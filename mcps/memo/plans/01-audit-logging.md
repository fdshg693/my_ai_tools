# 機能A: 監査ログ（ミドルウェア方式）

## 目的・背景

ツール呼び出しを横断的に1箇所で記録する。主目的は **`Mcp-Session-Id` がどう変化するかの
可視化**で、機能B（ユーザー切り替え）の鍵に何を使うべきか（自前 `?client_id=` vs
プロトコルの `Mcp-Session-Id`）を実地で見極める材料にする。

### 前提（fastmcp 3.1.1 を実コードで確認）

- ミドルウェアは `mcp.add_middleware(instance)` で登録。`Middleware.on_message` が全メッセージの
  最外層フック（`middleware.py` の `_dispatch_handler` で常に最初に巻かれる）。`context.method`
  で `initialize` / `tools/call` 等を判別。`tools/call` のとき `context.message` は
  `CallToolRequestParams`（`.name` を持つ）。
- HTTP はデフォルトでステートフル。`Mcp-Session-Id` は1接続を通じて安定するが、**再接続
  （再 initialize）で別 UUID** になる。最初の initialize リクエストにはヘッダが無く、
  サーバーがレスポンスで採番→以後のリクエストでクライアントがエコーする。
- fastmcp は `fastmcp` ロガーにのみハンドラを付け root を触らない。`memo.*` は `basicConfig`
  しないと出力されない。**stdio は stdout が JSON-RPC 本体なのでログは必ず stderr へ。**

## 変更/新規ファイル

| 種別 | ファイル | 内容 |
|------|---------|------|
| 新規 | `src/memo/logging_middleware.py` | `AuditLogMiddleware` |
| 変更 | `src/memo/main.py` | ログ基盤 `_configure_logging` + `--debug` + `mcp.add_middleware` |
| 変更 | `src/memo/tests/test_mcp_client.py` | `caplog` でログ検証 |

## 設計

### AuditLogMiddleware（`on_message` をオーバーライド）

- `on_message` で全メソッドを捕捉し、`await call_next(context)` で素通し。
- HTTP フィールドは `get_http_request()` 経由（stdio は RuntimeError → 全 None）：
  - `client_id` = `request.query_params.get("client_id")`（機能B と同一ソース）
  - `raw_user` = `request.query_params.get("user")`（解決前）
  - `session` = `request.headers.get("mcp-session-id")`（生ヘッダ＝観測対象）
- 解決後ユーザーは `memo.auth.current_user()`（同期・I/O なし。`setdefault` で冪等）。
- `request_id` は context 未確立時に例外を投げうるので `_safe_request_id()` で
  `try/except RuntimeError` ラップ。

出力:
- **INFO（既定）**: `tools/call` のとき1行
  `tool=<name> user=<resolved> client_id=<id> session=<Mcp-Session-Id>`
- **DEBUG**: 全メソッドで
  `method=<m> request_id=<rid> client_id=<id> raw_user=<生?user=> resolved_user=<解決後> session=<id>`

INFO/DEBUG はロガーレベルに委譲（明示分岐なし）。

### ログ基盤（main.py）

```python
def _configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(stream=sys.stderr, level=level,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("memo").setLevel(level)
```

`mcp = FastMCP("memo")` の直後に `mcp.add_middleware(AuditLogMiddleware())`。
argparse に `--debug`（`action="store_true"`, default は env `MEMO_LOG_DEBUG` in (1/true/yes)）。
`main()` 冒頭で `_configure_logging(args.debug)` を呼ぶ。

## 再利用
- `memo.auth.current_user`
- `fastmcp.server.dependencies.get_http_request`（auth.py と同流儀）
- `MiddlewareContext.message.name`

## テスト（test_mcp_client.py, `caplog`）
- `test_audit_log_emits_one_line_per_tool_call`: `caplog.at_level(INFO, "memo.logging_middleware")`
  下で `create_memo` → `tool=create_memo` と `user=` を含む INFO 行。
- `test_audit_log_debug_includes_initialize`: `caplog.at_level(DEBUG, ...)` で接続時に
  `method=initialize` の DEBUG 行（on_message が tools/call 以外も拾う証跡）。
- 既存テストは `main()` を通らないので basicConfig 非依存（caplog がハンドラを差す）。

## 手動検証
- stdio: `uv run memo --user admin --debug` → 接続しツール実行。ログは stderr。
  session はクエリ無しで None。
- HTTP: `TRANSPORT=http PORT=8080 uv run memo --debug`、`?user=alice&client_id=desktop-1` で接続。
  initialize の DEBUG 行と以後の tools/call INFO 行で同一 `session=<uuid>`、
  **切断→再接続で session が別 uuid・client_id は不変**を目視。
