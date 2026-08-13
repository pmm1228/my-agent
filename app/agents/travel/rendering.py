from app.agents.travel.planning import PACE_LABELS


def _money(value: int, currency: str) -> str:
    symbol = "¥" if currency == "CNY" else f"{currency} "
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,}"


def render_travel_plan(plan: dict) -> str:
    request = plan["request"]
    budget = plan["budget"]
    currency = budget["currency"]
    lines = [
        f"# {request['destination']}旅行方案",
        "",
        f"- 日期：{request['start_date']} 至 {request['end_date']}",
        f"- 人数：{request['travelers']} 人",
        f"- 节奏：{PACE_LABELS.get(request.get('pace'), '适中')}",
        "",
        "## 住宿候选",
        "",
    ]
    hotels = plan.get("hotels", [])
    if hotels:
        for index, hotel in enumerate(hotels[:5], 1):
            evidence = hotel.get("evidence") or []
            source_url = evidence[0]["source_url"] if evidence else ""
            area = hotel.get("area") or "位置待核实"
            price_min = hotel.get("price_per_room_night_min")
            price_max = hotel.get("price_per_room_night_max")
            price_text = (
                f"{_money(price_min, hotel.get('currency') or currency)}–"
                f"{_money(price_max, hotel.get('currency') or currency)}/间/晚"
                if price_min is not None and price_max is not None
                else "价格和库存待核实"
            )
            name = f"[{hotel['name']}]({source_url})" if source_url else hotel["name"]
            lines.extend([
                f"{index}. {name}",
                f"   - 区域：{area}；{price_text}；置信度：{hotel.get('confidence', 'medium')}。",
            ])
    else:
        lines.append("未获得可靠酒店候选。建议优先选择交通便利的中心城区，并在预订平台核实实时价格与库存。")

    lines.extend(["", "## 每日行程", ""])
    for day in plan["itinerary"]:
        lines.append(f"### 第 {day['day']} 天 · {day['date']} · {day['area']}")
        if day.get("geography_confidence") == "unknown":
            lines.append("位置关系尚未核实，本日不会假设多个未知地点彼此邻近。")
        weather = day.get("weather")
        if weather:
            lines.append(
                f"天气：{weather['weather']}，{weather['temperature_min']}–{weather['temperature_max']}°C，"
                f"最高降水概率 {weather['precipitation_probability']}%。"
            )
        elif plan.get("weather", {}).get("message"):
            lines.append(f"天气：{plan['weather']['message']}")
        if day["activities"]:
            for activity in day["activities"]:
                activity_name = (
                    f"[{activity['name']}]({activity['source_url']})"
                    if activity.get("source_url") else activity["name"]
                )
                opening = activity.get("opening_hours")
                opening_text = f"（开放信息：{opening}；出发前请复核）" if opening else ""
                lines.append(f"- {activity['period']}：{activity_name}{opening_text}")
        else:
            unavailable = day.get("unavailable_candidates") or []
            if unavailable:
                lines.append(
                    f"- 自由活动或休息；根据来源开放信息，{'、'.join(unavailable)}"
                    "当日明确闭馆或不开放。"
                )
            else:
                lines.append("- 自由活动或休息；当前联网候选不足，请在出发前补充核实。")
        alt = next((x for x in plan["alternatives"] if x["day"] == day["day"]), None)
        if alt:
            lines.append(f"- 备选：{alt['suggestion']}")
        lines.append("")

    lines.extend(["## 预算估算", ""])
    for name, item in budget["items"].items():
        values = item["range"]
        amount = (
            f"{_money(values[0], currency)}–{_money(values[1], currency)}"
            if values is not None else "未知"
        )
        lines.append(f"- {name}：{amount}（{item['basis']}）")
    completeness_labels = {
        "complete": "完整",
        "partial": "部分费用待核实",
        "insufficient": "信息不足",
    }
    total_label = (
        "总计" if budget.get("completeness") == "complete" else "当前估算"
    )
    lines.extend([
        f"- {total_label}（含 {round(budget['contingency_rate'] * 100)}% 缓冲）："
        f"{_money(budget['total'][0], currency)}–{_money(budget['total'][1], currency)}",
        f"- 人均：{_money(budget['per_person'][0], currency)}–{_money(budget['per_person'][1], currency)}",
        f"- 预算完整性：{completeness_labels.get(budget.get('completeness'), '未知')}"
        f"（覆盖率 {round(budget.get('coverage_ratio', 0) * 100)}%）",
        f"- 当前有依据的费用（含缓冲）：{_money(budget['known_total'][0], currency)}–"
        f"{_money(budget['known_total'][1], currency)}",
    ])
    status_labels = {
        "within_budget": "预算内",
        "at_risk": "存在超预算风险",
        "over_budget": "超出预算",
        "unknown": "现有证据不足，暂不能判断是否超预算",
        "no_user_budget": "未提供用户预算",
    }
    if budget.get("user_budget") is not None:
        lines.append(f"- 用户预算：{_money(budget['user_budget'], currency)}")
    lines.append(f"- 预算风险：{status_labels.get(budget.get('risk'), '未知')}")
    if budget.get("remaining") is not None:
        remaining = budget["remaining"]
        lines.append(
            f"- 相对预算余额：{_money(remaining[0], currency)} 至 {_money(remaining[1], currency)}"
        )
    lines.append(f"- 未知或未计入：{'、'.join(budget['unknown_items'])}")
    for adjustment in budget.get("adjustments", []):
        replacement = adjustment.get("replacement_candidate_id") or "移除"
        lines.append(
            f"- 预算调整：{adjustment['removed_candidate_id']} → {replacement}，"
            f"预计节省 {_money(adjustment['savings_min'], currency)}–"
            f"{_money(adjustment['savings_max'], currency)}。"
        )
    lines.extend(["", "## 注意事项", ""])
    for warning in plan.get("warnings", []):
        lines.append(f"- {warning['message']}")
    if not plan.get("warnings"):
        lines.append("- 酒店、门票和交通费用均为估算，请在预订前核实实时价格。")

    sources = plan.get("sources", [])
    if sources:
        lines.extend(["", "## 来源", ""])
        for source in sources[:15]:
            lines.append(f"- [{source['title']}]({source['url']})")
    return "\n".join(lines)
