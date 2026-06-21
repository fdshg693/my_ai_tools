"""スキーマのバージョン管理付きマイグレーション (別フォルダに分離)。

``schema_version`` テーブルで適用済みバージョンを管理し、未適用のものだけを
順番に実行する (``runner.run_migrations``)。各マイグレーションは
``mNNN_*.py`` に1つずつ置き、``runner._MIGRATIONS`` に登録する
(dynamic_prompt の ``_MIGRATIONS`` 方式を踏襲)。

``infra.database.init_db()`` が起動時に ``run_migrations`` を呼ぶ。手動で
既存 DB を移行したいときは ``python -m memo.migrations`` (= ``memo-migrate``)
を使う (``__main__`` 参照)。
"""

from memo.migrations.runner import run_migrations

__all__ = ["run_migrations"]
