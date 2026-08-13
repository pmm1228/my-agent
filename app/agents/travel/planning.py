import math
import re
from copy import deepcopy
from collections import OrderedDict
from datetime import date


PACE_LIMITS = {"relaxed": 2, "balanced": 3, "intensive": 4}
PACE_LABELS = {"relaxed": "轻松", "balanced": "适中", "intensive": "紧凑"}
DESTINATION_COST_PROFILES = {
    "上海": {"currency": "CNY", "meals": (120, 250), "transport": (40, 100)},
    "北京": {"currency": "CNY", "meals": (110, 240), "transport": (35, 90)},
    "深圳": {"currency": "CNY", "meals": (120, 260), "transport": (40, 100)},
    "广州": {"currency": "CNY", "meals": (100, 230), "transport": (35, 90)},
    "杭州": {"currency": "CNY", "meals": (100, 230), "transport": (35, 90)},
    "成都": {"currency": "CNY", "meals": (90, 210), "transport": (30, 80)},
    "重庆": {"currency": "CNY", "meals": (90, 210), "transport": (30, 80)},
    "西安": {"currency": "CNY", "meals": (80, 190), "transport": (30, 75)},
}
WEEKDAY_NAMES = {
    0: ("周一", "星期一", "礼拜一"),
    1: ("周二", "星期二", "礼拜二"),
    2: ("周三", "星期三", "礼拜三"),
    3: ("周四", "星期四", "礼拜四"),
    4: ("周五", "星期五", "礼拜五"),
    5: ("周六", "星期六", "礼拜六"),
    6: ("周日", "周天", "星期日", "星期天", "礼拜日", "礼拜天"),
}


def _explicitly_closed_on(candidate: dict, day_date: date) -> bool:
    opening = candidate.get("opening_hours") or ""
    if not opening:
        return False
    closed = r"闭馆|闭园|不开放|暂停开放|休息"
    for weekday in WEEKDAY_NAMES[day_date.weekday()]:
        if re.search(rf"{re.escape(weekday)}[^，。；;]{{0,10}}(?:{closed})", opening):
            return True
        if re.search(rf"(?:{closed})[^，。；;]{{0,10}}{re.escape(weekday)}", opening):
            return True
    return False


def build_itinerary(request: dict, attractions: list[dict], weather: dict) -> list[dict]:
    start = date.fromisoformat(request["start_date"])
    end = date.fromisoformat(request["end_date"])
    days = (end - start).days + 1
    per_day = PACE_LIMITS.get(request.get("pace", "balanced"), 3)
    groups: OrderedDict[str, tuple[str, list[dict]]] = OrderedDict()
    for attraction in attractions:
        area = attraction.get("area")
        key = area or f"unknown:{attraction.get('id', attraction.get('name', ''))}"
        display_area, group = groups.setdefault(
            key, (area or "位置待核实", [])
        )
        group.append(attraction)
    pending_groups = [
        [display_area, list(group)] for display_area, group in groups.values()
    ]
    itinerary = []
    for index in range(days):
        day_date = start.fromordinal(start.toordinal() + index)
        area, activities = "自由活动", []
        unavailable_candidates = []
        for group in pending_groups:
            display_area, remaining = group
            available = [
                item for item in remaining
                if not _explicitly_closed_on(item, day_date)
            ]
            if available:
                area = display_area
                activities = available[:per_day]
                selected_ids = {id(item) for item in activities}
                group[1] = [item for item in remaining if id(item) not in selected_ids]
                break
            unavailable_candidates.extend(item["name"] for item in remaining)
        pending_groups = [group for group in pending_groups if group[1]]
        itinerary.append({
            "day": index + 1,
            "date": day_date.isoformat(),
            "area": area,
            "geography_confidence": "unknown" if area == "位置待核实" else "area_verified",
            "unavailable_candidates": unavailable_candidates,
            "activities": [
                {
                    "period": ["上午", "下午", "傍晚", "晚上"][i],
                    "attraction_id": item["id"],
                    "name": item["name"],
                    "ticket_price_min": item.get("ticket_price_min"),
                    "ticket_price_max": item.get("ticket_price_max"),
                    "currency": item.get("currency"),
                    "opening_hours": item.get("opening_hours"),
                    "source_url": (
                        item.get("evidence", [{}])[0].get("source_url", "")
                        if item.get("evidence") else ""
                    ),
                }
                for i, item in enumerate(activities)
            ],
            "weather": next(
                (x for x in weather.get("forecast", []) if x.get("date") == day_date.isoformat()),
                None,
            ),
        })
    return itinerary


