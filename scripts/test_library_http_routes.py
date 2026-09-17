"""Ticket 31 — stdlib HTTP routes for HOME / STYLE / CASE."""

from __future__ import annotations

from http.client import HTTPConnection
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.app import make_server
from library.index import configure_index_path, rebuild_index
from library.session import reset_session


def _request(host: str, port: int, path: str) -> tuple[int, str]:
    conn = HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        return resp.status, body
    finally:
        conn.close()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    reset_session()
    tmp = ROOT / "data" / "_tmp_index_t31.json"
    configure_index_path(tmp)
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    try:
        rebuild_index(
            [
                {
                    "id": "case_a",
                    "title": "Internal",
                    "url": "https://romanjeanelie.com/",
                    "created_at": "2026-09-17T00:00:00+00:00",
                    "screenshots": [],
                    "visual": {"style": "Dark cinematic"},
                    "interaction": {},
                    "frontend": {},
                    "replication": {},
                }
            ],
            {"case_a": "dark_cinematic"},
            path=tmp,
        )
        thread.start()
        host, port = server.server_address
        code, body = _request(host, port, "/")
        assert code == 200, (code, body[:200])
        code, _body = _request(host, port, "/style/dark_cinematic")
        assert code == 200
        code, _body = _request(host, port, "/style/missing-style")
        assert code in {303, 302}
        print("ok")
    finally:
        server.shutdown()
        configure_index_path(None)
        if tmp.exists():
            tmp.unlink()
        reset_session()


if __name__ == "__main__":
    main()
