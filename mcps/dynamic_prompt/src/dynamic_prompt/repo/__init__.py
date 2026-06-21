"""リポジトリ層のエントリポイント。

``init_repo()`` でバックエンドを選択して初期化し、``get_repo()`` でシングルトンの
``RepoBundle`` を取得する。呼び出し側 (tools / quiz_server / main) はこの2関数だけを
使い、具体的なバックエンド実装には依存しない。
"""

import os

from dynamic_prompt.repo.base import QuizRepo, RepoBundle, TopicRepo, VocabRepo

__all__ = [
    "QuizRepo",
    "RepoBundle",
    "TopicRepo",
    "VocabRepo",
    "init_repo",
    "get_repo",
]

_repo: RepoBundle | None = None


def init_repo(backend: str | None = None) -> RepoBundle:
    """バックエンドを初期化してシングルトンに設定する。

    ``backend`` 未指定時は環境変数 ``DATA_BACKEND`` (既定 ``"sqlite"``) を参照する。
    """
    global _repo
    if backend is None:
        backend = os.environ.get("DATA_BACKEND", "sqlite")

    if backend == "sqlite":
        from dynamic_prompt.repo.sqlite_repo import build_sqlite_repo

        _repo = build_sqlite_repo()
    else:
        raise ValueError(f"unknown backend: {backend}")

    _repo.vocab.init()  # マイグレーション等
    return _repo


def get_repo() -> RepoBundle:
    """初期化済みの ``RepoBundle`` を返す。未初期化なら自動で SQLite を初期化する。"""
    if _repo is None:
        return init_repo()
    return _repo
