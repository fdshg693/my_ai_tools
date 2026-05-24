# 機能B: ユーザー切り替え（memo 直結 / 個人ローカル）

## 目的・背景

現状、接続ユーザーは「接続単位」で固定（stdio は起動時 `--user`、HTTP は毎リクエストの
`?user=`）。切り替えには再接続/再起動が必須で、Claude アプリのように再接続を制御できない
クライアントでは事実上切り替えられない。

そこで **「安定した client 識別子」と「可変の現在ユーザー」を分離**し、`switch_user` ツール
一発で切り替えられるようにする。運用前提は **個人ローカルのみ**（認可ゲート不要・in-memory
状態で十分）。中継 MCP は挟まず memo 直結。

### 鍵の選択（検証済み）

HTTP はステートフルだが `Mcp-Session-Id` は再接続で変わるため、切替状態の保持鍵には不適。
**鍵は自前 `?client_id=`** を使う（機能A のログと同一ソース）。`Mcp-Session-Id` は機能A で
観測するのみ。

## 変更ファイル

| ファイル | 内容 |
|---------|------|
| `src/memo/auth.py` | in-memory `_http_user_by_client` マップ + `current_user` 拡張 + `http_client_id` / `switch_http_user` / `transport_is_http` |
| `src/memo/tools/user.py` | 新ツール `switch_user(target)` |
| `src/memo/main.py` | HOST 既定 `0.0.0.0` → `127.0.0.1` |
| `src/memo/tests/test_mcp_client.py` | EXPECTED_TOOLS + switch テスト |

## 設計（auth.py）

```python
_http_user_by_client: dict[str, str] = {}   # 安定 client_id → 現在ユーザー（in-memory）

def http_client_id() -> str | None:          # ?client_id=（機能A と同一ソース）
def set_http_transport(is_http): ...         # 起動時に main() が一度だけ確定させる
def transport_is_http() -> bool:             # 起動時に確定したフラグを返す（毎回検出しない）
def switch_http_user(client_id, target):     # _http_user_by_client[client_id] = target

def current_user() -> str | None:
    # stdio                              → _stdio_user
    # HTTP, client_id 無                 → 従来の ?user=（後方互換）
    # HTTP, client_id 有 + ?user= 有     → _http_user_by_client.setdefault(client_id, user)
    # HTTP, client_id 有 + ?user= 無     → _http_user_by_client.get(client_id)
```

`setdefault` が肝：機能A のミドルウェアが先に `current_user()` を呼んでも初回値を確定し、
`switch_user` 後の上書き値を壊さない。マップは in-memory（再起動で初期 `?user=` に戻る。
個人用途で許容。TTL/eviction は将来検討＝現状省略）。GIL 下の単一キー代入・参照は原子的で
ロック不要。

## 設計（tools/user.py の `switch_user(target)`）

1. `resolve_caller()` で発呼者を識別（未識別/未登録は既存エラーで拒否）。
2. `target` を strip、空なら error。`is_registered_user(target)` 未登録なら拒否。
3. `transport_is_http()` が False（stdio）→ `set_stdio_user(target)`（再起動不要）。
4. HTTP → `client_id = http_client_id()`。無ければ「`?client_id=` を付けて接続」エラー。
   有れば `switch_http_user(client_id, target)`。
5. 個人ローカル前提で **admin への切替も secret 不要**。戻り値は簡潔メッセージ。

## main.py: HOST 既定変更（要検討事項）

`host = os.environ.get("HOST", "127.0.0.1")`。`switch_user` は secret なしで admin にもなれる
ため、`0.0.0.0` 公開はネットワーク上の誰でも admin 化できる穴。ローカル束縛で塞ぐ。
コンテナ運用で `0.0.0.0` が要る場合は env で明示し前段に認証（dynamic_prompt の GoogleProvider
相当）を置くこと、と README/CLAUDE.md に注記。

## 再利用
`resolve_caller` / `is_registered_user` / `set_stdio_user`（いずれも既存）。

## テスト（test_mcp_client.py）
- `EXPECTED_TOOLS` に `switch_user` 追加。
- `test_switch_user_stdio_changes_owner`: `set_stdio_user(admin)` → `switch_user("alice")` →
  以後 `create_memo` の所有者が alice（`list_memos` で確認）。teardown で `set_stdio_user(None)`。
- `test_switch_user_rejects_unregistered_target` / `test_switch_user_rejects_unidentified_caller`。
- HTTP 分岐は auth 単体（`monkeypatch` で `get_http_request` をダミー request 差し替え）：
  client_id 有+初回 user 登録 / 同 client_id 2回目は setdefault で初回保持 /
  `switch_http_user` 後は切替値 / client_id 無は従来 user。
- 後方互換：client_id を渡さない既存 stdio テスト群が green のまま。

## 手動検証
- stdio: `uv run memo --user admin` → `switch_user alice` → `create_memo` → `list_memos` で
  alice 所有（再起動不要）。
- HTTP: `http://127.0.0.1:8080/mcp?user=admin&client_id=desktop-1` で接続 → `switch_user alice`
  → 以後 alice 所有。機能A ログで `user=` が admin→alice に変化、`client_id`/`session` の
  安定/張り替わりを目視。別 client_id は独立。client_id 無しの `switch_user` はエラー。
