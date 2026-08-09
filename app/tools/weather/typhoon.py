import json
import re
import time
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import tool

from app.utils.http import http_client


SOURCE = "中央气象台 typhoon.nmc.cn"


def _extract_jsonp_payload(text: str) -> dict:
    match = re.search(r"(\{.*\})", text, re.S)
    if not match:
        raise ValueError("响应中未找到 JSON 数据")
    return json.loads(match.group(1))


def _get(values: list, index: int, default: Any = "未知") -> Any:
    return values[index] if index < len(values) else default


def _as_text(value: Any, default: str = "未知") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _format_time(timestamp_ms: Any) -> str:
    try:
        return datetime.fromtimestamp(
            int(timestamp_ms) / 1000,
            tz=timezone.utc,
        ).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(timestamp_ms or "未知")


def _parse_active_typhoon(item: list) -> dict | None:
    if len(item) < 8 or item[7] != "start":
        return None
    return {
        "id": _get(item, 0),
        "en_name": _as_text(_get(item, 1)),
        "cn_name": _as_text(_get(item, 2)),
        "number": _as_text(_get(item, 4)),
    }


def _fetch_cma_list() -> list:
    with http_client() as client:
        resp = client.get(
            "http://typhoon.nmc.cn/weatherservice/typhoon/jsons/list_default",
            params={"t": int(time.time() * 1000)},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
    data = _extract_jsonp_payload(resp.text)
    active = []
    for item in data.get("typhoonList", []):
        parsed = _parse_active_typhoon(item)
        if parsed:
            active.append(parsed)
    return active


def _fetch_cma_detail(typhoon_id: int) -> dict | None:
    with http_client() as client:
        resp = client.get(
            f"http://typhoon.nmc.cn/weatherservice/typhoon/jsons/view_{typhoon_id}",
            params={"t": int(time.time() * 1000)},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
    data = _extract_jsonp_payload(resp.text)
    typhoon = data.get("typhoon") or []
    if len(typhoon) < 9 or not typhoon[8]:
        return None

    latest = typhoon[8][-1]
    if not isinstance(latest, list):
        return None

    detail = {
        "cn_name": _as_text(_get(typhoon, 2)),
        "en_name": _as_text(_get(typhoon, 1)),
        "number": _as_text(_get(typhoon, 4)),
        "meaning": _as_text(_get(typhoon, 6, ""), ""),
        "strength": _as_text(_get(latest, 3)),
        "longitude": _as_text(_get(latest, 4)),
        "latitude": _as_text(_get(latest, 5)),
        "pressure_hpa": _as_text(_get(latest, 6)),
        "wind_speed_ms": _as_text(_get(latest, 7)),
        "direction": _as_text(_get(latest, 8)),
        "move_speed_kmh": _as_text(_get(latest, 9)),
        "update_time": _format_time(_get(latest, 2, None)),
        "forecast": [],
    }

    forecast_block = _get(latest, 11, {})
    if not isinstance(forecast_block, dict):
        forecast_block = {}

    for forecast in forecast_block.get("BABJ", []):
        if not isinstance(forecast, list) or len(forecast) < 8:
            continue
        detail["forecast"].append(
            {
                "hours_ahead": _as_text(_get(forecast, 0)),
                "longitude": _as_text(_get(forecast, 2)),
                "latitude": _as_text(_get(forecast, 3)),
                "pressure": _as_text(_get(forecast, 4)),
                "wind_speed_ms": _as_text(_get(forecast, 5)),
                "strength": _as_text(_get(forecast, 7)),
            }
        )
    return detail


@tool
def get_typhoon(name: str = "") -> str:
    """查询当前活跃台风信息。不传 name 返回活跃台风列表，传名称返回详情和预报路径。"""
    try:
        active = _fetch_cma_list()
    except (json.JSONDecodeError, ValueError) as exc:
        return f"台风数据解析失败：{exc}。来源：{SOURCE}"
    except Exception as exc:
        return f"台风数据服务请求失败：{exc}。来源：{SOURCE}"

    if not active:
        return f"当前西北太平洋及南海无活跃台风。来源：{SOURCE}"

    if not name.strip():
        lines = ["当前活跃台风："]
        for typhoon in active:
            lines.append(
                f"• {typhoon['cn_name']}（{typhoon['en_name']}，"
                f"编号 {typhoon['number']}）"
            )
        lines.append(f"来源：{SOURCE}")
        return "\n".join(lines)

    target = None
    normalized_name = name.strip().lower()
    for typhoon in active:
        if (
            normalized_name in typhoon["cn_name"].lower()
            or normalized_name in typhoon["en_name"].lower()
        ):
            target = typhoon
            break

    if not target:
        available = "、".join(typhoon["cn_name"] for typhoon in active)
        return f"未找到名为 “{name}” 的活跃台风。当前活跃的有：{available}"

    try:
        detail = _fetch_cma_detail(target["id"])
    except (json.JSONDecodeError, ValueError) as exc:
        return f"解析 {target['cn_name']} 详情失败：{exc}。来源：{SOURCE}"
    except Exception as exc:
        return f"获取 {target['cn_name']} 详情失败：{exc}。来源：{SOURCE}"

    if not detail:
        return f"无法解析 {target['cn_name']} 的详情数据。来源：{SOURCE}"

    summary = (
        f"【台风详情】\n"
        f"名称：{detail['cn_name']}（{detail['en_name']}）编号 {detail['number']}\n"
        f"名字含义：{detail['meaning']}\n"
        f"强度：{detail['strength']}\n"
        f"当前位置：{detail['longitude']}°E, {detail['latitude']}°N\n"
        f"中心气压：{detail['pressure_hpa']} hPa\n"
        f"最大风速：{detail['wind_speed_ms']} m/s\n"
        f"移动方向：{detail['direction']}，速度：{detail['move_speed_kmh']} km/h\n"
        f"数据时间：{detail['update_time']}"
    )

    if detail["forecast"]:
        forecast_lines = ["未来预报路径："]
        for forecast in detail["forecast"]:
            forecast_lines.append(
                f"  +{forecast['hours_ahead']}h "
                f"{forecast['longitude']}°E/{forecast['latitude']}°N "
                f"气压 {forecast['pressure']}hPa "
                f"风速 {forecast['wind_speed_ms']}m/s"
            )
        summary += "\n" + "\n".join(forecast_lines)

    return summary + f"\n来源：{SOURCE}"
