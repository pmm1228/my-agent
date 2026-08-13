import re
import uuid
from copy import deepcopy
from datetime import date

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from app.agents.travel.state import TravelState
from app.agents.travel.candidate_extraction import extract_with_page_enrichment
from app.agents.travel.extraction import extract_trip_patch, extract_trip_revision
from app.agents.travel.planning import (
    PACE_LIMITS,
    activity_from_candidate,
    build_alternatives,
    build_itinerary,
    optimize_plan_for_budget,
)
from app.agents.travel.rendering import render_travel_plan
from app.agents.travel.schemas import SearchDocument, TripRequest, TripRevision
from app.tools.search.tavily import tavily_search
from app.tools.weather.forecast import get_weather_forecast


TRAVEL_CONTEXT = (
    "旅游", "旅行", "出游", "度假", "景点", "酒店", "住宿", "目的地",
    "几日游", "几天游", "每日行程", "旅游攻略", "旅行攻略", "之旅",
)
PLANNING_ACTIONS = (
    "规划", "安排", "制定", "攻略", "路线", "计划", "怎么玩", "怎么游",
)
EXPLICIT_TRAVEL_PHRASES = ("行程规划", "规划行程", "旅游计划", "旅行计划")
CANCEL_KEYWORDS = ("取消规划", "取消旅行规划", "不规划了", "算了")
NEW_PLAN_KEYWORDS = (
    "重新规划", "新行程", "再规划", "另一个旅行", "另一个行程",
    "另外规划", "再做一个旅行", "再做一个行程",
)
REVISION_PATTERNS = (
    r"(?:旅行|行程|本次)预算",
    r"预算(?:改为|调整为|控制在|不超过|提高到|降低到)\s*\d+",
    r"(?:出行)?人数(?:改为|换成|增加到|减少到)\s*\d+",
    r"房间(?:改为|换成|增加到|减少到)\s*\d+",
    r"酒店(?:档次|等级).*(?:改|换|便宜|调整)",
    r"景点(?:改|换|删|增加|调整)",
    r"(?:出发|返程|旅行)日期", r"(?:轻松|紧凑|节奏).*(?:一点|调整|改)",
)
ACTIVE_TRAVEL_STAGES = {"collecting", "ready", "researching"}
COMMON_DESTINATIONS = {
    "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "西安", "南京",
    "苏州", "武汉", "长沙", "青岛", "厦门", "三亚", "桂林", "昆明", "丽江",
    "大理", "哈尔滨", "香港", "澳门", "台北", "东京", "大阪", "京都", "首尔",
    "新加坡", "曼谷", "普吉岛", "巴黎", "伦敦", "罗马", "纽约", "悉尼", "迪拜",
    "巴厘岛", "日本", "韩国", "泰国", "法国", "英国", "意大利", "澳大利亚",
}


def _message_text(message) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return ""


def latest_user_text(state: TravelState) -> str:
    for message in reversed(state.get("messages", [])):
        if getattr(message, "type", None) in {"human", "user"}:
            return _message_text(message)
        if isinstance(message, dict) and message.get("role") == "user":
            return _message_text(message)
    return ""


def is_bare_new_plan_request(text: str) -> bool:
    compact = re.sub(r"[\s，。！？!?]+", "", text)
    return compact in {"重新规划", "再规划", "新行程", "重新做一个", "重新来"}


