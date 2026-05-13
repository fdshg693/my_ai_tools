# Phase 5: 本番データ移行 + MCPサービス切替

## 目的

本番SQLite `/data/vocab.db` のデータを本番Firestoreにコピーし、MCPサービスを `DATA_BACKEND=firestore` で稼働させる。

**このフェーズは本番データに影響する不可逆操作を含む**。各ステップでチェックを入れて慎重に進めること。

## 前提

- Phase 4 が完了（Firestore DB + インデックス + IAMが本番に展開済み）
- Firestoreインデックスのビルドがすべて完了している
- Phase 2 の移行スクリプトがローカルで動作確認済み

## 完了基準

- 本番Firestoreに既存SQLite全データが入っている（件数突き合わせ一致）
- MCPサービスが `DATA_BACKEND=firestore` で稼働
- すべてのMCPツールが本番Firestoreデータで正常動作
- 旧 `/data/vocab.db` はバックアップとしてGCSに退避済み（1週間以上保持）

## ステップ

### 5.1 SQLiteバックアップ取得（最重要）

Cloud Run のボリュームマウント先 `/data/vocab.db` をローカルマシンに取得:

選択肢 A: GCS経由でコピー（推奨）
```powershell
# MCPサービスは稼働を継続したまま、GCSバケットを直接見る
gsutil cp gs://dynamic-prompt-mcp-dp-data/vocab.db .\vocab.db.backup-$(Get-Date -Format yyyyMMdd-HHmmss)
```

選択肢 B: 一度Cloud Runの開発用シェルで `gsutil cp /data/vocab.db gs://.../backup/...` でバックアップを別キーに退避

バックアップ完了を `gsutil ls -l gs://.../backup/` で確認。

### 5.2 移行のdry-run

ローカルからバックアップしたSQLiteを使って本番Firestoreへの書き込みを**dry-run**:

```powershell
cd c:\CodeRoot\my_ai_tools\mcps\dynamic_prompt
$env:GOOGLE_CLOUD_PROJECT="dynamic-prompt-mcp"
# Firestoreエミュレータ環境変数は外しておくこと:
$env:FIRESTORE_EMULATOR_HOST=$null

uv run python -m dynamic_prompt.migrate_to_firestore `
    --source .\vocab.db.backup-YYYYMMDD-HHMMSS `
    --project dynamic-prompt-mcp `
    --dry-run
```

期待される出力:
```
[dry-run] Would write unknown_words: 234 docs
[dry-run] Would write quiz_sessions: 56 docs + 412 question subdocs
[dry-run] Would write story_topics: 18 docs
```

件数が想定どおりかチェック。

### 5.3 本番移行実行

```powershell
uv run python -m dynamic_prompt.migrate_to_firestore `
    --source .\vocab.db.backup-YYYYMMDD-HHMMSS `
    --project dynamic-prompt-mcp
```

実行後、スクリプトが自動で件数突き合わせを行う:
```
✓ unknown_words: SQLite=234, Firestore=234
✓ quiz_sessions: SQLite=56, Firestore=56
✓ story_topics: SQLite=18, Firestore=18
Migration complete.
```

不一致があれば exit code 1 で停止する。

**スポットチェック**:
```powershell
# 1件取得して目視確認
gcloud firestore documents list --collection-ids=unknown_words --limit=3 --project=dynamic-prompt-mcp
```

### 5.4 サービス切替

`infra/terraform/cloud_run.tf` に env 追加:
```hcl
env {
  name  = "DATA_BACKEND"
  value = "firestore"
}
```

`DB_PATH` の env は削除（または値を空に）。

```powershell
cd c:\CodeRoot\my_ai_tools\mcps\dynamic_prompt\infra
just tf-plan
# 期待される変更: cloud_run.app の env 変更のみ
just tf-apply
```

Cloud Run が新リビジョンを起動し、トラフィックを切り替える（数十秒）。

### 5.5 動作確認（本番）

```powershell
# ヘルスチェック
$URL = just cloud-url
curl -i "$URL/health"
# → 200

# MCPツール（OAuth付き）で操作確認
# Claude Desktop or Claude.ai でMCP接続:
#   - get_words を呼ぶ → Firestoreの単語が返る
#   - save_words で新規追加 → Firestoreに反映確認
#   - send_quiz → 受信できる
#   - get_quiz_results → 過去履歴が見える
#   - get_past_topics → 過去の話題が返る
```

ログ確認:
```powershell
gcloud run services logs read dynamic-prompt --limit=50 --project=dynamic-prompt-mcp
```

エラーがないこと、`DATA_BACKEND=firestore` で起動した形跡を確認。

### 5.6 旧データの退避

`/data/vocab.db` を `_archived/` ディレクトリに移動（即時削除はせず1週間以上残す）:

```powershell
gsutil mv gs://dynamic-prompt-mcp-dp-data/vocab.db gs://dynamic-prompt-mcp-dp-data/_archived/vocab.db-$(Get-Date -Format yyyyMMdd)
gsutil mv "gs://dynamic-prompt-mcp-dp-data/vocab.db-shm" "gs://dynamic-prompt-mcp-dp-data/_archived/" 2>$null
gsutil mv "gs://dynamic-prompt-mcp-dp-data/vocab.db-wal" "gs://dynamic-prompt-mcp-dp-data/_archived/" 2>$null
```

### 5.7 1週間後のクリーンアップ（フォローアップタスク）

- 旧 `_archived/vocab.db-*` の削除
- `database.py` のSQLiteコード削除（shim撤去）
- `repo/sqlite_repo.py` の削除
- 関連テストの整理
- `infra/terraform/cloud_run.tf` から `/data` ボリュームマウントを削除するかは要検討（FASTMCP_HOMEはまだ使う想定）

## ロールバック

### 移行中のロールバック
- 5.2 のdry-runで件数が合わない → スクリプトを修正してリトライ
- 5.3 の書き込みで一部失敗 → Firestoreの該当コレクションをコンソールで一括削除し、5.3 を再実行（自然IDは upsert なので重複しない）

### 切替後のロールバック
- 5.4 の `terraform apply` を巻き戻し（`DATA_BACKEND` env を削除して再apply）→ SQLiteに戻る
- ただし切替後に書かれたFirestoreの新規データはSQLiteに反映されないため、切替後すぐの問題は早めに検知すること
- バックアップから vocab.db を復元する場合:
  ```powershell
  gsutil cp gs://.../_archived/vocab.db-YYYYMMDD gs://dynamic-prompt-mcp-dp-data/vocab.db
  # その後 terraform apply で DATA_BACKEND を除去
  ```

## 注意

- 移行中もMCPサービスは稼働し続け、SQLiteへの書き込みが起こり得る。「移行スナップショット取得」→「すぐに切替」を短時間で行うのが安全
- 完璧を期すならメンテナンスモード（Cloud Runを一時停止）を挟む案もあるが、個人利用なら不要
- Cloud Run revisionのトラフィック切替時に旧/新両方が一瞬走るが、SQLiteは旧側のみ・Firestoreは新側のみが参照するため不整合の可能性ゼロではない。気になるなら revision を `latest=100%` で完全切替してから動作確認
