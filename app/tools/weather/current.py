from langchain_core.tools import tool

from app.tools.weather import codes
from app.utils.http import http_client


def _format_location(result: dict) -> str:
    parts = [result.get("name"), result.get("admin1"), result.get("country")]
    return "，".join(p for p in parts if p)


def _list_get(values: list, index: int, default: str = "未知"):
    return values[index] if index < len(values) else default


@tool
def get_weather(city: str) -> str:
    """联网查询指定城市的当前天气和未来三天简要预报。"""
    city = city.strip()
    if not city:
        return "请提供要查询天气的城市或地区。"

    try:
        with http_client() as client:
            geo_resp = client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "zh"},
            )
            geo_resp.raise_for_status()
            results = geo_resp.json().get("results") or []
            if not results:
                return f"没有找到“{city}”的天气位置"

            location = results[0]
            weather_resp = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                    "current": (
                        "temperature_2m,apparent_temperature,"
                        "relative_humidity_2m,precipitation,"
                        "weather_code,wind_speed_10m"
                    ),
                    "daily": (
                        "weather_code,temperature_2m_max,temperature_2m_min,"
                        "precipitation_probability_max"
                    ),
                    "forecast_days": 3,
                    "timezone": "auto",
                },
            )
            weather_resp.raise_for_status()
            data = weather_resp.json()
    except Exception as exc:
        return f"天气服务请求失败：{exc}"

    current = data.get("current", {})
    daily = data.get("daily", {})
    loc_name = _format_location(location)

    summary = (
        f"{loc_name}\n"
        f"数据时间：{current.get('time', '未知')}\n"
        f"当前天气：{codes.describe(current.get('weather_code'))}\n"
        f"气温：{current.get('temperature_2m')}°C，"
        f"体感：{current.get('apparent_temperature')}°C\n"
        f"湿度：{current.get('relative_humidity_2m')}%，"
        f"降水量：{current.get('precipitation')} mm，"
        f"风速：{current.get('wind_speed_10m')} km/h"
    )

    forecast_lines = []
    dates = daily.get("time", [])
    max_temps = daily.get("temperature_2m_max", [])
    min_temps = daily.get("temperature_2m_min", [])
    weather_codes = daily.get("weather_code", [])
    rain_probs = daily.get("precipitation_probability_max", [])
    for index, date in enumerate(dates):
        forecast_lines.append(
            f"{date}：{codes.describe(_list_get(weather_codes, index, None))}，"
            f"{_list_get(min_temps, index)}°C - {_list_get(max_temps, index)}°C，"
            f"最高降水概率 {_list_get(rain_probs, index)}%"
        )

    forecast = "\n".join(forecast_lines) if forecast_lines else "暂无预报数据"
    return f"{summary}\n未来三天：\n{forecast}\n来源：Open-Meteo"
