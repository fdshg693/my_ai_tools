"""ユーザー管理用のローカル Web サーバーのアプリ本体 (``memo-admin``)。

DB を直接いじらずに ``users`` 台帳を手動で素早く管理するための画面を提供する。
MCP サーバー (stdio/http) とは別プロセスで動き、同じ ``memo.db`` を読み書きする
(SQLite は WAL モードなので別プロセスからの同時アクセスでも安全)。

層の位置づけ: これはトランスポート端 (Web UI) であり、認可は持たない無認証
admin 面のまま。ただしユーザー CRUD のドメイン不変条件 (name 必須・trim・部分
更新・admin 削除禁止) は MCP ツールと共有する ``service.user`` に集約し、ここは
service のドメイン例外を HTTP ステータスへ翻訳するだけにする。

セキュリティ: 既定で ``127.0.0.1`` にだけバインドする無認証の admin 専用ツール
(switch_user 同様、無認証で全ユーザーを操作できる)。``MEMO_ADMIN_HOST`` で広げる
場合は前段に認証を置くこと (起動は ``main.py``)。
"""

import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from memo.repository.memo import count_memos_db, list_memos_db
from memo.service.user import (
    CannotDeleteAdmin,
    NameRequired,
    UserAlreadyExists,
    UserNotFound,
    create_user,
    delete_user,
    get_user,
    list_users,
    update_user,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# メモ一覧のページング既定値 (1ページあたりの件数とその上限)。
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100


def _int_param(request: Request, name: str, default: int, *, minimum: int) -> int:
    """クエリ文字列から整数を読む。未指定・不正値は ``default`` にフォールバック。"""
    raw = request.query_params.get(name)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def index(_request: Request) -> FileResponse:
    """管理画面 (admin.html) を配信する。"""
    return FileResponse(STATIC_DIR / "admin.html")


async def api_list_users(_request: Request) -> JSONResponse:
    """登録済みユーザーを名前順に返す。"""
    return JSONResponse(list_users())


async def api_get_user(request: Request) -> JSONResponse:
    """ユーザーを1件返す。無ければ 404。"""
    name = request.path_params["name"]
    try:
        user = get_user(name)
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)
    return JSONResponse(user)


async def api_list_user_memos(request: Request) -> JSONResponse:
    """指定ユーザーのメモを新しい順にページングして返す (一覧表示専用)。

    クエリ: ``page`` (1始まり) / ``per_page`` (1〜``MAX_PER_PAGE``)。
    ユーザーが台帳に存在しなければ 404。メモは多くなり得るので、件数 (``total``)
    と総ページ数 (``total_pages``) を添えて返す。
    """
    name = request.path_params["name"]
    try:
        get_user(name)  # 存在確認 (無ければ 404)
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)

    page = _int_param(request, "page", 1, minimum=1)
    per_page = min(_int_param(request, "per_page", DEFAULT_PER_PAGE, minimum=1), MAX_PER_PAGE)

    # この画面は「特定ユーザーのメモ」を見るので is_admin は使わず user で絞る。
    total = count_memos_db(name)
    memos = list_memos_db(name, limit=per_page, offset=(page - 1) * per_page)
    total_pages = (total + per_page - 1) // per_page if total else 0
    return JSONResponse(
        {
            "user": name,
            "items": memos,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }
    )


async def api_create_user(request: Request) -> JSONResponse:
    """ユーザーを新規登録する。name 必須・重複は 409。"""
    body = await request.json()
    try:
        created = create_user(
            str(body.get("name", "")),
            str(body.get("display_name", "")),
            str(body.get("note", "")),
        )
    except NameRequired:
        return JSONResponse({"error": "name is required"}, status_code=400)
    except UserAlreadyExists as e:
        return JSONResponse(
            {"error": f"user '{e.name}' already exists"}, status_code=409
        )
    return JSONResponse(created, status_code=201)


async def api_update_user(request: Request) -> JSONResponse:
    """ユーザーの display_name / note を更新する。name (識別子) は不変。"""
    name = request.path_params["name"]
    body = await request.json()
    # 省略されたフィールドは None を渡して「変更しない」を表現する (service が trim する)
    display_name = body.get("display_name")
    note = body.get("note")
    try:
        updated = update_user(
            name,
            display_name if isinstance(display_name, str) else None,
            note if isinstance(note, str) else None,
        )
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)
    return JSONResponse(updated)


async def api_delete_user(request: Request) -> JSONResponse:
    """ユーザーを台帳から削除する。admin 自身は削除不可 (tools の delete_user と同じガード)。"""
    name = request.path_params["name"]
    try:
        delete_user(name)
    except CannotDeleteAdmin as e:
        return JSONResponse(
            {"error": f"cannot delete the admin user '{e.name}'"},
            status_code=403,
        )
    except UserNotFound:
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
            Route("/api/users/{name}/memos", api_list_user_memos, methods=["GET"]),
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
