# 管理者用WEBページ追加 + Firestore移行 — フェーズ別計画

## 全体像

dynamic_prompt MCPサーバに、Google認証で保護された管理者用WEBページ（Next.js）を追加する。同時にデータストアをSQLite→Firestoreに移行し、複数サービスからの同時アクセスを安全化する。

詳細な背景・確定事項は親計画 `~/.claude/plans/web-google-functional-quasar.md` を参照。

## フェーズ一覧

| Phase | 内容 | 不可逆性 | 依存 |
|---|---|---|---|
| [Phase 1](./phase1-repository-layer.md) | リポジトリ層導入（既存挙動を変えない） | 低 | なし |
| [Phase 2](./phase2-firestore-impl.md) | Firestore実装 + 移行スクリプト + エミュレータテスト | 低 | Phase 1 |
| [Phase 3](./phase3-admin-rest-api.md) | 管理REST API (reload-config + health) + config_source.write_text | 低 | なし（Phase 1と並行可） |
| [Phase 4](./phase4-infra-firestore.md) | Terraform: Firestore + インデックス + IAM + MCP_ADMIN_TOKEN | 中 | Phase 2, 3 |
| [Phase 5](./phase5-prod-migration.md) | 本番データ移行 + MCPサービス切替 | **高** | Phase 4 |
| [Phase 6](./phase6-nextjs-implementation.md) | Next.js管理Web実装（ローカル動作確認まで） | 低 | Phase 2, 3 |
| [Phase 7](./phase7-admin-deploy.md) | 管理WebのTerraform + Cloud Buildデプロイ | 中 | Phase 5, 6 |

## 推奨実行順

```
1 → 2 ⟍
        ⟶ 4 → 5
3 ─────⟋        ⟍
                  ⟶ 7
6 (Phase 2,3完了後、Phase 4-5と並行可能) ⟋
```

最短経路: `1 → 2 → 3 → 4 → 5 → 6 → 7`

## 重要な注意

- Phase 5（本番データ移行）は実行前に必ずSQLiteバックアップをGCSに保存
- Phase 7の初回 `terraform apply` は2回必要（NEXTAUTH_URLブートストラップ）
- 各フェーズの完了基準を満たしてから次へ進むこと
