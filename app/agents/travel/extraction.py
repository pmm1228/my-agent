import json
import re
from datetime import date

from app.core.llm import get_llm
from app.agents.travel.schemas import TripRevision


EXTRACTION_PROMPT = """你是旅游需求字段提取器。当前日期是 {today}。
已有需求：{existing}
用户最新消息：{message}

只输出 JSON，不要解释。输出格式：
{{"updates": {{...}}, "explicit_fields": ["..."]}}
只写用户本轮明确给出或明确修改的字段。允许字段：destination、start_date、end_date、
travelers、origin、budget_total、budget_scope、currency、rooms、interests、pace、hotel_level、
preferred_areas、transport_preferences、special_needs。
日期使用 YYYY-MM-DD；金额只输出整数；pace 使用 relaxed/balanced/intensive；
hotel_level 使用 economy/comfortable/premium/unspecified。无法确定的字段不要输出。
budget_scope 使用 local_only 或 including_round_trip；currency 必须使用三位 ISO 代码，
例如人民币输出 CNY、美元输出 USD、欧元输出 EUR、日元输出 JPY。
"""


REVISION_PROMPT = """你是已有旅行方案的修改指令提取器。
当前旅行需求：{request}
当前每日行程：{itinerary}
当前可用景点候选名称：{candidate_names}
用户最新消息：{message}

只输出 JSON，不要解释：
{{
  "request_updates": {{}},
  "operations": [
    {{
      "operation": "replace_activity|remove_activity|add_activity",
      "day": 1,
      "target_name": null,
      "replacement_name": null
    }}
  ]
}}

规则：
1. request_updates 仅允许 budget_total、travelers、rooms、pace、hotel_level。
2. replace_activity 必须有 target_name 和 replacement_name；remove_activity 必须有
   target_name；add_activity 必须有 replacement_name。
3. 活动名称必须使用当前行程或候选中已有的完整名称，不得创造候选。
4. 没有明确修改时返回空对象和空列表。
"""


def _json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("模型未返回 JSON 对象")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("模型返回内容不是对象")
    return value


def extract_trip_patch(message: str, existing: dict) -> dict:
    response = get_llm().invoke(
        EXTRACTION_PROMPT.format(
            today=date.today().isoformat(),
            existing=json.dumps(existing, ensure_ascii=False),
            message=message,
        )
    )
    payload = _json_object(str(response.content))
    updates = payload.get("updates") or {}
    explicit = payload.get("explicit_fields") or []
    if not isinstance(updates, dict) or not isinstance(explicit, list):
        raise ValueError("字段提取结果格式错误")
    allowed = {
        "destination", "start_date", "end_date", "travelers", "origin",
        "budget_total", "budget_scope", "currency", "rooms", "interests", "pace",
        "hotel_level", "preferred_areas", "transport_preferences", "special_needs",
    }
    return {key: updates[key] for key in explicit if key in allowed and key in updates}


def extract_trip_revision(
    message: str,
    request: dict,
    itinerary: list[dict],
    candidates: list[dict],
) -> TripRevision:
    response = get_llm().invoke(
        REVISION_PROMPT.format(
            request=json.dumps(request, ensure_ascii=False),
            itinerary=json.dumps(itinerary, ensure_ascii=False),
            candidate_names=json.dumps(
                [item.get("name") for item in candidates if item.get("name")],
                ensure_ascii=False,
            ),
            message=message,
        )
    )
    return TripRevision.model_validate(_json_object(str(response.content)))
