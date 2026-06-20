"""MCP ツール登録 (side-effect import)。

ツールをドメインごとにサブモジュールへ分割している:

- ``memo`` : メモ管理ツール (CRUD + タイトル部分一致検索)
- ``user`` : ユーザー管理ツール (admin 専用)

ここで両方を読み込むことで、``import memo.tools`` だけで全ツールが
``mcp`` インスタンスに登録される。
"""

from memo.server.mcp.tools import memo, user  # noqa: F401 — ツール登録 (side-effect import)
