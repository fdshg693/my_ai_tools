"""クイズ用Webサーバー。デーモンスレッドで起動し、SSEでクイズをブラウザにプッシュする。"""

import asyncio
import atexit
import json
import logging
import os
import platform
import socket
import subprocess
import threading
import time
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from dynamic_prompt.database import get_pending_quiz, save_words_db, submit_quiz_answers

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"

# --- Module-level state ---
_quiz_queue: asyncio.Queue | None = None
_server_loop: asyncio.AbstractEventLoop | None = None
_server: uvicorn.Server | None = None
_server_thread: threading.Thread | None = None
_active_port: int | None = None
_atexit_registered = False


# ---------------------------------------------------------------------------
# SSE (Server-Sent Events)
# ---------------------------------------------------------------------------


async def _event_generator(request: Request):
    """SSEイベントジェネレーター。クイズデータをブラウザにプッシュする。"""
    from sse_starlette.sse import ServerSentEvent  # noqa: F401

    while True:
        if await request.is_disconnected():
            break
        try:
            data = await asyncio.wait_for(_quiz_queue.get(), timeout=30.0)
            yield {
                "event": "quiz",
                "data": json.dumps(data, ensure_ascii=False),
            }
        except asyncio.TimeoutError:
            # Keep-alive ping
            yield {"event": "ping", "data": ""}


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def homepage(_request: Request) -> HTMLResponse:
    html_path = _STATIC_DIR / "quiz.html"
    content = html_path.read_text(encoding="utf-8")
    return HTMLResponse(content)


async def sse_endpoint(request: Request):
    from sse_starlette.sse import EventSourceResponse

    return EventSourceResponse(_event_generator(request))


async def pending_quiz(_request: Request) -> JSONResponse:
    data = get_pending_quiz()
    return JSONResponse(data if data else {})


async def submit_answers(request: Request) -> JSONResponse:
    body = await request.json()
    session_id = body["session_id"]
    answers = body["answers"]
    result = submit_quiz_answers(session_id, answers)
    return JSONResponse(result)


async def save_words(request: Request) -> JSONResponse:
    body = await request.json()
    lang = body.get("lang", "").strip()
    words_raw = body.get("words", "").strip()
    context = body.get("context", "").strip()

    if not lang:
        return JSONResponse({"error": "lang is required"}, status_code=400)
    if not words_raw:
        return JSONResponse({"error": "words is required"}, status_code=400)

    word_list = [w.strip() for w in words_raw.split(",") if w.strip()]
    if not word_list:
        return JSONResponse({"error": "No valid words provided"}, status_code=400)

    saved = save_words_db(lang, word_list, context)
    return JSONResponse({"saved": saved, "count": len(saved)})


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

_app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/events", sse_endpoint),
        Route("/api/pending", pending_quiz),
        Route("/api/submit", submit_answers, methods=["POST"]),
        Route("/api/save_words", save_words, methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"),
    ],
)


# ---------------------------------------------------------------------------
# Port utilities
# ---------------------------------------------------------------------------


