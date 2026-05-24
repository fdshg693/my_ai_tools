"""接続中ユーザーの識別。

ユーザーはトランスポートごとに異なる方法で渡される:

- **stdio**: サーバー起動時のコマンドライン引数 (`memo --user alice`)。
  stdio はクライアントごとにプロセスが起動するため、プロセス全体で
  ユーザーは1人に固定される。起動時に `set_stdio_user()` で記録する。
  `switch_user` ツールで実行時に書き換えられる (再起動不要)。
- **HTTP**: MCP エンドポイントのクエリパラメータ。**安定した接続識別子**
  `?client_id=` と **初期ユーザー** `?user=` を分離して渡す。`client_id` が
  あれば in-memory マップ ``_http_user_by_client`` で「現在ユーザー」を引く。
  これにより、接続を張り替えずに `switch_user` でユーザーを切り替えられる。
  `client_id` が無い場合は従来どおり `?user=` をそのまま使う (後方互換)。

`Mcp-Session-Id` は再接続のたびに変わるためユーザー状態の鍵には使わない
(変化の可視化は logging_middleware が担う)。

ユーザーを識別できない場合は None を返す。ツール側はこれをエラーとして
拒否し、未識別のまま操作させない。
"""

from fastmcp.server.dependencies import get_http_request

# トランスポート種別は起動時に TRANSPORT で確定する不変量。main() が set_http_transport()
# で一度だけ確定させ、以後はこのフラグを参照する (毎回 get_http_request() の例外で検出しない)。
# 既定 False = stdio。インプロセステスト (main を通らない) もこの既定で stdio 扱いになる。
_is_http_transport: bool = False

_stdio_user: str | None = None

# HTTP 用: 安定 client_id → 現在ユーザー名。in-memory (サーバー再起動で初期 ?user= に戻る)。
# 個人ローカル運用前提のため TTL/eviction は省略する (長時間運用で client_id が増え続ける
# 懸念があれば将来 LRU/TTL を検討)。GIL 下の単一キー代入・参照は原子的なのでロック不要。
_http_user_by_client: dict[str, str] = {}


def set_http_transport(is_http: bool) -> None:
    """起動時にトランスポート種別 (HTTP か stdio か) を確定させる。"""
    global _is_http_transport
    _is_http_transport = is_http


def transport_is_http() -> bool:
    """HTTP トランスポートで起動しているかを返す (起動時に確定した値)。"""
    return _is_http_transport


def set_stdio_user(user: str | None) -> None:
    """stdio のユーザー名を記録する (起動時および switch_user による実行時書き換え)。"""
    global _stdio_user
    _stdio_user = (user or "").strip() or None


def http_client_id() -> str | None:
    """HTTP の安定接続識別子 ``?client_id=`` を返す (無ければ None)。

    HTTP モードでのみ呼ぶこと (リクエストコンテキスト内であることが前提)。
    logging_middleware が観測する client_id と同一ソース。
    """
    return (get_http_request().query_params.get("client_id") or "").strip() or None


def switch_http_user(client_id: str, target: str) -> None:
    """HTTP: ``client_id`` の現在ユーザーを ``target`` に上書きする。"""
    _http_user_by_client[client_id] = target


def current_user() -> str | None:
    """接続中ユーザー名を返す。識別できなければ None。

    - stdio: 起動時に記録したユーザー名。
    - HTTP かつ ``client_id`` なし: 従来どおり ``?user=`` をそのまま返す (後方互換)。
    - HTTP かつ ``client_id`` あり + ``?user=`` あり: 初回は ``?user=`` を初期値として
      ``setdefault`` で登録し、その値を返す。``switch_user`` 済みなら既存値を保持。
    - HTTP かつ ``client_id`` あり + ``?user=`` なし: マップのみ参照 (未登録なら None)。
    """
    if not _is_http_transport:
        return _stdio_user

    # HTTP モードのツール/ミドルウェア呼び出しは必ずリクエストコンテキスト内。
    # 万一外で呼ばれれば get_http_request() が例外を投げるが、それは握り潰さず
    # 表に出す (黙って stdio 扱いにすると誤ったユーザー解決を隠してしまうため)。
    request = get_http_request()
    query_user = (request.query_params.get("user") or "").strip() or None
    client_id = (request.query_params.get("client_id") or "").strip() or None
    if client_id is None:
        return query_user  # 後方互換: client_id 無し → 従来の ?user=
    if query_user is not None:
        # 初回のみ初期登録 (冪等)。ミドルウェアが先に呼んでも switch_user 後の値を壊さない。
        return _http_user_by_client.setdefault(client_id, query_user)
    return _http_user_by_client.get(client_id)