def calculate_budget(request: dict, itinerary: list[dict], hotels: list[dict]) -> dict:
    travelers = request["travelers"]
    rooms = request.get("rooms") or math.ceil(travelers / 2)
    nights = max(0, len(itinerary) - 1)
    currency = request.get("currency", "CNY")
    level = request.get("hotel_level", "unspecified")
    fallback_nightly = {
        "economy": (250, 450),
        "comfortable": (450, 800),
        "premium": (900, 1800),
        "unspecified": (350, 800),
    }[level]
    priced_hotels = [
        hotel for hotel in hotels
        if hotel.get("price_per_room_night_min") is not None
        and hotel.get("price_per_room_night_max") is not None
        and (not hotel.get("currency") or hotel.get("currency") == currency)
    ]
    priced_hotel = min(
        priced_hotels,
        key=lambda hotel: hotel["price_per_room_night_max"],
        default=None,
    )
    critical_unknown: list[str] = []
    if nights == 0:
        lodging = (0, 0)
        lodging_basis = "当日往返，不计住宿"
        lodging_confidence = "high"
        lodging_is_known = True
    elif priced_hotel:
        lodging = (
            priced_hotel["price_per_room_night_min"] * rooms * nights,
            priced_hotel["price_per_room_night_max"] * rooms * nights,
        )
        lodging_basis = f"{priced_hotel['name']} × {rooms} 间 × {nights} 晚"
        lodging_confidence = "medium"
        lodging_is_known = True
    elif currency == "CNY":
        lodging = (
            fallback_nightly[0] * rooms * nights,
            fallback_nightly[1] * rooms * nights,
        )
        lodging_basis = f"{level}住宿基准 × {rooms} 间 × {nights} 晚"
        lodging_confidence = "low"
        lodging_is_known = False
        critical_unknown.append("酒店实时价格与库存")
    else:
        lodging = None
        lodging_basis = f"缺少 {currency} 币种的住宿价格依据"
        lodging_confidence = "unknown"
        lodging_is_known = False
        critical_unknown.append("酒店实时价格与库存")

    cost_profile = next(
        (
            profile for city, profile in DESTINATION_COST_PROFILES.items()
            if city in request.get("destination", "")
            and profile["currency"] == currency
        ),
        None,
    )
    if cost_profile:
        meals = (
            cost_profile["meals"][0] * travelers * len(itinerary),
            cost_profile["meals"][1] * travelers * len(itinerary),
        )
        local_transport = (
            cost_profile["transport"][0] * travelers * len(itinerary),
            cost_profile["transport"][1] * travelers * len(itinerary),
        )
    else:
        meals = None
        local_transport = None
        critical_unknown.extend(["目的地餐饮消费", "目的地市内交通消费"])
    ticket_min = ticket_max = 0
    known_ticket_count = 0
    scheduled_activity_count = 0
    unknown: list[str] = ["个人购物"]
    for day in itinerary:
        for activity in day.get("activities", []):
            scheduled_activity_count += 1
            minimum = activity.get("ticket_price_min")
            maximum = activity.get("ticket_price_max")
            activity_currency = activity.get("currency")
            if (
                minimum is None
                or maximum is None
                or (activity_currency and activity_currency != currency)
            ):
                item = f"{activity['name']}门票"
                if item not in unknown:
                    unknown.append(item)
                    critical_unknown.append(item)
                continue
            ticket_min += minimum * travelers
            ticket_max += maximum * travelers
            known_ticket_count += 1
    if scheduled_activity_count == 0:
        tickets = (0, 0)
    else:
        tickets = (ticket_min, ticket_max) if known_ticket_count else None

    if not priced_hotel and nights:
        unknown.append("酒店实时价格与库存（当前采用低置信度档次估算）")
    if meals is None:
        unknown.append("目的地餐饮消费")
    if local_transport is None:
        unknown.append("目的地市内交通消费")
    if request.get("budget_scope") == "including_round_trip":
        unknown.append("往返大交通")
        critical_unknown.append("往返大交通")
    else:
        unknown.append("往返大交通（不在本次预算范围）")

    subtotal_min = (
        (lodging or (0, 0))[0]
        + (meals or (0, 0))[0]
        + (local_transport or (0, 0))[0]
        + (tickets or (0, 0))[0]
    )
    subtotal_max = (
        (lodging or (0, 0))[1]
        + (meals or (0, 0))[1]
        + (local_transport or (0, 0))[1]
        + (tickets or (0, 0))[1]
    )
    contingency = (round(subtotal_min * 0.1), round(subtotal_max * 0.1))
    total = (subtotal_min + contingency[0], subtotal_max + contingency[1])
    ticket_is_known = scheduled_activity_count == known_ticket_count
    known_subtotal_min = (
        (lodging[0] if lodging_is_known else 0)
        + (meals or (0, 0))[0]
        + (local_transport or (0, 0))[0]
        + ticket_min
    )
    known_subtotal_max = (
        (lodging[1] if lodging_is_known else 0)
        + (meals or (0, 0))[1]
        + (local_transport or (0, 0))[1]
        + ticket_max
    )
    known_total = (
        known_subtotal_min + round(known_subtotal_min * 0.1),
        known_subtotal_max + round(known_subtotal_max * 0.1),
    )
    known_components = sum((
        lodging_is_known,
        meals is not None,
        local_transport is not None,
        ticket_is_known,
    ))
    if not critical_unknown:
        completeness = "complete"
    elif known_components:
        completeness = "partial"
    else:
        completeness = "insufficient"

    user_budget = request.get("budget_total")
    if user_budget is None:
        risk = "no_user_budget"
    elif known_total[0] > user_budget:
        risk = "over_budget"
    elif completeness == "complete" and total[1] <= user_budget:
        risk = "within_budget"
    elif completeness == "complete" and total[0] <= user_budget:
        risk = "at_risk"
    elif completeness == "complete":
        risk = "over_budget"
    elif total[1] > user_budget:
        risk = "at_risk"
    else:
        risk = "unknown"

    return {
        "currency": currency,
        "rooms": rooms,
        "items": {
            "住宿": {"range": lodging, "basis": lodging_basis, "confidence": lodging_confidence},
            "餐饮": {"range": meals, "basis": f"目的地配置 × {travelers} 人 × {len(itinerary)} 天" if meals else "缺少目的地消费配置", "confidence": "medium" if meals else "unknown"},
            "市内交通": {"range": local_transport, "basis": f"目的地配置 × {travelers} 人 × {len(itinerary)} 天" if local_transport else "缺少目的地消费配置", "confidence": "medium" if local_transport else "unknown"},
            "景点门票": {"range": tickets, "basis": f"{known_ticket_count} 个有价格证据的实际活动", "confidence": "high" if scheduled_activity_count == 0 else "medium" if tickets else "unknown"},
            "缓冲金": {"range": contingency, "basis": "已估算支出的 10%", "confidence": "high"},
        },
        "contingency_rate": 0.1,
        "total": total,
        "known_total": known_total,
        "per_person": (round(total[0] / travelers), round(total[1] / travelers)),
        "unknown_items": unknown,
        "critical_unknown_items": critical_unknown,
        "completeness": completeness,
        "coverage_ratio": known_components / 4,
        "risk": risk,
        "is_complete": completeness == "complete",
        "selected_hotel_id": priced_hotel.get("id") if priced_hotel else None,
        "user_budget": user_budget,
        "remaining": (
            (user_budget - total[1], user_budget - total[0])
            if user_budget is not None and completeness == "complete" else None
        ),
        "adjustments": [],
        "is_estimate": True,
    }


