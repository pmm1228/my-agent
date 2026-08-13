from datetime import date

from app.tools.weather import codes
from app.utils.http import http_client


def _at(values: list, index: int):
    return values[index] if index < len(values) else None


def _normalize_place(value: str) -> str:
    normalized = "".join(value.lower().split())
    for suffix in ("特别行政区", "自治区", "自治州", "省", "市", "区", "县"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def _select_location(city: str, locations: list[dict]) -> dict | None:
    query = _normalize_place(city)
    scored = []
    for location in locations:
        name = _normalize_place(str(location.get("name", "")))
        if not name:
            continue
        score = 100 if name == query else 70 if name in query else 0
        for field in ("admin1", "admin2", "country"):
            context = _normalize_place(str(location.get(field, "")))
            if context and context in query:
                score += 10
        if score:
            scored.append((score, location))
    return max(scored, key=lambda item: item[0])[1] if scored else None


def get_weather_forecast(city: str, start_date: str, end_date: str) -> dict:
    """Return available daily forecasts, explicitly marking out-of-range dates."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    try:
        with http_client() as client:
            geo_resp = client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 5, "language": "zh"},
            )
            geo_resp.raise_for_status()
            locations = geo_resp.json().get("results") or []
            if not locations:
                return {"status": "location_not_found", "forecast": [], "message": f"无法识别天气位置：{city}"}
            location = _select_location(city, locations)
            if location is None:
                return {
                    "status": "location_ambiguous",
                    "forecast": [],
                    "message": f"天气位置存在歧义，无法安全匹配：{city}",
                }
            response = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "forecast_days": 16,
                    "timezone": "auto",
                },
            )
            response.raise_for_status()
            daily = response.json().get("daily", {})
    except Exception as exc:
        return {"status": "failed", "forecast": [], "message": f"天气服务请求失败：{exc}"}

    result = []
    dates = daily.get("time", [])
    for index, value in enumerate(dates):
        current = date.fromisoformat(value)
        if start <= current <= end:
            result.append({
                "date": value,
                "weather": codes.describe(_at(daily.get("weather_code") or [], index)),
                "temperature_min": _at(daily.get("temperature_2m_min") or [], index),
                "temperature_max": _at(daily.get("temperature_2m_max") or [], index),
                "precipitation_probability": _at(daily.get("precipitation_probability_max") or [], index),
            })
    status = "available" if result and len(result) == (end - start).days + 1 else "partial" if result else "out_of_range"
    message = None if status == "available" else "旅行日期超出或部分超出可靠预报范围，建议出发前 7–14 天重新查询。"
    resolved_location = ", ".join(
        str(location.get(field))
        for field in ("name", "admin1", "country")
        if location.get(field)
    )
    return {
        "status": status,
        "location": city,
        "resolved_location": resolved_location,
        "forecast": result,
        "message": message,
        "source": "Open-Meteo",
    }
