"""埋め込みベクトルキャッシュ (``memo_embeddings`` テーブル) のデータアクセス。

セマンティック検索が概要 (summary) の埋め込みを遅延計算し、再利用するための
純粋なデータアクセス層。vector は JSON 配列として保存する。``summary_hash`` と
``model`` が一致する間はキャッシュを使い回し、変わったら service 層が再計算して
``upsert_embedding`` で更新する。ここでは OpenAI 呼び出しや認可は扱わない。
"""

import json

from memo.infra.database import _connect_db


def get_cached_embedding(memo_id: int) -> dict | None:
    """memo_id のキャッシュを取得する。無ければ None。

    戻り値は ``{"summary_hash", "model", "vector"}`` (vector は float のリスト)。
    """
    with _connect_db() as db:
        row = db.execute(
            "SELECT summary_hash, model, vector FROM memo_embeddings WHERE memo_id = ?",
            (memo_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "summary_hash": row["summary_hash"],
        "model": row["model"],
        "vector": json.loads(row["vector"]),
    }


def upsert_embedding(
    memo_id: int, summary_hash: str, model: str, vector: list[float]
) -> None:
    """埋め込みを保存する。同じ memo_id があれば上書きする (1メモ1行)。"""
    with _connect_db() as db:
        db.execute(
            "INSERT INTO memo_embeddings (memo_id, summary_hash, model, vector) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(memo_id) DO UPDATE SET "
            "summary_hash = excluded.summary_hash, model = excluded.model, "
            "vector = excluded.vector, created_at = datetime('now')",
            (memo_id, summary_hash, model, json.dumps(vector)),
        )


def delete_embedding(memo_id: int) -> None:
    """memo_id のキャッシュを削除する (任意。孤児行を掃除したい場合に使う)。"""
    with _connect_db() as db:
        db.execute("DELETE FROM memo_embeddings WHERE memo_id = ?", (memo_id,))
