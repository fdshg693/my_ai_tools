"""OpenAI 埋め込み API のラッパ (セマンティック検索用)。

``openai`` を import し ``OPENAI_API_KEY`` を読むのはこのモジュールだけ。
service 層 (ランキング) から ``embed_text`` を呼び出す。テストは
``memo.service.embed_text`` を monkeypatch するため、このモジュールは
ネットワーク・API キー無しでも import できる (キーは呼び出し時に遅延取得)。

import 時に ``mcps/memo/.env`` を読み込むので、``OPENAI_API_KEY`` などは
そこに書いておける。既に設定済みの環境変数が優先される (.env は上書きしない)。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

#: パッケージルート (mcps/memo) の .env。簡単のためここ固定で読み込む。
#: __file__ = mcps/memo/src/memo/embedding.py → parents[2] = mcps/memo
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

#: 埋め込みモデル。多言語対応で日本語の概要にも使える。環境変数で上書き可。
MODEL = os.environ.get("MEMO_EMBEDDING_MODEL", "text-embedding-3-small")


class EmbeddingError(RuntimeError):
    """API キー未設定・API 呼び出し失敗を表す。tool 層が文言にして返す。"""


_client = None


def _get_client():
    """OpenAI クライアントを遅延生成する。キーが無ければ ``EmbeddingError``。"""
    global _client
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise EmbeddingError(
            "OPENAI_API_KEY is not set. "
            "環境変数に OpenAI API キーを設定してください。"
        )
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(api_key=key)
    return _client


def embed_text(text: str) -> list[float]:
    """テキストを埋め込みベクトルに変換する。失敗は ``EmbeddingError`` に包む。"""
    try:
        resp = _get_client().embeddings.create(model=MODEL, input=text)
    except EmbeddingError:
        raise
    except Exception as e:  # APIError / RateLimitError / ネットワーク等
        raise EmbeddingError(f"OpenAI embedding request failed: {e}") from e
    return resp.data[0].embedding
