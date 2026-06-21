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

from memo.repository.category import ensure_default_category_db
from memo.repository.user import (
    count_admins_db,
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


class CannotDeleteLastAdmin(UserError):
    """最後の1人の管理者 (``is_admin``) の削除を拒否するときに送出する。

    管理者が誰も居なくなる事態 (ロックアウト) を防ぐための不変条件。
    """

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"cannot delete the last admin user '{name}'")


class CannotDemoteLastAdmin(UserError):
    """最後の1人の管理者から ``is_admin`` を外す (降格) のを拒否するときに送出する。"""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"cannot remove admin from the last admin user '{name}'")


def list_users() -> list[dict]:
    """登録済みユーザーを名前順に返す。"""
    return list_users_db()


def get_user(name: str) -> dict:
    """ユーザーを1件返す。存在しなければ ``UserNotFound``。"""
    user = get_user_db(name.strip())
    if user is None:
        raise UserNotFound(name)
    return user


def create_user(
    name: str, display_name: str = "", note: str = "", is_admin: bool = False
) -> dict:
    """ユーザーを新規登録して作成レコードを返す。

    ``name`` 必須 (空なら ``NameRequired``)。``name`` / ``display_name`` /
    ``note`` は trim する。同名が既に存在すれば ``UserAlreadyExists``。
    ``is_admin`` で管理者権限を付けて作成できる (既定は非管理者)。
    """
    name = name.strip()
    if not name:
        raise NameRequired()
    created = create_user_db(name, display_name.strip(), note.strip(), is_admin)
    if created is None:
        raise UserAlreadyExists(name)
    # 新規ユーザーには既定カテゴリ OTHERS だけを付与する (要望: 新規は OTHERS のみ)。
    # カテゴリは不変の user_id に紐づくので作成済みレコードの id を使う。
    ensure_default_category_db(created["id"])
    return created


def update_user(
    name: str,
    display_name: str | None = None,
    note: str | None = None,
    is_admin: bool | None = None,
) -> dict:
    """ユーザーの属性 (display_name / note / is_admin) を部分更新して返す。

    ``name`` (ログインハンドル) は不変。各フィールドは ``None`` のとき
    「変更しない」を表す。文字列フィールドは trim して更新する。``is_admin`` は
    bool で管理者権限を付与/剥奪するが、**最後の1人の管理者は降格できない**
    (``CannotDemoteLastAdmin``)。対象が存在しなければ ``UserNotFound``。
    """
    name = name.strip()
    if is_admin is False:
        current = get_user_db(name)
        if current and current["is_admin"] and count_admins_db() <= 1:
            raise CannotDemoteLastAdmin(name)
    updated = update_user_db(
        name,
        display_name.strip() if display_name is not None else None,
        note.strip() if note is not None else None,
        is_admin,
    )
    if updated is None:
        raise UserNotFound(name)
    return updated


def delete_user(name: str) -> None:
    """ユーザーを台帳から削除する。

    **最後の1人の管理者は削除禁止** (``CannotDeleteLastAdmin``) — 管理者が
    誰も居なくなるロックアウトを防ぐ。対象が存在しなければ ``UserNotFound``。
    そのユーザーのメモ・カテゴリ・埋め込みは DB の外部キー (ON DELETE CASCADE)
    が自動で削除する (孤立データを残さない)。
    """
    name = name.strip()
    target = get_user_db(name)
    if target is None:
        raise UserNotFound(name)
    if target["is_admin"] and count_admins_db() <= 1:
        raise CannotDeleteLastAdmin(name)
    delete_user_db(name)