def route_intent_node(state: TravelState) -> dict:
    text = latest_user_text(state)
    stage = state.get("travel_stage")
    has_context = any(word in text for word in TRAVEL_CONTEXT)
    numbered_trip = bool(re.search(r"[一二三四五六七八九十两\d]+\s*[日天]游", text))
    if stage in ACTIVE_TRAVEL_STAGES and any(word in text for word in CANCEL_KEYWORDS):
        return {"workflow_agent": "travel", "travel_action": "travel_cancel"}
    if (
        any(word in text for word in NEW_PLAN_KEYWORDS)
        and (has_context or numbered_trip)
    ) or (stage is not None and is_bare_new_plan_request(text)):
        return {"workflow_agent": "travel", "travel_action": "travel_new"}
    if stage in ACTIVE_TRAVEL_STAGES:
        if _looks_like_trip_field_update(text, state.get("missing_fields", [])):
            return {"workflow_agent": "travel", "travel_action": "travel_continue"}
        return {"travel_action": "general"}
    day_revision = bool(re.search(r"第[一二三四五六七八九十两\d]+天", text))
    known_activity_names = [
        item.get("name", "")
        for day in state.get("itinerary", [])
        for item in day.get("activities", [])
    ]
    known_activity_names.extend(
        item.get("name", "") for item in state.get("attraction_candidates", [])
    )
    activity_revision = (
        any(name and name in text for name in known_activity_names)
        and any(word in text for word in ("换成", "替换", "删除", "删掉", "增加", "加到"))
    )
    if stage == "completed" and (
        any(re.search(pattern, text) for pattern in REVISION_PATTERNS)
        or day_revision
        or activity_revision
    ):
        return {"workflow_agent": "travel", "travel_action": "travel_revision"}

    has_action = any(word in text for word in PLANNING_ACTIONS)
    explicit_phrase = any(phrase in text for phrase in EXPLICIT_TRAVEL_PHRASES)
    if (has_context and has_action) or numbered_trip or "酒店候选" in text or explicit_phrase:
        return {"workflow_agent": "travel", "travel_action": "travel_new"}
    return {"travel_action": "general"}


def _looks_like_trip_field_update(text: str, missing_fields: list[str]) -> bool:
    if not text.strip():
        return False
    signals = (
        r"\d{4}[-/.年]\d{1,2}", r"\d{1,2}月\d{1,2}",
        r"(?:明天|后天|下周|下个月|国庆|春节|暑假|寒假)",
        r"(?:\d+|[一二三四五六七八九十两]+)\s*(?:个)?(?:人|位|口)",
        r"\d+\s*(?:间|个房间)",
        r"\d+\s*(?:元|块|人民币|美元)",
        r"(?:轻松|适中|紧凑|经济型|舒适型|高端)",
        r"(?:老人|儿童|小孩|无障碍|轮椅)",
    )
    if any(re.search(pattern, text) for pattern in signals):
        return True
    if any(word in text for word in TRAVEL_CONTEXT):
        return True
    if "目的地" in missing_fields:
        value = text.strip()
        if value in COMMON_DESTINATIONS:
            return True
        if len(value) <= 20 and re.search(r"(?:市|省|县|州|岛|国)$", value):
            return True
    return False


def route_from_intent(state: TravelState) -> str:
    return state.get("travel_action", "general")


def reset_travel_state_node(state: TravelState) -> dict:
    if state.get("travel_action") != "travel_new":
        raise ValueError("只有明确的新旅行请求可以重置旅行状态")
    return {
        "plan_id": str(uuid.uuid4()),
        "travel_stage": "collecting",
        "trip_request": {},
        "missing_fields": [],
        "research_plan": [],
        "research_documents": [],
        "research_approved": None,
        "research_round": 0,
        "attraction_candidates": [],
        "hotel_candidates": [],
        "weather_result": {},
        "itinerary": [],
        "budget": {},
        "alternatives": [],
        "warnings": [],
        "sources": [],
        "travel_plan": {},
        "revision_patch": {},
        "revision_error": None,
    }


def cancel_travel_node(state: TravelState) -> dict:
    return {
        "messages": [AIMessage(content="已取消当前未完成的旅行规划。")],
        "travel_stage": "cancelled",
        "travel_action": "general",
        "missing_fields": [],
        "research_plan": [],
        "research_documents": [],
        "research_approved": None,
    }


def collect_trip_node(state: TravelState) -> dict:
    existing = dict(state.get("trip_request") or {})
    warnings = [
        item for item in state.get("warnings", [])
        if item.get("stage") not in {"collecting", "validation"}
    ]
    try:
        patch = extract_trip_patch(latest_user_text(state), existing)
        existing.update(patch)
    except Exception as exc:
        warnings.append({
            "code": "TRIP_EXTRACTION_FAILED",
            "severity": "warning",
            "stage": "collecting",
            "message": "没有完全识别本轮旅行信息，请按提示补充。",
            "details": {"error": str(exc)},
        })
    return {
        "trip_request": existing,
        "travel_stage": "collecting",
        "warnings": warnings,
    }


