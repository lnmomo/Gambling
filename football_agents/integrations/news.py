from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from ..config import settings
from .http import get_json


class GdeltNewsClient:
    def fetch(self, match: dict[str, Any], max_records: int = 5) -> list[dict[str, Any]]:
        try:
            return self._google_news_rss(match, max_records)
        except Exception:
            return self._gdelt(match, max_records)

    def _gdelt(self, match: dict[str, Any], max_records: int) -> list[dict[str, Any]]:
        query = f'("{match["home_team"]}" OR "{match["away_team"]}") football'
        data, _ = get_json(settings.gdelt_api_url, {"query": query, "mode": "artlist",
            "maxrecords": max_records, "format": "json", "sort": "datedesc"}, settings.enrichment_timeout_seconds)
        output = []
        for article in data.get("articles", []):
            seen = article.get("seendate") or ""
            try:
                published = datetime.strptime(seen[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                published = datetime.now(timezone.utc).isoformat()
            output.append({"event_type": "news", "confidence": 0.6, "source_url": article.get("url"),
                           "published_at": published, "raw_text": article.get("title", "")})
        return output

    def _google_news_rss(self, match: dict[str, Any], max_records: int) -> list[dict[str, Any]]:
        query = f'{match["home_team"]} {match["away_team"]} 足球'
        url = "https://news.google.com/rss/search?" + urlencode(
            {"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
        request = Request(url, headers={"User-Agent": "football-agents/1.0"})
        with urlopen(request, timeout=settings.enrichment_timeout_seconds) as response:
            root = ElementTree.fromstring(response.read())
        output = []
        for item in root.findall("./channel/item")[:max_records]:
            published = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc).isoformat()
            output.append({"event_type": "news", "confidence": 0.5,
                "source_url": item.findtext("link"), "published_at": published,
                "raw_text": item.findtext("title") or ""})
        return output
