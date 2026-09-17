"""Lightweight Library HTTP app (stdlib only)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from library.cards import get_research_card
from library.index import load_index
from library.pages import render_case_page, render_home, render_not_found, render_style_page
from library.session import get_session, request_cancel, start_research

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 8765


class LibraryHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code: int, text: str, extra: dict[str, str] | None = None) -> None:
        self._send(code, text.encode("utf-8"), "text/html; charset=utf-8", extra)

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, raw, "application/json; charset=utf-8")

    def _redirect(self, location: str, code: int = 303) -> None:
        self._send(code, b"", "text/plain", {"Location": location})

    def _read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        parsed = parse_qs(raw.decode("utf-8", errors="replace"))
        return {key: (vals[0] if vals else "") for key, vals in parsed.items()}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path or "/")
        qs = parse_qs(parsed.query)

        if path.startswith("/screenshots/"):
            self._serve_file(PROJECT_ROOT / path.lstrip("/"))
            return
        if path == "/api/status":
            self._json(200, get_session())
            return
        if path == "/":
            q = (qs.get("q") or [""])[0]
            style = (qs.get("style") or [""])[0]
            sort = (qs.get("sort") or ["recent"])[0]
            html = render_home(load_index(), q=q, style=style, sort=sort)
            self._html(200, html)
            return
        if path.startswith("/style/"):
            category_id = path[len("/style/") :].strip("/")
            sort = (qs.get("sort") or ["recent"])[0]
            page = render_style_page(category_id, load_index(), sort=sort)
            if page is None:
                self._redirect("/")
                return
            self._html(200, page)
            return
        if path.startswith("/case/"):
            case_id = path[len("/case/") :].strip("/")
            fetched = get_research_card(case_id)
            if not fetched.get("ok") or not isinstance(fetched.get("case"), dict):
                self._html(404, render_not_found("Case not found"))
                return
            self._html(200, render_case_page(fetched["case"], load_index()))
            return
        self._html(404, render_not_found())

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path or "/")
        if path == "/research":
            form = self._read_form()
            start_research(form.get("goal") or "")
            self._redirect("/")
            return
        if path == "/research/cancel":
            request_cancel()
            self._redirect("/")
            return
        self._html(404, render_not_found())

    def _serve_file(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            root = (PROJECT_ROOT / "screenshots").resolve()
            if root not in resolved.parents and resolved != root:
                self._html(404, render_not_found("Not found"))
                return
            if not resolved.is_file():
                self._html(404, render_not_found("Not found"))
                return
            data = resolved.read_bytes()
        except Exception:
            self._html(404, render_not_found("Not found"))
            return
        ctype = "image/png"
        suffix = resolved.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            ctype = "image/jpeg"
        elif suffix == ".webp":
            ctype = "image/webp"
        elif suffix == ".gif":
            ctype = "image/gif"
        self._send(200, data, ctype)


def make_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), LibraryHandler)


def _rebuild_index_if_empty() -> None:
    from library.classify import classify_and_rebuild_index
    from library.index import load_index

    if load_index().get("sites"):
        return
    print("Library Index empty; rebuilding from Research Cards (visual classify)...", flush=True)
    try:
        result = classify_and_rebuild_index()
        print(f"Index rebuilt: {result.get('count', 0)} cards", flush=True)
    except Exception as exc:
        print(f"Index rebuild skipped: {type(exc).__name__}: {exc}", flush=True)


def serve_forever(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    import threading

    server = make_server(host, port)
    print(f"Library app: http://{host}:{port}/", flush=True)
    threading.Thread(target=_rebuild_index_if_empty, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
