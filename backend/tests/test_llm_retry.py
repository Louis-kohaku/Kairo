"""Does Kairo survive LM Studio swapping a model mid-production?

This exists because a real Full Auto run failed on it. LM Studio returned
`400 {"error":"Model reloaded."}` while the pipeline was writing the script,
`chat_completion` raised immediately, and a twenty-minute production died on
a condition that resolves itself on the next request.

The test stands up a throwaway HTTP server that impersonates LM Studio's
`/v1/models` and `/v1/chat/completions`, scripted to fail in the specific
ways the real server does, and asserts on what `llm_client` does about it.

Run with:
    backend/.venv/Scripts/python.exe backend/tests/test_llm_retry.py
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

MODEL = "test-model"

# Each entry is one scripted reply for the next /chat/completions call:
# (status, body). Consumed in order.
_script: list[tuple[int, str]] = []
_calls: list[dict] = []


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silence the default stderr spam
        pass

    def _send(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path.endswith("/models"):
            self._send(200, json.dumps({"data": [{"id": MODEL}]}))
        else:
            self._send(404, "{}")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            _calls.append(json.loads(raw))
        except ValueError:
            _calls.append({})
        if _script:
            status, body = _script.pop(0)
        else:
            status, body = 200, json.dumps(
                {"choices": [{"message": {"content": "ok"}}]}
            )
        self._send(status, body)


failures: list[str] = []
passed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failures.append(f"{name} - {detail}")
        print(f"[FAIL] {name} - {detail}")


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Point the client at the fake server before importing it, and shorten
    # the backoff so the suite runs in seconds rather than minutes.
    import app.core.config as config

    config.LLM_BASE_URL = f"http://127.0.0.1:{port}/v1"
    import app.services.llm_client as llm

    llm.LLM_BASE_URL = config.LLM_BASE_URL
    llm.LLM_MODEL_ENV = MODEL
    llm._RETRY_BACKOFF_SECONDS = 0.05

    def reset(script: list[tuple[int, str]]) -> None:
        _script.clear()
        _script.extend(script)
        _calls.clear()
        llm.get_status.cache_clear() if hasattr(llm.get_status, "cache_clear") else None

    ok_body = json.dumps({"choices": [{"message": {"content": "generated"}}]})
    reload_body = json.dumps({"error": "Model reloaded."})

    # --- the failure that killed a real run ------------------------------
    reset([(400, reload_body), (200, ok_body)])
    try:
        result = llm.chat_completion([{"role": "user", "content": "hi"}])
        check(
            "モデル再読み込み(400)の直後に自動で再試行して成功する",
            result == "generated" and len(_calls) == 2,
            f"result={result!r} calls={len(_calls)}",
        )
    except Exception as exc:  # noqa: BLE001
        check("モデル再読み込み(400)の直後に自動で再試行して成功する", False, repr(exc))

    # --- a transient 503 -------------------------------------------------
    reset([(503, "{}"), (200, ok_body)])
    try:
        result = llm.chat_completion([{"role": "user", "content": "hi"}])
        check("503の直後に再試行して成功する", result == "generated" and len(_calls) == 2,
              f"calls={len(_calls)}")
    except Exception as exc:  # noqa: BLE001
        check("503の直後に再試行して成功する", False, repr(exc))

    # --- retry is bounded ------------------------------------------------
    reset([(400, reload_body), (400, reload_body), (200, ok_body)])
    try:
        llm.chat_completion([{"role": "user", "content": "hi"}])
        check("再試行は1回まで（無限に繰り返さない）", False, "2回目も失敗したのに例外が出なかった")
    except llm.LLMResponseError as exc:
        check(
            "再試行は1回まで（無限に繰り返さない）",
            len(_calls) == 2, f"calls={len(_calls)}",
        )
        check(
            "再読み込みが続く場合はその旨をユーザーに伝える",
            "再読み込み" in str(exc), str(exc)[:120],
        )
    except Exception as exc:  # noqa: BLE001
        check("再試行は1回まで（無限に繰り返さない）", False, repr(exc))

    # --- a real client error must NOT be retried -------------------------
    reset([(400, json.dumps({"error": "invalid 'messages': empty"})), (200, ok_body)])
    try:
        llm.chat_completion([{"role": "user", "content": "hi"}])
        check("本物の400は再試行しない", False, "例外が出なかった")
    except llm.LLMResponseError:
        check("本物の400は再試行しない（リクエスト1回で失敗する）",
              len(_calls) == 1, f"calls={len(_calls)}")
    except Exception as exc:  # noqa: BLE001
        check("本物の400は再試行しない", False, repr(exc))

    # --- a crashed model: reported, not retried --------------------------
    # Observed in a real run. Retrying would only make the user wait twice
    # for the same failure, because a dead model does not answer either.
    crash_body = json.dumps(
        {"error": "The model has crashed without additional information. (Exit code: 1844)"}
    )
    reset([(400, crash_body), (200, ok_body)])
    try:
        llm.chat_completion([{"role": "user", "content": "hi"}])
        check("モデルクラッシュは再試行しない", False, "例外が出なかった")
    except llm.LLMModelCrashedError as exc:
        check("モデルクラッシュは再試行しない（1回で失敗する）",
              len(_calls) == 1, f"calls={len(_calls)}")
        check("クラッシュ時はメモリ不足の可能性と対処を伝える",
              "メモリ不足" in str(exc) and "読み込み直す" in str(exc), str(exc)[:140])
        check("クラッシュ例外はLLMResponseErrorとして捕捉できる（既存の握りが壊れない）",
              isinstance(exc, llm.LLMResponseError))
    except Exception as exc:  # noqa: BLE001
        check("モデルクラッシュは再試行しない", False, repr(exc))

    # --- 404 is not transient either -------------------------------------
    reset([(404, "{}"), (200, ok_body)])
    try:
        llm.chat_completion([{"role": "user", "content": "hi"}])
        check("404は再試行しない", False, "例外が出なかった")
    except llm.LLMResponseError:
        check("404は再試行しない", len(_calls) == 1, f"calls={len(_calls)}")
    except Exception as exc:  # noqa: BLE001
        check("404は再試行しない", False, repr(exc))

    server.shutdown()
    print("\n" + "=" * 60)
    print(f"{passed}/{passed + len(failures)} passed")
    for failure in failures:
        print(f"  FAILED: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
