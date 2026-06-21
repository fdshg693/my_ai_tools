"""admin タグの付いたツール (ユーザー管理ツール) の可視性ポリシー。

FastMCP の公式「Component Visibility」機能をそのまま使う
(https://gofastmcp.com/servers/visibility)。ミドルウェアで一覧を書き換えるのではなく、
FastMCP が用意した2段構えの可視性 API を使う:

- **サーバーレベル** (`mcp.disable(tags=...)`): 起動時に admin タグのツールを既定で
  無効化する。新しいセッションは必ずこの既定 (= 非公開) から始まる。``app.py`` が
  ツール登録後に ``apply_server_default(mcp)`` を呼ぶ。
- **セッションレベル** (`ctx.enable_components(...)` / `ctx.disable_components(...)`):
  ``switch_user`` で現在ユーザーが admin に切り替わった **その接続だけ** で admin タグの
  ツールを有効化する。admin から離れたら無効化する。FastMCP がこの変更に対して
  ``notifications/tools/list_changed`` をクライアントへ自動送信するので、クライアントは
  ツール一覧を再取得して有効/無効を正しく反映できる (ミドルウェア方式の最大の問題点だった
  「有効化したのに通知が飛ばない」を公式 API が解決する)。

``switch_user`` 自体は admin 専用ではない (誰でも admin に切り替えられる) ので、
「admin に切り替えただけで破壊的なユーザー管理ツールが生える」自動有効化は危険になりうる。
環境変数 ``MEMO_ADMIN_TOOLS_AUTO_ENABLE`` を falsy (``0``/``false``/``no``/``off``) にすると、
このセッション有効化を一切行わない (admin に切り替えても管理ツールはサーバーレベルの
既定どおり無効のまま)。値は環境変数を優先し、無ければ ``mcps/memo/.env`` にフォールバックする。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from memo.infra.database import ADMIN_USER

#: パッケージルート (mcps/memo) の .env。embedding.py と同じ方針でここ固定で読み込む。
#: __file__ = mcps/memo/src/memo/server/mcp/admin_tools.py → parents[4] = mcps/memo
_ENV_PATH = Path(__file__).resolve().parents[4] / ".env"
load_dotenv(_ENV_PATH)  # 既に設定済みの環境変数が優先される (.env は上書きしない)

#: admin 専用ツール (ユーザー管理ツール) に付与するタグ。可視性 API はこのタグで束ねる。
ADMIN_TOOL_TAG = "admin"

#: ``MEMO_ADMIN_TOOLS_AUTO_ENABLE`` を無効と解釈する値 (大文字小文字は無視)。
_FALSY = {"0", "false", "no", "off"}


def admin_tools_auto_enable() -> bool:
    """admin 切替時に管理ツールをセッションで自動有効化してよいか (env 優先・.env フォールバック)。

    既定は有効 (未設定・空文字も有効扱い)。``MEMO_ADMIN_TOOLS_AUTO_ENABLE`` を
    ``0``/``false``/``no``/``off`` にすると無効化され、admin に切り替えても管理ツールは
    サーバーレベルの既定どおり無効のままになる。
    """
    raw = os.environ.get("MEMO_ADMIN_TOOLS_AUTO_ENABLE")
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() not in _FALSY


def apply_server_default(mcp) -> None:
    """サーバー起動時に admin タグのツールを無効化する (サーバーレベルの既定)。

    ツール登録後に呼ぶこと。これにより、どの新規セッションも admin タグのツールが
    非公開の状態から始まる。``switch_user`` で admin に切り替わったセッションだけが
    ``ctx.enable_components`` でこの既定を上書きする。
    """
    mcp.disable(tags={ADMIN_TOOL_TAG})


async def apply_session_visibility(ctx, current_user: str) -> None:
    """``switch_user`` 後に、この接続だけ admin タグのツールの可視性を切り替える。

    現在ユーザーが admin かつ自動有効化が有効なら有効化、そうでなければ無効化する
    (admin から離れたら隠す)。``ctx.enable_components`` / ``disable_components`` は
    ``list_changed`` 通知をクライアントへ自動送信する。
    """
    if current_user == ADMIN_USER and admin_tools_auto_enable():
        await ctx.enable_components(tags={ADMIN_TOOL_TAG})
    else:
        await ctx.disable_components(tags={ADMIN_TOOL_TAG})
