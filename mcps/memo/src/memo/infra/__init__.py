"""インフラ層 (infra)。

ドメインに依存しない低レベルな基盤を集約する:

- ``database`` : SQLite 接続ファクトリ・スキーマ初期化・共通定数
- ``embedding`` : OpenAI 埋め込み API のラッパ (唯一の OpenAI/.env 読み込み点)
"""