def _is_port_listening(port: int) -> bool:
    """ポートでプロセスがアクティブにリッスンしているかチェックする。

    socket.connect で判定するため、TIME_WAIT 状態の残骸には反応しない。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _try_bind_port(port: int) -> bool:
    """ポートにバインドできるかチェックする (TIME_WAIT 状態でも再利用を試みる)。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _kill_process_on_port(port: int) -> bool:
    """指定ポートを占有しているプロセスを強制終了する。成功時True。"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            killed = False
            for line in result.stdout.splitlines():
                if f"127.0.0.1:{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    if pid == os.getpid():
                        continue  # 自分自身は殺さない
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True,
                        timeout=5,
                    )
                    logger.info("Killed process %d on port %d", pid, port)
                    killed = True
            return killed
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout.strip():
                import signal as _signal

                for pid_str in result.stdout.strip().splitlines():
                    pid = int(pid_str)
                    if pid == os.getpid():
                        continue
                    os.kill(pid, _signal.SIGTERM)
                    logger.info("Killed process %d on port %d", pid, port)
                return True
    except Exception:
        logger.warning("Failed to kill process on port %d", port, exc_info=True)
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_active_port() -> int | None:
    """現在のクイズサーバーが使用しているポートを返す。"""
    return _active_port


def stop_quiz_server() -> None:
    """起動中のクイズサーバーをグレースフルに停止する。"""
    global _server, _server_thread, _server_loop, _quiz_queue, _active_port

    if _server is not None:
        _server.should_exit = True
        if _server_thread is not None and _server_thread.is_alive():
            _server_thread.join(timeout=5)
        logger.info("Quiz server stopped (port %s)", _active_port)
        _server = None
        _server_thread = None
        _server_loop = None
        _quiz_queue = None
        _active_port = None


def push_quiz(quiz_data: dict) -> None:
    """MCPツール(同期スレッド)からSSEキューにクイズデータをプッシュする。"""
    if _server_loop is None or _quiz_queue is None:
        raise RuntimeError("Quiz server not started")
    asyncio.run_coroutine_threadsafe(_quiz_queue.put(quiz_data), _server_loop)


def start_quiz_server(port: int = 8765, pool_size: int = 3) -> int:
    """デーモンスレッドでWebサーバーを起動する。

    ポートプールから利用可能なポートを探す。占有されている場合は古いプロセスを
    停止してからリトライする。

    Args:
        port: ベースポート番号。
        pool_size: 試行するポート数 (port〜port+pool_size-1)。

    Returns:
        実際に使用されたポート番号。

    Raises:
        RuntimeError: すべてのポートが利用不可の場合。
    """
    global _quiz_queue, _server_loop, _server, _server_thread, _active_port
    global _atexit_registered

    # 既存サーバーがあれば停止
    stop_quiz_server()

    # ポートプールから利用可能なポートを探す
    selected_port = None
    for i in range(pool_size):
        candidate = port + i

        # 1) 何もリッスンしておらず、バインドもできる → すぐ使える
        if not _is_port_listening(candidate) and _try_bind_port(candidate):
            selected_port = candidate
            break

        # 2) アクティブにリッスンしている → 古いプロセスをkill
        if _is_port_listening(candidate):
            logger.info(
                "Port %d has an active listener, killing old process...", candidate
            )
            _kill_process_on_port(candidate)
            # kill 後にポートが解放されるまで最大2秒リトライ
            for _ in range(4):
                time.sleep(0.5)
                if not _is_port_listening(candidate) and _try_bind_port(candidate):
                    selected_port = candidate
                    break
            if selected_port is not None:
                break

        # 3) リッスンはしていないがバインドできない (TIME_WAIT 等)
        #    → SO_REUSEADDR 付きソケットを uvicorn に渡すので使用可能とする
        if not _is_port_listening(candidate):
            selected_port = candidate
            logger.info(
                "Port %d appears to be in TIME_WAIT, will bind with SO_REUSEADDR",
                candidate,
            )
            break

        logger.warning("Port %d still unavailable, trying next...", candidate)

    if selected_port is None:
        raise RuntimeError(
            f"All ports in pool {port}\u2013{port + pool_size - 1} are unavailable"
        )

    ready_event = threading.Event()
    final_port = selected_port  # closure 用

    def _run() -> None:
        global _quiz_queue, _server_loop, _server
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _server_loop = loop
        _quiz_queue = asyncio.Queue()

        # SO_REUSEADDR 付きソケットを事前に作成して uvicorn に渡す。
        # これにより TIME_WAIT 状態のポートでも即座に再バインドできる。
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", final_port))
        sock.listen(100)
        sock.setblocking(False)

        config = uvicorn.Config(
            _app,
            host="127.0.0.1",
            port=final_port,
            log_level="warning",
        )
        _server = uvicorn.Server(config)

        ready_event.set()
        try:
            loop.run_until_complete(_server.serve(sockets=[sock]))
        finally:
            # 残タスクをキャンセルして "Task was destroyed" 警告を防ぐ
            _cleanup_loop(loop)

    _server_thread = threading.Thread(target=_run, daemon=True, name="quiz-server")
    _server_thread.start()
    ready_event.wait(timeout=5)
    _active_port = final_port

    # atexit は1回だけ登録
    if not _atexit_registered:
        atexit.register(stop_quiz_server)
        _atexit_registered = True

    logger.info("Quiz server starting on http://127.0.0.1:%d", final_port)
    return final_port


def _cleanup_loop(loop: asyncio.AbstractEventLoop) -> None:
    """イベントループの残タスクをキャンセルし、クリーンに閉じる。"""
    try:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        loop.run_until_complete(loop.shutdown_asyncgens())
    except Exception:
        pass  # シャットダウン中のエラーは無視
    finally:
        loop.close()
