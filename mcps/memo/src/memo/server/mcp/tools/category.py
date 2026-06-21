"""カテゴリ管理の MCP ツール定義 (作成 + 一覧の C/R のみ)。

カテゴリはユーザーごとの第一級の実体で、メモは自分の登録済みカテゴリにしか
紐づけられない。MCP からはカテゴリの **作成 (create_category)** と
**一覧 (list_categories)** だけを公開する。更新 (リネーム) と削除は Web 画面
からのみ行う方針なのでツールにはしない。

各ツールは ``authz.resolve_caller()`` で識別・登録チェックを通過した接続ユーザーを
所有者としてカテゴリを操作する。カテゴリはユーザー単位なので admin でも自分の
カテゴリだけを扱う (横断アクセスは持たない)。
"""

import json

from memo.server.mcp.app import mcp
from memo.server.mcp.authz import resolve_caller
from memo.service.category import (
    CategoryAlreadyExists,
    CategoryNameRequired,
    create_category as create_category_service,
    list_categories as list_categories_service,
)


def _dump(obj) -> str:
    """結果を読みやすい JSON 文字列にして返す (日本語をエスケープしない)。"""
    return json.dumps(obj, ensure_ascii=False, indent=2)


@mcp.tool(
    description=(
        "新しいカテゴリを作成する。作成者は接続中ユーザーで、そのユーザー専用の\n"
        "カテゴリになる。\n\n"
        "name : カテゴリ名 (必須)。大文字に正規化して保存される (work→WORK)。\n"
        "メモは登録済みカテゴリにしか紐づけられないため、新しいカテゴリで\n"
        "メモを作りたい場合は先にこのツールで作成する。\n"
        "成功時は短いメッセージを返す。既に同名が存在すればその旨を返す。"
    )
)
def create_category(name: str) -> str:
    """resolve_caller() の接続ユーザー所有でカテゴリを作成する。

    name 必須 (空なら CategoryNameRequired) と正規化は service / repository 側。
    """
    user, _is_admin, error = resolve_caller()
    if error:
        return error
    try:
        created = create_category_service(user, name)
    except CategoryNameRequired:
        return "Error: name is required."
    except CategoryAlreadyExists as e:
        return f"Category '{e.name}' already exists."
    return f"Created category '{created['name']}'."


@mcp.tool(
    description=(
        "自分のカテゴリ一覧を名前順に取得する。\n\n"
        "メモを作成・絞り込みする際に、利用できるカテゴリを確認するのに使う。\n"
        "カテゴリの配列を JSON で返す。"
    )
)
def list_categories() -> str:
    """接続ユーザーのカテゴリ一覧を返す (カテゴリはユーザー単位)。"""
    user, _is_admin, error = resolve_caller()
    if error:
        return error
    categories = list_categories_service(user)
    if not categories:
        return "No categories found."
    return _dump(categories)
