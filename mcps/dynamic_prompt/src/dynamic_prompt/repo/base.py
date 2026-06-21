"""リポジトリ層のインタフェース定義。

データアクセスを Protocol で抽象化し、後続の Firestore 移行リスクを下げる。
シグネチャは既存 SQLite 実装 (``sqlite_repo.py`) の戻り値形式に合わせてある。
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class VocabRepo(Protocol):
    """単語と復習プールへのアクセス。"""

    def init(self) -> None:
        """スキーマ作成・マイグレーション等の初期化。"""
        ...

    def save_words(self, lang: str, words: list[str], context: str = "") -> list[str]:
        """単語を保存し、保存された (正規化済み) 単語のリストを返す。"""
        ...

    def get_review_pool(
        self, lang: str, limit: int, memory_test_period_hours: int
    ) -> list[dict]:
        """復習対象の単語 (``word`` / ``context`` / ``status``) をランダムに返す。"""
        ...

    def process_answers(
        self, lang: str, correct: list[str], incorrect: list[str]
    ) -> list[str]:
        """正答・誤答にステータス遷移を適用し、結果メッセージのリストを返す。"""
        ...


@runtime_checkable
class QuizRepo(Protocol):
    """クイズセッション・問題・採点へのアクセス。"""

    def create_session(self, lang: str, title: str, questions: list[dict]) -> int:
        """クイズセッション (MC / free 混在可) を保存し、セッションIDを返す。"""
        ...

    def submit_answers(self, session_id: int, answers: list) -> dict:
        """回答を保存・採点し、結果 dict を返す。"""
        ...

    def get_pending(self) -> dict | None:
        """未回答の最新クイズを返す。なければ None。"""
        ...

    def get_recent_results(self, lang: str, limit: int = 5) -> list[dict]:
        """直近の完了済みクイズ結果を返す。"""
        ...

    def get_unscored(self, lang: str, limit: int = 5) -> list[dict]:
        """提出済みだが未採点の自由回答クイズを返す。"""
        ...

    def score_free_answers(self, session_id: int, scores: list[dict]) -> dict:
        """自由回答の採点結果を保存する。"""
        ...


@runtime_checkable
class TopicRepo(Protocol):
    """物語の話題へのアクセス。"""

    def save_topic(self, lang: str, topic: str, summary: str = "") -> int:
        """話題を保存し、IDを返す。"""
        ...

    def list_recent(self, lang: str, limit: int = 20) -> list[dict]:
        """直近の話題を新しい順に返す。"""
        ...


@dataclass
class RepoBundle:
    """バックエンド非依存のリポジトリ束。"""

    vocab: VocabRepo
    quiz: QuizRepo
    topic: TopicRepo
