"""カテゴリ CRUD のドメインルール (MCP ツールと Web UI が共有する)。

``repository.category`` を包み、カテゴリ操作のドメイン不変条件を一箇所に集約する
(``service.user`` の構成を踏襲):

- ``name`` 必須・trim・正規化 (大文字化、空 → ``OTHERS``)。
- 既定カテゴリ ``OTHERS`` はリネーム・削除できない。
- リネーム先が既存の別カテゴリと衝突したら拒否。
- 削除すると紐づくメモは ``OTHERS`` へ付け替えられる (repository が実施)。

戻り値は **構造化データ (dict) または例外** で表現し、文字列メッセージは返さない
(呼び出し側がメッセージや HTTP ステータスへ各自変換できるように)。

**認可はここに入れない。** カテゴリはユーザー単位 (admin も自分のカテゴリのみ)。
依存方向: ``tools`` / ``web`` → ``service`` → ``repository`` 。
"""

from memo.infra.database import OTHERS_CATEGORY
from memo.repository.category import (
    create_category_db,
    delete_category_db,
    get_category_db,
    list_categories_db,
    normalize_category,
    rename_category_db,
)


class CategoryError(Exception):
    """カテゴリ操作のドメイン例外の基底。"""


class CategoryNameRequired(CategoryError):
    """``name`` が空 (trim 後) のときに送出する。"""


class CategoryAlreadyExists(CategoryError):
    """同名カテゴリ (正規化後) が既に存在するときに送出する。"""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"category '{name}' already exists")


class CategoryNotFound(CategoryError):
    """対象カテゴリが存在しないときに送出する。"""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"category '{name}' not found")


class CannotModifyOthers(CategoryError):
    """既定カテゴリ ``OTHERS`` のリネーム/削除を拒否するときに送出する。"""

    def __init__(self):
        super().__init__(f"cannot modify the default category '{OTHERS_CATEGORY}'")


def list_categories(user_id: int) -> list[dict]:
    """ユーザーのカテゴリ一覧を名前順に返す (常にそのユーザーのものだけ)。"""
    return list_categories_db(user_id)


def create_category(user_id: int, name: str) -> dict:
    """カテゴリを新規作成して作成レコードを返す。

    ``name`` 必須 (空なら ``CategoryNameRequired``)、trim + 正規化 (大文字化)。
    同名 (正規化後) が既にあれば ``CategoryAlreadyExists``。
    """
    if not name or not name.strip():
        raise CategoryNameRequired()
    created = create_category_db(user_id, name)
    if created is None:
        raise CategoryAlreadyExists(normalize_category(name))
    return created


def rename_category(user_id: int, old_name: str, new_name: str) -> dict:
    """カテゴリ名を変更し、紐づくメモのカテゴリも追従させる (repository が実施)。

    既定カテゴリ ``OTHERS`` は変更不可 (``CannotModifyOthers``)。``old_name`` が
    存在しなければ ``CategoryNotFound``。``new_name`` が空なら
    ``CategoryNameRequired``、既存の別カテゴリと衝突すれば ``CategoryAlreadyExists``。
    """
    old = normalize_category(old_name)
    if old == OTHERS_CATEGORY:
        raise CannotModifyOthers()
    if not new_name or not new_name.strip():
        raise CategoryNameRequired()
    new = normalize_category(new_name)

    existing = {c["name"] for c in list_categories_db(user_id)}
    if old not in existing:
        raise CategoryNotFound(old)
    # 同名へのリネーム (実質変更なし) は許可。別カテゴリと衝突する場合のみ拒否。
    if new != old and new in existing:
        raise CategoryAlreadyExists(new)

    rename_category_db(user_id, old, new)
    return {"user_id": user_id, "name": new}


def delete_category(user_id: int, name: str) -> None:
    """カテゴリを削除する (紐づくメモは ``OTHERS`` へ付け替え)。

    既定カテゴリ ``OTHERS`` は削除不可 (``CannotModifyOthers``)。対象が存在
    しなければ ``CategoryNotFound``。
    """
    target = normalize_category(name)
    if target == OTHERS_CATEGORY:
        raise CannotModifyOthers()
    existing = {c["name"] for c in list_categories_db(user_id)}
    if target not in existing:
        raise CategoryNotFound(target)
    delete_category_db(user_id, target)


def rename_category_by_id(user_id: int, category_id: int, new_name: str) -> dict:
    """id 指定でカテゴリをリネームする (Web の id ベース呼び出し用)。

    対象 id が存在しなければ ``CategoryNotFound``。それ以外の不変条件は
    ``rename_category`` に委譲する。
    """
    current = get_category_db(user_id, category_id)
    if current is None:
        raise CategoryNotFound(str(category_id))
    return rename_category(user_id, current["name"], new_name)


def delete_category_by_id(user_id: int, category_id: int) -> None:
    """id 指定でカテゴリを削除する (Web の id ベース呼び出し用)。

    対象 id が存在しなければ ``CategoryNotFound``。それ以外の不変条件は
    ``delete_category`` に委譲する。
    """
    current = get_category_db(user_id, category_id)
    if current is None:
        raise CategoryNotFound(str(category_id))
    delete_category(user_id, current["name"])
