"""ユーザー管理用のローカル Web サーバーのアプリ本体 (``memo-admin``)。

DB を直接いじらずに ``users`` 台帳を手動で素早く管理するための画面を提供する。
MCP サーバー (stdio/http) とは別プロセスで動き、同じ ``memo.db`` を読み書きする
(SQLite は WAL モードなので別プロセスからの同時アクセスでも安全)。

層の位置づけ: これはトランスポート端 (Web UI) であり、認可は持たない無認証
admin 面のまま。ただしユーザー CRUD のドメイン不変条件 (name 必須・trim・部分
更新・最後の管理者の削除/降格禁止) は MCP ツールと共有する ``service.user`` に
集約し、ここは service のドメイン例外を HTTP ステータスへ翻訳するだけにする。
``is_admin`` の編集はこの Web UI からのみ行える (MCP ツールでは変更しない)。

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

from memo.service.category import (
    CategoryAlreadyExists,
    CategoryNameRequired,
    CategoryNotFound,
    CannotModifyOthers,
    create_category as create_category_service,
    delete_category_by_id as delete_category_by_id_service,
    list_categories as list_categories_service,
    rename_category_by_id as rename_category_by_id_service,
)
from memo.service.memo import (
    TitleRequired,
    UnknownCategory,
    count_memos as count_memos_service,
    create_memo as create_memo_service,
    delete_memo as delete_memo_service,
    list_memos as list_memos_service,
    update_memo as update_memo_service,
)
from memo.service.user import (
    CannotDeleteLastAdmin,
    CannotDemoteLastAdmin,
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
        user = get_user(name)  # 存在確認 (無ければ 404)
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)

    page = _int_param(request, "page", 1, minimum=1)
    per_page = min(_int_param(request, "per_page", DEFAULT_PER_PAGE, minimum=1), MAX_PER_PAGE)
    # category クエリがあれば同一カテゴリに絞る (空なら全カテゴリ)。
    category = request.query_params.get("category") or None

    # この画面は「特定ユーザーのメモ」を見るので、不変の user_id で絞る。
    user_id = user["id"]
    total = count_memos_service(user_id, category=category)
    memos = list_memos_service(
        user_id, limit=per_page, offset=(page - 1) * per_page, category=category
    )
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


async def api_create_user_memo(request: Request) -> JSONResponse:
    """指定ユーザーのメモを新規作成する。title 必須・ユーザーが無ければ 404。

    所有者はパスの ``name`` に固定する (この画面は「特定ユーザーのメモ」を扱うので
    is_admin は使わず、常にそのユーザーのメモとして作る)。
    """
    name = request.path_params["name"]
    try:
        user = get_user(name)  # 存在確認 (無ければ 404)
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)

    body = await request.json()
    # title 必須チェックと trim は service 側 (TitleRequired)。category 省略時は
    # repository が OTHERS に正規化する。
    title = str(body.get("title", ""))
    summary = str(body.get("summary", ""))
    category = body.get("category")
    category = category if isinstance(category, str) else None
    try:
        memo = create_memo_service(user["id"], title, summary, category)
    except TitleRequired:
        return JSONResponse({"error": "title is required"}, status_code=400)
    except UnknownCategory as e:
        return JSONResponse(
            {"error": f"category '{e.category}' is not registered"}, status_code=400
        )
    return JSONResponse(memo, status_code=201)


async def api_update_user_memo(request: Request) -> JSONResponse:
    """指定ユーザーのメモを更新する (title / summary の部分更新)。

    対象はそのユーザーが所有するメモに限る (is_admin=False で絞る)。存在しない/
    他人のメモなら 404。空の title への更新は拒否する (400)。
    """
    name = request.path_params["name"]
    memo_id = request.path_params["memo_id"]
    try:
        user = get_user(name)  # 存在確認 (無ければ 404)
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)

    body = await request.json()
    # 文字列でないフィールドは None = 「変更しない」。trim と空 title 拒否
    # (TitleRequired) は service 側。category の空文字=OTHERS は repository が解釈する。
    title = body.get("title")
    title = title if isinstance(title, str) else None
    summary = body.get("summary")
    summary = summary if isinstance(summary, str) else None
    category = body.get("category")
    category = category if isinstance(category, str) else None

    try:
        memo = update_memo_service(
            user["id"], memo_id, title, summary, category=category
        )
    except TitleRequired:
        return JSONResponse({"error": "title is required"}, status_code=400)
    except UnknownCategory as e:
        return JSONResponse(
            {"error": f"category '{e.category}' is not registered"}, status_code=400
        )
    if memo is None:
        return JSONResponse(
            {"error": f"memo id={memo_id} not found"}, status_code=404
        )
    return JSONResponse(memo)


async def api_delete_user_memo(request: Request) -> JSONResponse:
    """指定ユーザーのメモを削除する。そのユーザーが所有するメモのみ (無ければ 404)。"""
    name = request.path_params["name"]
    memo_id = request.path_params["memo_id"]
    try:
        user = get_user(name)  # 存在確認 (無ければ 404)
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)
    if not delete_memo_service(user["id"], memo_id):
        return JSONResponse(
            {"error": f"memo id={memo_id} not found"}, status_code=404
        )
    return JSONResponse({"deleted": memo_id})


async def api_list_user_categories(request: Request) -> JSONResponse:
    """指定ユーザーのカテゴリ一覧を名前順に返す (メモ編集の選択肢・管理用)。

    ユーザーが台帳に存在しなければ 404。
    """
    name = request.path_params["name"]
    try:
        user = get_user(name)  # 存在確認 (無ければ 404)
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)
    return JSONResponse(list_categories_service(user["id"]))


async def api_create_user_category(request: Request) -> JSONResponse:
    """指定ユーザーのカテゴリを新規作成する。name 必須 (400)・重複 (409)。"""
    name = request.path_params["name"]
    try:
        user = get_user(name)  # 存在確認 (無ければ 404)
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)

    body = await request.json()
    try:
        created = create_category_service(user["id"], str(body.get("name", "")))
    except CategoryNameRequired:
        return JSONResponse({"error": "name is required"}, status_code=400)
    except CategoryAlreadyExists as e:
        return JSONResponse(
            {"error": f"category '{e.name}' already exists"}, status_code=409
        )
    return JSONResponse(created, status_code=201)


async def api_rename_user_category(request: Request) -> JSONResponse:
    """指定ユーザーのカテゴリをリネームする (紐づくメモのカテゴリも追従)。

    OTHERS は変更不可 (403)・対象なし (404)・新名称が空 (400)・既存と衝突 (409)。
    """
    name = request.path_params["name"]
    category_id = request.path_params["category_id"]
    try:
        user = get_user(name)  # 存在確認 (無ければ 404)
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)
    body = await request.json()
    try:
        renamed = rename_category_by_id_service(
            user["id"], category_id, str(body.get("name", ""))
        )
    except CategoryNameRequired:
        return JSONResponse({"error": "name is required"}, status_code=400)
    except CannotModifyOthers as e:
        return JSONResponse({"error": str(e)}, status_code=403)
    except CategoryNotFound as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except CategoryAlreadyExists as e:
        return JSONResponse(
            {"error": f"category '{e.name}' already exists"}, status_code=409
        )
    return JSONResponse(renamed)


async def api_delete_user_category(request: Request) -> JSONResponse:
    """指定ユーザーのカテゴリを削除する (紐づくメモは OTHERS へ付け替え)。

    OTHERS は削除不可 (403)・対象なし (404)。
    """
    name = request.path_params["name"]
    category_id = request.path_params["category_id"]
    try:
        user = get_user(name)  # 存在確認 (無ければ 404)
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)
    try:
        delete_category_by_id_service(user["id"], category_id)
    except CannotModifyOthers as e:
        return JSONResponse({"error": str(e)}, status_code=403)
    except CategoryNotFound as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    return JSONResponse({"deleted": category_id})


async def api_create_user(request: Request) -> JSONResponse:
    """ユーザーを新規登録する。name 必須・重複は 409。is_admin で管理者作成も可。"""
    body = await request.json()
    is_admin = bool(body.get("is_admin", False))
    try:
        created = create_user(
            str(body.get("name", "")),
            str(body.get("display_name", "")),
            str(body.get("note", "")),
            is_admin,
        )
    except NameRequired:
        return JSONResponse({"error": "name is required"}, status_code=400)
    except UserAlreadyExists as e:
        return JSONResponse(
            {"error": f"user '{e.name}' already exists"}, status_code=409
        )
    return JSONResponse(created, status_code=201)


async def api_update_user(request: Request) -> JSONResponse:
    """ユーザーの display_name / note / is_admin を更新する。name (ログインハンドル) は不変。

    ``is_admin`` はこの Web UI からのみ編集できる (MCP ツールでは変更しない)。
    最後の1人の管理者は降格できない (409)。
    """
    name = request.path_params["name"]
    body = await request.json()
    # 省略されたフィールドは None を渡して「変更しない」を表現する (service が trim する)
    display_name = body.get("display_name")
    note = body.get("note")
    is_admin = body.get("is_admin")
    try:
        updated = update_user(
            name,
            display_name if isinstance(display_name, str) else None,
            note if isinstance(note, str) else None,
            bool(is_admin) if is_admin is not None else None,
        )
    except CannotDemoteLastAdmin as e:
        return JSONResponse(
            {"error": f"cannot remove admin from the last admin user '{e.name}'"},
            status_code=409,
        )
    except UserNotFound:
        return JSONResponse({"error": f"user '{name}' not found"}, status_code=404)
    return JSONResponse(updated)


async def api_delete_user(request: Request) -> JSONResponse:
    """ユーザーを台帳から削除する。最後の1人の管理者は削除不可 (tools の delete_user と同じガード)。"""
    name = request.path_params["name"]
    try:
        delete_user(name)
    except CannotDeleteLastAdmin as e:
        return JSONResponse(
            {"error": f"cannot delete the last admin user '{e.name}'"},
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
            Route("/api/users/{name}/memos", api_create_user_memo, methods=["POST"]),
            Route(
                "/api/users/{name}/memos/{memo_id:int}",
                api_update_user_memo,
                methods=["PUT"],
            ),
            Route(
                "/api/users/{name}/memos/{memo_id:int}",
                api_delete_user_memo,
                methods=["DELETE"],
            ),
            Route(
                "/api/users/{name}/categories",
                api_list_user_categories,
                methods=["GET"],
            ),
            Route(
                "/api/users/{name}/categories",
                api_create_user_category,
                methods=["POST"],
            ),
            Route(
                "/api/users/{name}/categories/{category_id:int}",
                api_rename_user_category,
                methods=["PUT"],
            ),
            Route(
                "/api/users/{name}/categories/{category_id:int}",
                api_delete_user_category,
                methods=["DELETE"],
            ),
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
