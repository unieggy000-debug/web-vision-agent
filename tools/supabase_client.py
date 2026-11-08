"""Minimal Supabase client for Research Memory."""

from __future__ import annotations

import os
from pathlib import Path

from supabase import Client, create_client

ENV_PATH = Path(os.environ.get("VISION_AGENT_ENV_FILE") or (Path(__file__).resolve().parent.parent / ".env"))
PLACEHOLDER_KEYS = {"", "your_api_key_here", "..."}

_client: Client | None = None


def _read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("'\"")
    return values


def get_supabase() -> Client:
    """
    Return a shared Supabase client.
    Raises RuntimeError with a safe message if URL/key are missing.
    """
    global _client
    if _client is not None:
        return _client

    env = _read_env()
    url = env.get("SUPABASE_URL") or ""
    key = env.get("SUPABASE_KEY") or ""
    if url in PLACEHOLDER_KEYS or key in PLACEHOLDER_KEYS:
        raise RuntimeError(
            "Missing SUPABASE_URL or SUPABASE_KEY in .env. "
            "Add both values then retry."
        )

    _client = create_client(url, key)
    return _client


def reset_supabase_client() -> None:
    """Clear cached client (used by tests)."""
    global _client
    _client = None