def extract_revision_node(state: TravelState) -> dict:
    warnings = [
        item for item in state.get("warnings", [])
        if item.get("stage") != "revision"
    ]
    try:
        revision = extract_trip_revision(
            latest_user_text(state),
            dict(state.get("trip_request") or {}),
            list(state.get("itinerary") or []),
            list(state.get("attraction_candidates") or []),
        )
    except Exception as exc:
        warnings.append({
            "code": "REVISION_EXTRACTION_FAILED",
            "severity": "warning",
            "stage": "revision",
            "message": "没有识别到可安全执行的行程修改，原方案未改变。",
            "details": {"error": str(exc)},
        })
        return {
            "revision_patch": {},
            "revision_error": "请明确说明要修改哪一天、哪个活动或哪项预算字段。",
            "warnings": warnings,
            "travel_stage": "revising",
        }
    return {
        "revision_patch": revision.model_dump(mode="json"),
        "revision_error": None,
        "warnings": warnings,
        "travel_stage": "revising",
    }


def route_after_revision_extraction(state: TravelState) -> str:
    return "invalid" if state.get("revision_error") else "valid"


def _normalized_activity_name(value: str | None) -> str:
    return re.sub(r"[\s·•\-—_（）()【】\[\]]+", "", value or "").lower()


def apply_revision_node(state: TravelState) -> dict:
    """Atomically apply request and local candidate changes to an existing plan."""
    try:
        revision = TripRevision.model_validate(state.get("revision_patch") or {})
        request = dict(state.get("trip_request") or {})
        itinerary = deepcopy(state.get("itinerary") or [])
        candidates = list(state.get("attraction_candidates") or [])
        request.update(revision.request_updates)
        request = TripRequest.model_validate(request).model_dump(mode="json")
        pace_changed = "pace" in revision.request_updates

        candidates_by_name = {
            _normalized_activity_name(item.get("name")): item
            for item in candidates if item.get("name")
        }
        used_ids = {
            activity.get("attraction_id")
            for day in itinerary for activity in day.get("activities", [])
        }
        periods = ["上午", "下午", "傍晚", "晚上"]
        for operation in revision.operations:
            day = next(
                (item for item in itinerary if item.get("day") == operation.day),
                None,
            )
            if day is None:
                raise ValueError(f"行程中不存在第 {operation.day} 天")
            activities = day.setdefault("activities", [])
            target = None
            if operation.target_name:
                target_key = _normalized_activity_name(operation.target_name)
                target = next(
                    (
                        item for item in activities
                        if _normalized_activity_name(item.get("name")) == target_key
                    ),
                    None,
                )
                if target is None:
                    raise ValueError(
                        f"第 {operation.day} 天没有找到活动：{operation.target_name}"
                    )

            replacement = None
            if operation.replacement_name:
                replacement = candidates_by_name.get(
                    _normalized_activity_name(operation.replacement_name)
                )
                if replacement is None:
                    raise ValueError(
                        f"当前已核实候选中没有：{operation.replacement_name}；"
                        "原方案未改变，如需新增候选请重新授权搜索。"
                    )
                if (
                    replacement.get("id") in used_ids
                    and (target is None or replacement.get("id") != target.get("attraction_id"))
                ):
                    raise ValueError(f"{replacement['name']} 已安排在其他日期")
                replacement_area = replacement.get("area") or "位置待核实"
                other_activities = [item for item in activities if item is not target]
                if other_activities and replacement_area != day.get("area"):
                    raise ValueError(
                        f"{replacement['name']} 与第 {operation.day} 天现有区域不同，"
                        "为避免跨区误排，原方案未改变。"
                    )

            if operation.operation == "remove_activity":
                activities.remove(target)
                used_ids.discard(target.get("attraction_id"))
            elif operation.operation == "replace_activity":
                index = activities.index(target)
                activities[index] = activity_from_candidate(
                    replacement, target.get("period", periods[min(index, 3)])
                )
                used_ids.discard(target.get("attraction_id"))
                used_ids.add(replacement.get("id"))
                if not other_activities:
                    day["area"] = replacement.get("area") or "位置待核实"
            else:
                if len(activities) >= len(periods):
                    raise ValueError(f"第 {operation.day} 天活动已满，无法继续增加")
                activities.append(
                    activity_from_candidate(replacement, periods[len(activities)])
                )
                used_ids.add(replacement.get("id"))
                if len(activities) == 1:
                    day["area"] = replacement.get("area") or "位置待核实"
            if not activities:
                day["area"] = "自由活动"
        if pace_changed:
            scheduled_ids = {
                activity.get("attraction_id")
                for day in itinerary for activity in day.get("activities", [])
            }
            scheduled_candidates = [
                candidate for candidate in candidates
                if candidate.get("id") in scheduled_ids
            ]
            itinerary = build_itinerary(
                request,
                scheduled_candidates,
                state.get("weather_result") or {},
            )
    except Exception as exc:
        return {
            "revision_error": str(exc),
            "travel_stage": "revising",
        }
    return {
        "trip_request": request,
        "itinerary": itinerary,
        "revision_error": None,
        "travel_stage": "revising",
    }


