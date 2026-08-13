import re

from app.agents.contracts import RootState, RouteDecision
from app.agents.travel.nodes import (
    REVISION_PATTERNS,
    is_bare_new_plan_request,
    route_intent_node,
)


COMPLETED_TRAVEL_EDIT_SIGNALS = ("换成", "替换", "删除", "删掉", "增加", "加到", "调整")


def route_travel_request(state: RootState) -> RouteDecision:
    """Score travel intent using explicit, testable evidence."""
    owns_workflow = state.get("workflow_agent") == "travel"
    workflow_status = state.get("workflow_status")
    if owns_workflow and workflow_status == "active":
        return RouteDecision(
            agent="travel",
            matched=True,
            score=100,
            reason="继续当前活跃的旅行工作流",
            kind="continuation",
        )
    decision = route_intent_node(state)
    action = decision.get("travel_action")
    if action != "general":
        scores = {
            "travel_cancel": 100,
            "travel_continue": 100,
            "travel_revision": 90,
            "travel_new": 90,
        }
        return RouteDecision(
            agent="travel",
            matched=True,
            score=scores.get(action, 80),
            reason=f"识别到旅行意图：{action}",
        )
    if not owns_workflow or workflow_status != "completed":
        return RouteDecision(
            agent="travel",
            matched=False,
            score=0,
            reason="未发现明确旅行意图",
        )

    text = ""
    for message in reversed(state.get("messages", [])):
        if getattr(message, "type", None) in {"human", "user"}:
            text = str(getattr(message, "content", ""))
            break
        if isinstance(message, dict) and message.get("role") == "user":
            text = str(message.get("content", ""))
            break
    if is_bare_new_plan_request(text):
        return RouteDecision(
            agent="travel",
            matched=True,
            score=90,
            reason="明确要求重新规划已有旅行",
        )
    has_edit = any(signal in text for signal in COMPLETED_TRAVEL_EDIT_SIGNALS)
    normalized_text = re.sub(r"[\s·•\-—_（）()【】\[\]]+", "", text).lower()
    mentions_known_item = any(
        hint and re.sub(r"[\s·•\-—_（）()【】\[\]]+", "", hint).lower() in normalized_text
        for hint in state.get("workflow_route_hints", [])
    )
    day_edit = bool(
        re.search(r"第[一二三四五六七八九十两\d]+天", text) and has_edit
    )
    is_revision = (
        any(re.search(pattern, text) for pattern in REVISION_PATTERNS)
        or (has_edit and mentions_known_item)
        or day_edit
    )
    return RouteDecision(
        agent="travel",
        matched=is_revision,
        score=80 if is_revision else 0,
        reason="修改已完成旅行方案" if is_revision else "未发现旅行方案修改意图",
    )