def activity_from_candidate(candidate: dict, period: str) -> dict:
    evidence = candidate.get("evidence") or []
    return {
        "period": period,
        "attraction_id": candidate["id"],
        "name": candidate["name"],
        "ticket_price_min": candidate.get("ticket_price_min"),
        "ticket_price_max": candidate.get("ticket_price_max"),
        "currency": candidate.get("currency"),
        "opening_hours": candidate.get("opening_hours"),
        "source_url": evidence[0].get("source_url", "") if evidence else "",
    }


def optimize_plan_for_budget(
    request: dict,
    itinerary: list[dict],
    hotels: list[dict],
    attractions: list[dict],
) -> tuple[list[dict], dict]:
    optimized = deepcopy(itinerary)
    budget = calculate_budget(request, optimized, hotels)
    if budget["risk"] not in {"at_risk", "over_budget"}:
        return optimized, budget

    used_ids = {
        activity["attraction_id"]
        for day in optimized for activity in day.get("activities", [])
    }
    free_candidates = [
        candidate for candidate in attractions
        if candidate["id"] not in used_ids
        and candidate.get("ticket_price_min") == 0
        and candidate.get("ticket_price_max") == 0
        and (not candidate.get("currency") or candidate.get("currency") == budget["currency"])
    ]
    adjustments = []
    for _ in range(2):
        if budget["risk"] not in {"at_risk", "over_budget"}:
            break
        priced = [
            (day, activity)
            for day in optimized
            for activity in day.get("activities", [])
            if activity.get("ticket_price_max") not in {None, 0}
        ]
        if not priced:
            break
        day, target = max(priced, key=lambda pair: pair[1]["ticket_price_max"])
        replacement = next(
            (
                candidate for candidate in free_candidates
                if (candidate.get("area") or "位置待核实") == day["area"]
            ),
            None,
        )
        old_min = target.get("ticket_price_min") or 0
        old_max = target.get("ticket_price_max") or 0
        if replacement:
            index = day["activities"].index(target)
            day["activities"][index] = activity_from_candidate(
                replacement, target["period"]
            )
            free_candidates.remove(replacement)
            action = "replace_paid_attraction"
            replacement_id = replacement["id"]
        else:
            day["activities"].remove(target)
            action = "remove_paid_attraction"
            replacement_id = None
        adjustments.append({
            "action": action,
            "removed_candidate_id": target["attraction_id"],
            "replacement_candidate_id": replacement_id,
            "savings_min": old_min * request["travelers"],
            "savings_max": old_max * request["travelers"],
            "reason": "为满足用户总预算，优先调整低约束的收费活动。",
        })
        budget = calculate_budget(request, optimized, hotels)
    budget["adjustments"] = adjustments
    return optimized, budget