def route_after_revision_apply(state: TravelState) -> str:
    return "invalid" if state.get("revision_error") else "applied"


def revision_feedback_node(state: TravelState) -> dict:
    return {
        "messages": [AIMessage(content=state.get("revision_error") or "行程修改失败，原方案未改变。")],
        "travel_stage": "completed",
    }


def validate_trip_node(state: TravelState) -> dict:
    raw = dict(state.get("trip_request") or {})
    warnings = list(state.get("warnings") or [])
    try:
        request = TripRequest.model_validate(raw)
    except Exception as exc:
        warnings.append({
            "code": "INVALID_TRIP_REQUEST",
            "severity": "error",
            "stage": "validation",
            "message": str(exc),
            "user_action_required": True,
        })
        return {"missing_fields": ["有效的旅行日期或人数"], "warnings": warnings}

    if request.start_date and request.start_date < date.today():
        warnings.append({
            "code": "PAST_START_DATE",
            "severity": "error",
            "stage": "validation",
            "message": "出发日期不能早于今天。",
            "user_action_required": True,
        })
        return {"missing_fields": ["有效的未来出发日期"], "warnings": warnings}
    return {
        "trip_request": request.model_dump(mode="json"),
        "missing_fields": request.missing_required(),
        "warnings": warnings,
    }


def route_after_validation(state: TravelState) -> str:
    return "missing" if state.get("missing_fields") else "ready"


def ask_missing_node(state: TravelState) -> dict:
    fields = "、".join(state.get("missing_fields") or ["必要信息"])
    errors = [
        item["message"] for item in state.get("warnings", [])
        if item.get("severity") == "error"
    ]
    prefix = f"目前的信息有问题：{'；'.join(errors)}\n\n" if errors else ""
    reply = (
        f"{prefix}为了继续规划，请补充：{fields}。"
        "也可以同时告诉我预算、兴趣偏好和想要的行程节奏；不填写会按适中节奏估算。"
    )
    return {"messages": [AIMessage(content=reply)], "travel_stage": "collecting"}


def build_research_plan_node(state: TravelState) -> dict:
    request = state["trip_request"]
    destination = request["destination"]
    year = request["start_date"][:4]
    interests = " ".join(request.get("interests") or ["经典热门"])
    level = {
        "economy": "经济型",
        "comfortable": "舒适型",
        "premium": "高端",
        "unspecified": "交通便利",
    }.get(request.get("hotel_level"), "交通便利")
    rooms = request.get("rooms") or (request["travelers"] + 1) // 2
    plans = [
        {
            "id": "attractions-1",
            "purpose": "attractions",
            "query": f"{destination} {interests} 景点 {year} 官方 开放时间 门票",
            "max_results": 8,
        },
        {
            "id": "hotels-1",
            "purpose": "hotels",
            "query": (
                f"{destination} {level} 酒店 {request['start_date']}入住 "
                f"{request['end_date']}退房 {rooms}间 {request['travelers']}人 参考价格"
            ),
            "max_results": 5,
        },
    ]
    return {"research_plan": plans, "travel_stage": "ready", "research_round": 1}


