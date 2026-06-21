"""ユーザー CRUD のドメインルール (MCP ツールと Web UI が共有する)。

``tools/user.py`` (MCP) と ``server/web/app.py`` (Web) に重複していた
ドメイン不変条件をここ一箇所に集約する:

- ``name`` 必須・trim、``display_name`` / ``note`` の trim と部分更新
  (None = 変更しない) セマンティクス。
- ``admin`` ユーザーは削除禁止。``name`` は不変 (更新できるのは属性のみ)。

**認可 (admin-only 判定) はここに入れない。** MCP 側は従来どおり
``resolve_caller()`` で admin を強制し、Web 側は無認証 admin 面のまま。
service が持つのは上記の「ドメイン不変条件」だけ。

戻り値は **構造化データ (dict) または例外** で表現し、文字列メッセージは
返さない (呼び出し側がメッセージや HTTP ステータスへ各自変換できるように)。
repository.user の素の戻り値 (create は重複時 None、delete は bool 等) を
踏まえ、例外に翻訳して曖昧さをなくす。
"""

from memo.infra.database import ADMIN_USER
from memo.repository.category import ensure_default_category_db
from memo.repository.user import (
    create_user_db,
    delete_user_db,
    get_user_db,
    list_users_db,
    update_user_db,
)


class UserError(Exception):
    """ユーザー操作のドメイン例外の基底。"""


class NameRequired(UserError):
    """``name`` が空 (trim 後) のときに送出する。"""


class UserAlreadyExists(UserError):
    """同名ユーザーが既に存在するときに送出する。"""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"user '{name}' already exists")


class UserNotFound(UserError):
    """対象ユーザーが存在しないときに送出する。"""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"user '{name}' not found")


class CannotDeleteAdmin(UserError):
    """特権ユーザー ``admin`` の削除を拒否するときに送出する。"""

    def __init__(self, name: str = ADMIN_USER):
        self.name = name
        super().__init__(f"cannot delete the admin user '{name}'")


def list_users() -> list[dict]:
    """登録済みユーザーを名前順に返す。"""
    return list_users_db()


def get_user(name: str) -> dict:
    """ユーザーを1件返す。存在しなければ ``UserNotFound``。"""
    user = get_user_db(name.strip())
    if user is None:
        raise UserNotFound(name)
    return user


def create_user(name: str, display_name: str = "", note: str = "") -> dict:
    """ユーザーを新規登録して作成レコードを返す。

    ``name`` 必須 (空なら ``NameRequired``)。``name`` / ``display_name`` /
    ``note`` は trim する。同名が既に存在すれば ``UserAlreadyExists``。
    """
    name = name.strip()
    if not name:
        raise NameRequired()
    created = create_user_db(name, display_name.strip(), note.strip())
    if created is None:
        raise UserAlreadyExists(name)
    # 新規ユーザーには既定カテゴリ OTHERS だけを付与する (要望: 新規は OTHERS のみ)
    ensure_default_category_db(name)
    return created


def update_user(
    name: str, display_name: str | None = None, note: str | None = None
) -> dict:
    """ユーザーの属性 (display_name / note) を部分更新して返す。

    ``name`` (識別子) は不変。``display_name`` / ``note`` は ``None`` のとき
    「変更しない」を表し、文字列のときは trim して更新する。対象が存在しなければ
    ``UserNotFound``。
    """
    updated = update_user_db(
        name.strip(),
        display_name.strip() if display_name is not None else None,
        note.strip() if note is not None else None,
    )
    if updated is None:
        raise UserNotFound(name)
    return updated


def delete_user(name: str) -> None:
    """ユーザーを台帳から削除する。

    特権ユーザー ``admin`` は削除禁止 (``CannotDeleteAdmin``)。対象が存在
    しなければ ``UserNotFound``。そのユーザーのメモ・カテゴリ・埋め込みも
    repository 側でカスケード削除される (孤立データを残さない)。
    """
    name = name.strip()
    if name == ADMIN_USER:
        raise CannotDeleteAdmin(name)
    if not delete_user_db(name):
        raise UserNotFound(name)
