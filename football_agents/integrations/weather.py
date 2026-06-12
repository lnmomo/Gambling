from __future__ import annotations

from datetime import datetime
from typing import Any

from ..config import settings
from .http import get_json


class OpenMeteoClient:
    def fetch(self, match: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any] | None:
        latitude = metadata.get("latitude"); longitude = metadata.get("longitude")
        if latitude is None or longitude is None:
            return None
        kickoff = datetime.fromisoformat(match["kickoff_time"])
        data, _ = get_json(settings.open_meteo_forecast_url, {
            "latitude": latitude, "longitude": longitude, "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
            "timezone": "Asia/Shanghai", "start_date": kickoff.date().isoformat(), "end_date": kickoff.date().isoformat(),
        }, settings.enrichment_timeout_seconds)
        hourly = data.get("hourly", {}); times = hourly.get("time", [])
        if not times:
            return None
        index = min(range(len(times)), key=lambda i: abs(datetime.fromisoformat(times[i]) - kickoff.replace(tzinfo=None)))
        return {"temperature": hourly["temperature_2m"][index], "humidity": hourly["relative_humidity_2m"][index],
                "rainfall": hourly["precipitation"][index], "wind_speed": hourly["wind_speed_10m"][index]}