def confirm_research_node(state: TravelState) -> dict:
    plans = state.get("research_plan", [])
    approved = interrupt({
        "type": "web_confirmation",
        "message": (
            f"生成旅游方案需要执行 {len(plans)} 次 Tavily 搜索，并消耗搜索额度；"
            "摘要不足时会读取每类最多 2 个搜索结果页面，是否允许？"
        ),
        "estimated_calls": len(plans),
        "purposes": [
            "搜索热门景点、开放信息和门票参考",
            "搜索酒店候选、住宿区域和参考价格",
        ],
        "tool_calls": [
            {"name": "search_web", "args": {"query": p["query"], "max_results": p["max_results"]}}
            for p in plans
        ],
    })
    return {"research_approved": approved is True}


def route_after_confirmation(state: TravelState) -> str:
    return "approved" if state.get("research_approved") else "rejected"


def reject_research_node(state: TravelState) -> dict:
    warnings = list(state.get("warnings") or [])
    warnings.append({
        "code": "WEB_SEARCH_REJECTED",
        "severity": "warning",
        "stage": "research",
        "message": "你未授权 Tavily 搜索；景点、酒店、开放时间和价格均未联网核实。",
    })
    return {
        "attraction_candidates": [],
        "hotel_candidates": [],
        "research_documents": [],
        "warnings": warnings,
        "travel_stage": "researching",
    }


def execute_research_node(state: TravelState) -> dict:
    documents = []
    warnings = list(state.get("warnings") or [])
    for plan in state.get("research_plan", []):
        try:
            items = tavily_search(plan["query"], plan["max_results"])
        except Exception as exc:
            warnings.append({
                "code": "TAVILY_QUERY_FAILED",
                "severity": "warning",
                "stage": "research",
                "message": f"{plan['purpose']} 搜索失败，方案将使用可用信息继续生成。",
                "retryable": True,
                "details": {"error": str(exc)},
            })
            continue
        documents.extend(
            {
                "id": f"{plan['purpose']}-{len(documents) + index + 1}",
                "purpose": plan["purpose"],
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet") or "",
                "published_at": item.get("published_at"),
            }
            for index, item in enumerate(items)
            if item.get("title") and item.get("url")
        )
    return {
        "research_documents": documents,
        "warnings": warnings,
        "travel_stage": "researching",
    }


def extract_candidates_node(state: TravelState) -> dict:
    request = state["trip_request"]
    documents = []
    invalid_documents = 0
    for item in state.get("research_documents", []):
        try:
            documents.append(SearchDocument.model_validate(item))
        except Exception:
            invalid_documents += 1
    by_purpose = {
        purpose: [document for document in documents if document.purpose == purpose]
        for purpose in ("attractions", "hotels")
    }
    day_count = (
        date.fromisoformat(request["end_date"])
        - date.fromisoformat(request["start_date"])
    ).days + 1
    attraction_minimum = min(
        max(day_count * PACE_LIMITS.get(request.get("pace", "balanced"), 3), 3),
        8,
    )
    attractions, attraction_issues = extract_with_page_enrichment(
        by_purpose["attractions"],
        destination=request["destination"],
        purpose="attractions",
        minimum=attraction_minimum,
    )
    hotels, hotel_issues = extract_with_page_enrichment(
        by_purpose["hotels"],
        destination=request["destination"],
        purpose="hotels",
        minimum=3,
    )
    warnings = list(state.get("warnings") or [])
    if invalid_documents:
        warnings.append({
            "code": "INVALID_RESEARCH_DOCUMENT",
            "severity": "warning",
            "stage": "candidate_extraction",
            "message": f"已忽略 {invalid_documents} 条 URL 或格式无效的搜索资料。",
        })
    for issue in [*attraction_issues, *hotel_issues]:
        warnings.append({
            "code": "CANDIDATE_EXTRACTION_WARNING",
            "severity": "warning",
            "stage": "candidate_extraction",
            "message": issue,
        })
    if not attractions:
        warnings.append({
            "code": "ATTRACTIONS_UNAVAILABLE",
            "severity": "warning",
            "stage": "candidate_extraction",
            "message": "没有抽取到带直接来源证据的具体景点，空缺日期将显示为自由活动。",
        })
    sources_by_url = {}
    for candidate in [*attractions, *hotels]:
        for evidence in candidate.get("evidence", []):
            sources_by_url[evidence["source_url"]] = {
                "title": evidence["source_title"],
                "url": evidence["source_url"],
            }
    return {
        "attraction_candidates": attractions,
        "hotel_candidates": hotels,
        "sources": list(sources_by_url.values()),
        "warnings": warnings,
    }


