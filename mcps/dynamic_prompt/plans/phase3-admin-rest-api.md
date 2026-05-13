# Phase 3: 管理REST API (reload-config + health)

## 目的

管理Webから「YAML編集後の即時キャッシュ無効化」を呼ぶための最小限のREST APIをMCPサービスに追加する。`MCP_ADMIN_TOKEN` でBearer認証。

`config_source.py` に `write_text` を追加して、（将来的なCLI/テスト用途として）統一APIを整える。

## 前提

- Phase 1 完了が望ましい（並行実装も可能）
- このフェーズはFirestore実装に依存しない

## 完了基準

- `POST /admin/api/reload-config` が `MCP_ADMIN_TOKEN` 認証下で `config_store.reload()` を実行し、202返却
- `GET /admin/api/health` がトークン認証下で 200返却
- 認証なし/トークン不一致 で 401返却
- `MCP_ADMIN_TOKEN` 未設定時は admin routes をマウントしない（起動ログに警告）
- `ConfigSource.write_text` が LocalConfigSource / GCSConfigSource 両方で動作（テスト緑化）

## ステップ

### 3.1 admin_api.py 新規

`src/dynamic_prompt/admin_api.py`:

```python
import hmac
import logging
import os
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)


def _admin_token() -> str | None:
    return os.environ.get("MCP_ADMIN_TOKEN") or None


def _check_auth(request: Request) -> JSONResponse | None:
    token = _admin_token()
    if not token:
        return JSONResponse({"error": "admin api disabled"}, status_code=503)
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    provided = header[7:].strip()
    if not hmac.compare_digest(provided, token):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    user_email = request.headers.get("x-user-email")
    if user_email:
        logger.info("admin %s %s by %s", request.method, request.url.path, user_email)
    return None


async def health(request: Request) -> JSONResponse:
    if (resp := _check_auth(request)) is not None:
        return resp
    return JSONResponse({"status": "ok"})


async def reload_config(request: Request) -> JSONResponse:
    if (resp := _check_auth(request)) is not None:
        return resp
    from dynamic_prompt.config import config_store
    try:
        config_store.reload()
        return JSONResponse({"status": "reloaded"}, status_code=202)
    except Exception as exc:
        logger.exception("config reload failed")
        return JSONResponse({"error": str(exc)}, status_code=500)


def build_admin_routes() -> list[Route]:
    if not _admin_token():
        logger.warning("MCP_ADMIN_TOKEN unset; admin api routes not mounted")
        return []
    return [
        Route("/admin/api/health", health, methods=["GET"]),
        Route("/admin/api/reload-config", reload_config, methods=["POST"]),
    ]
```

### 3.2 main.py への組み込み

[main.py:128-139](../src/dynamic_prompt/main.py#L128-L139) の `combined = Starlette(...)` を修正:

```python
from dynamic_prompt.admin_api import build_admin_routes

combined = Starlette(
    routes=[
        Route("/", homepage),
        Route("/events", sse_endpoint),
        Route("/api/pending", pending_quiz),
        Route("/api/submit", submit_answers, methods=["POST"]),
        Route("/api/save_words", save_words, methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"),
        *build_admin_routes(),
        Mount("/", app=mcp_app),
    ],
    lifespan=combined_lifespan,
)
```

### 3.3 config_source.py の write_text 追加

`ConfigSource` Protocolに以下を追加:

```python
def write_text(self, relative_path: str, text: str) -> None: ...
```

`LocalConfigSource.write_text`:
```python
def write_text(self, relative_path: str, text: str) -> None:
    target = self.base_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
```

`GCSConfigSource.write_text`:
```python
def write_text(self, relative_path: str, text: str) -> None:
    key = self._key(relative_path)
    blob = self._bucket.blob(key)
    blob.upload_from_string(text, content_type="application/yaml")
```

（注: `_key` メソッドが既存にあるか要確認。なければ既存読み込み側のキー組み立てロジックを抽出してから追加）

### 3.4 テスト追加

`tests/test_admin_api.py`:
- `MCP_ADMIN_TOKEN` 未設定で `build_admin_routes()` が空リストを返す
- httpx + ASGITransport で `/admin/api/health` への認証付き/なしリクエスト
- `/admin/api/reload-config` 呼び出しで `config_store.reload()` が呼ばれること（monkeypatchで検証）

`tests/test_config_source_write.py`:
- `LocalConfigSource` で tmp_path に書き込み → 読み戻して一致
- 親ディレクトリが存在しないパスでも書き込めること
- (GCS版は本物のGCSを叩くテストは書かない。fakeでもMockでもよいが優先度低 — 一旦スキップ)

### 3.5 動作確認

```powershell
cd c:\CodeRoot\my_ai_tools\mcps\dynamic_prompt
uv run --project . pytest src/dynamic_prompt/tests/test_admin_api.py -v
uv run --project . pytest src/dynamic_prompt/tests/test_config_source_write.py -v

# 起動して手動確認
$env:TRANSPORT="http"; $env:PORT="8080"; $env:MCP_ADMIN_TOKEN="dev"
uv run dynamic_prompt
# 別ターミナル:
curl -i http://localhost:8080/admin/api/health
# → 401
curl -i -H "Authorization: Bearer dev" http://localhost:8080/admin/api/health
# → 200
curl -i -X POST -H "Authorization: Bearer dev" http://localhost:8080/admin/api/reload-config
# → 202
```

## ロールバック

`admin_api.py` を削除し、`main.py` で `*build_admin_routes()` の行を消すだけ。本番への影響なし。
