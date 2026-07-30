from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _matches_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Accept the documented authorized-feed response envelopes.

    The rows deliberately use the same canonical keys as the existing
    Sporttery page extractor. This keeps persistence and audit behavior
    identical across public-page and licensed/API sources.
    """
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        data = payload.get("data") or payload.get("value") or payload
        rows = data.get("matches") if isinstance(data, dict) else None
    else:
        rows = None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError(
            "Authorized official feed must return a JSON list, {'matches': [...]}, "
            "or {'data': {'matches': [...]}} using the canonical match schema"
        )
    return rows


class AuthorizedOfficialFeedClient:
    """Fetch a licensed official-odds feed without using browser automation.

    Credentials are read only from environment-backed settings and are never
    written to fetch logs, database observations, or exception messages.
    """

    def __init__(self, url: str, token: str = "", headers_json: str = "{}", timeout_seconds: int = 25) -> None:
        self.url = url.strip()
        self.token = token.strip()
        self.timeout_seconds = timeout_seconds
        try:
            parsed_headers = json.loads(headers_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("OFFICIAL_AUTHORIZED_API_HEADERS_JSON must be a JSON object") from exc
        if not isinstance(parsed_headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in parsed_headers.items()
        ):
            raise ValueError("OFFICIAL_AUTHORIZED_API_HEADERS_JSON must contain string header values")
        self.headers = dict(parsed_headers)

    def fetch(self, _url: str | None = None) -> dict[str, Any]:
        if not self.url.startswith(("https://", "http://")):
            raise RuntimeError("OFFICIAL_AUTHORIZED_API_URL must be an HTTP(S) URL")
        headers = {"Accept": "application/json", "User-Agent": "football-agents/1.0", **self.headers}
        if self.token and not any(key.lower() == "authorization" for key in headers):
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(self.url, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Authorized official feed HTTP {exc.code}") from exc
        rows = _matches_from_payload(payload)
        return {
            "html": json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "matches": rows,
        }