def weather_node(state: TravelState) -> dict:
    request = state["trip_request"]
    weather = get_weather_forecast(
        request["destination"], request["start_date"], request["end_date"]
    )
    warnings = list(state.get("warnings") or [])
    if weather.get("status") != "available":
        warnings.append({
            "code": f"WEATHER_{weather.get('status', 'failed').upper()}",
            "severity": "warning",
            "stage": "weather",
            "message": weather.get("message") or "未能获取完整天气预报。",
        })
    return {"weather_result": weather, "warnings": warnings}


def compose_plan_node(state: TravelState) -> dict:
    request = state["trip_request"]
    itinerary = build_itinerary(
        request,
        state.get("attraction_candidates", []),
        state.get("weather_result", {}),
    )
    itinerary, budget = optimize_plan_for_budget(
        request,
        itinerary,
        state.get("hotel_candidates", []),
        state.get("attraction_candidates", []),
    )
    alternatives = build_alternatives(
        itinerary, state.get("attraction_candidates", [])
    )
    warnings = list(state.get("warnings") or [])
    warnings.append({
        "code": "ESTIMATED_PRICES",
        "severity": "info",
        "stage": "budget",
        "message": "酒店、门票、餐饮和交通费用是估算区间，不代表实时库存或最终成交价。",
    })
    warnings.append({
        "code": "OPENING_HOURS_REQUIRE_RECHECK",
        "severity": "info",
        "stage": "itinerary",
        "message": "已展示可核实的开放时间原文；闭馆日和预约要求仍需在出发前复核。",
    })
    plan = {
        "request": request,
        "hotels": state.get("hotel_candidates", []),
        "itinerary": itinerary,
        "weather": state.get("weather_result", {}),
        "budget": budget,
        "alternatives": alternatives,
        "warnings": warnings,
        "sources": state.get("sources", []),
    }
    return {
        "messages": [AIMessage(content=render_travel_plan(plan))],
        "itinerary": itinerary,
        "budget": budget,
        "alternatives": alternatives,
        "warnings": warnings,
        "travel_plan": plan,
        "travel_stage": "completed",
    }


def recompose_revision_node(state: TravelState) -> dict:
    """Recalculate an already modified itinerary without rebuilding or searching."""
    request = state["trip_request"]
    itinerary, budget = optimize_plan_for_budget(
        request,
        state.get("itinerary", []),
        state.get("hotel_candidates", []),
        state.get("attraction_candidates", []),
    )
    alternatives = build_alternatives(
        itinerary, state.get("attraction_candidates", [])
    )
    warnings = list(state.get("warnings") or [])
    warnings.append({
        "code": "REVISION_APPLIED",
        "severity": "info",
        "stage": "revision",
        "message": "已在现有核实候选范围内修改行程，并重新计算预算；未执行新的联网搜索。",
    })
    plan = {
        "request": request,
        "hotels": state.get("hotel_candidates", []),
        "itinerary": itinerary,
        "weather": state.get("weather_result", {}),
        "budget": budget,
        "alternatives": alternatives,
        "warnings": warnings,
        "sources": state.get("sources", []),
    }
    return {
        "messages": [AIMessage(content=render_travel_plan(plan))],
        "itinerary": itinerary,
        "budget": budget,
        "alternatives": alternatives,
        "warnings": warnings,
        "travel_plan": plan,
        "revision_patch": {},
        "revision_error": None,
        "travel_stage": "completed",
    }
