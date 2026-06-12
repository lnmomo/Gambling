from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def get_json(url: str, params: dict[str, Any], timeout: int) -> tuple[Any, dict[str, str]]:
    query = urlencode({key: value for key, value in params.items() if value is not None}, doseq=True)
    request = Request(f"{url}?{query}", headers={"User-Agent": "football-agents/1.0"})
    with urlopen(request, timeout=timeout) as response:
        headers = {key.lower(): value for key, value in response.headers.items()}
        return json.loads(response.read().decode("utf-8")), headers
