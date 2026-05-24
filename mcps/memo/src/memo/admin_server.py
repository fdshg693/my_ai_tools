"""ユーザー管理用のローカル Web サーバー (独立コマンド ``memo-admin``)。

DB を直接いじらずに ``users`` 台帳を手動で素早く管理するための画面を提供する。
MCP サーバー (stdio/http) とは別プロセスで動き、同じ ``memo.db`` を読み書きする
(SQLite は WAL モードなので別プロセスからの同時アクセスでも安全)。

層の位置づけ: これは ``logging_middleware`` と同様「層の外側」のトランスポート端で、
ビジネスロジックは持たず ``repository.user`` をそのまま呼ぶ。``tools/* → authz →
repository/* → database`` の一方向依存は崩さない。

セキュリティ: 既定で ``127.0.0.1`` にだけバインドする無認証の admin 専用ツール
(switch_user 同様、無認証で全ユーザーを操作できる)。``MEMO_ADMIN_HOST`` で広げる
場合は前段に認証を置くこと。
"""

import logging
import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from memo.database import ADMIN_USER, init_db
from memo.repository.user import (
    create_user_db,
    delete_user_db,
    get_user_db,
    list_users_db,
    update_user_db,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_PORT = 8090  # memo HTTP(8080) / dynamic_prompt quiz(8765) と衝突しない既定値


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def index(_request: Request) -> FileResponse:
    """管理画面 (admin.html) を配信する。"""
    return FileResponse(STATIC_DIR / "admin.html")


async def api_list_users(_request: Request) -> JSONResponse:
    """登録済みユーザーを名前順に返す。"""
    return JSONResponse(list_users_db())


async def api_get_user(request: Request) -> JSONResponse:
    """ユーザーを1件返す。無ければ 404。"""
    name = request.path_params["name"]
    user = get_user_db(name)
    if user is None:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)
    return JSONResponse(user)


async def api_create_user(request: Request) -> JSONResponse:
    """ユーザーを新規登録する。name 必須・重複は 409。"""
    body = await request.json()
    name = str(body.get("name", "")).strip()
    display_name = str(body.get("display_name", "")).strip()
    note = str(body.get("note", "")).strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    created = create_user_db(name, display_name, note)
    if created is None:
        return JSONResponse(
            {"error": f"user '{name}' already exists"}, status_code=409
        )
    return JSONResponse(created, status_code=201)


async def api_update_user(request: Request) -> JSONResponse:
    """ユーザーの display_name / note を更新する。name (識別子) は不変。"""
    name = request.path_params["name"]
    body = await request.json()
    # 省略されたフィールドは None を渡して「変更しない」を表現する
    display_name = body.get("display_name")
    note = body.get("note")
    updated = update_user_db(
        name,
        display_name.strip() if isinstance(display_name, str) else None,
        note.strip() if isinstance(note, str) else None,
    )
    if updated is None:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)
    return JSONResponse(updated)


async def api_delete_user(request: Request) -> JSONResponse:
    """ユーザーを台帳から削除する。admin 自身は削除不可 (tools の delete_user と同じガード)。"""
    name = request.path_params["name"]
    if name == ADMIN_USER:
        return JSONResponse(
            {"error": f"cannot delete the admin user '{ADMIN_USER}'"},
            status_code=403,
        )
    if not delete_user_db(name):
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)
    return JSONResponse({"deleted": name})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> Starlette:
    """管理画面の Starlette アプリを組み立てて返す (テストからも利用する)。"""
    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/users", api_list_users, methods=["GET"]),
            Route("/api/users", api_create_user, methods=["POST"]),
            Route("/api/users/{name}", api_get_user, methods=["GET"]),
            Route("/api/users/{name}", api_update_user, methods=["PUT"]),
            Route("/api/users/{name}", api_delete_user, methods=["DELETE"]),
            Mount(
                "/static",
                StaticFiles(directory=str(STATIC_DIR)),
                name="static",
            ),
        ]
    )


def main() -> None:
    """``memo-admin`` のエントリポイント。ローカル Web サーバーを起動する。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()  # memo.db が無い初回でもスキーマと admin を用意する

    host = os.environ.get("MEMO_ADMIN_HOST", "127.0.0.1")
    port = int(os.environ.get("MEMO_ADMIN_PORT", str(DEFAULT_PORT)))
    if host not in ("127.0.0.1", "localhost"):
        logger.warning(
            "MEMO_ADMIN_HOST=%s で外部公開しています。この管理画面は無認証で "
            "admin を含む全ユーザーを操作できるため、前段に認証を必ず置いてください。",
            host,
        )
    logger.info("memo-admin starting on http://%s:%d", host, port)
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