def build_alternatives(
    itinerary: list[dict],
    attractions: list[dict] | None = None,
) -> list[dict]:
    attractions = attractions or []
    used_ids = {
        activity.get("attraction_id")
        for day in itinerary for activity in day.get("activities", [])
    }
    alternatives = []
    for day in itinerary:
        candidates = [
            candidate for candidate in attractions
            if candidate.get("id") not in used_ids
            and day.get("geography_confidence") != "unknown"
            and (candidate.get("area") or "位置待核实") == day.get("area")
        ]
        precipitation = (day.get("weather") or {}).get("precipitation_probability")
        if precipitation is not None and precipitation >= 50:
            candidates.sort(key=lambda candidate: candidate.get("indoor") is True, reverse=True)
        candidates = candidates[:2]
        names = [candidate["name"] for candidate in candidates]
        suggestion = (
            f"同区域可替换为：{'、'.join(names)}。"
            if names
            else "当前没有已核实的同区域候选；可减少一个景点并增加休息时间。"
        )
        alternatives.append({
            "day": day["day"],
            "trigger": "降雨、临时闭馆或体力不足",
            "suggestion": suggestion,
            "candidate_ids": [candidate.get("id") for candidate in candidates],
            "candidate_names": names,
            "verification_required": True,
        })
    return alternatives
