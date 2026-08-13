import unittest
from datetime import date, timedelta
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from app.agents.travel.nodes import (
    apply_revision_node,
    build_research_plan_node,
    confirm_research_node,
    reset_travel_state_node,
    route_after_confirmation,
    route_intent_node,
    validate_trip_node,
)
from app.agents.travel.schemas import TripRevision


FUTURE_START = (date.today() + timedelta(days=60)).isoformat()
FUTURE_END = (date.today() + timedelta(days=63)).isoformat()


class TravelNodeTests(unittest.TestCase):
    def test_valid_request_builds_bounded_research_plan(self):
        state = {
            "trip_request": {
                "destination": "上海",
                "start_date": FUTURE_START,
                "end_date": FUTURE_END,
                "travelers": 4,
            }
        }
        validated = validate_trip_node(state)
        plan = build_research_plan_node({"trip_request": validated["trip_request"]})
        self.assertEqual(len(plan["research_plan"]), 2)
        self.assertLessEqual(len(plan["research_plan"]), 3)

    def test_confirmation_rejection_is_preserved(self):
        state = {"research_plan": [{"query": "q", "max_results": 5}]}
        with patch("app.agents.travel.nodes.interrupt", return_value=False):
            result = confirm_research_node(state)
        self.assertFalse(result["research_approved"])
        self.assertEqual(route_after_confirmation(result), "rejected")

    def test_active_travel_workflow_can_be_cancelled(self):
        result = route_intent_node({
            "travel_stage": "collecting",
            "messages": [{"role": "user", "content": "算了，不规划了"}],
        })
        self.assertEqual(result["workflow_agent"], "travel")
        self.assertEqual(result["travel_action"], "travel_cancel")

    def test_broad_non_travel_phrases_do_not_trigger_travel(self):
        for message in (
            "这个游戏怎么玩",
            "帮我规划学习路线",
            "重新规划学习计划",
            "我还有另一个问题",
        ):
            result = route_intent_node({
                "messages": [{"role": "user", "content": message}],
            })
            self.assertEqual(result["travel_action"], "general")

    def test_existing_travel_state_does_not_expand_false_positives(self):
        for stage in ("collecting", "completed"):
            result = route_intent_node({
                "travel_stage": stage,
                "messages": [{"role": "user", "content": "重新规划学习计划"}],
            })
            self.assertEqual(result["travel_action"], "general")

    def test_bare_replan_resets_an_existing_travel_workflow(self):
        result = route_intent_node({
            "travel_stage": "completed",
            "messages": [{"role": "user", "content": "重新规划"}],
        })
        self.assertEqual(result["travel_action"], "travel_new")

    def test_missing_field_answer_continues_active_trip(self):
        result = route_intent_node({
            "travel_stage": "collecting",
            "missing_fields": ["目的地"],
            "messages": [{"role": "user", "content": "上海"}],
        })
        self.assertEqual(result["travel_action"], "travel_continue")

    def test_unrelated_short_message_does_not_fill_destination(self):
        result = route_intent_node({
            "travel_stage": "collecting",
            "missing_fields": ["目的地"],
            "messages": [{"role": "user", "content": "这个游戏怎么玩"}],
        })
        self.assertEqual(result["travel_action"], "general")

    def test_unrelated_budget_question_does_not_revise_trip(self):
        result = route_intent_node({
            "travel_stage": "completed",
            "messages": [{"role": "user", "content": "公司预算怎么控制"}],
        })
        self.assertEqual(result["travel_action"], "general")

    def test_known_activity_change_routes_to_revision(self):
        result = route_intent_node({
            "travel_stage": "completed",
            "itinerary": [{"activities": [{"name": "上海博物馆"}]}],
            "attraction_candidates": [{"name": "世纪公园"}],
            "messages": [{
                "role": "user",
                "content": "把上海博物馆换成世纪公园",
            }],
        })
        self.assertEqual(result["travel_action"], "travel_revision")

    def test_numbered_trip_triggers_new_plan(self):
        result = route_intent_node({
            "messages": [{"role": "user", "content": "上海三日游怎么安排"}],
        })
        self.assertEqual(result["travel_action"], "travel_new")

    def test_explicit_itinerary_phrase_triggers_new_plan(self):
        result = route_intent_node({
            "messages": [{"role": "user", "content": "做一个上海行程规划"}],
        })
        self.assertEqual(result["travel_action"], "travel_new")

    def test_new_plan_reset_clears_plan_scoped_state(self):
        result = reset_travel_state_node({
            "travel_action": "travel_new",
            "trip_request": {"destination": "上海", "travelers": 4},
            "itinerary": [{"day": 1}],
            "warnings": [{"code": "old"}],
        })
        self.assertEqual(result["trip_request"], {})
        self.assertEqual(result["itinerary"], [])
        self.assertEqual(result["warnings"], [])
        self.assertTrue(result["plan_id"])

    def test_revision_replaces_existing_activity_and_updates_budget(self):
        state = {
            "trip_request": {
                "destination": "上海",
                "start_date": FUTURE_START,
                "end_date": FUTURE_END,
                "travelers": 2,
            },
            "itinerary": [{
                "day": 1,
                "area": "黄浦区",
                "activities": [{
                    "period": "上午",
                    "attraction_id": "paid",
                    "name": "收费景点",
                }],
            }],
            "attraction_candidates": [{
                "id": "free",
                "name": "免费公园",
                "area": "黄浦区",
                "ticket_price_min": 0,
                "ticket_price_max": 0,
                "currency": "CNY",
                "evidence": [{"source_url": "https://example.com/park"}],
            }],
            "revision_patch": {
                "request_updates": {"budget_total": 3000},
                "operations": [{
                    "operation": "replace_activity",
                    "day": 1,
                    "target_name": "收费景点",
                    "replacement_name": "免费公园",
                }],
            },
        }
        result = apply_revision_node(state)
        self.assertIsNone(result["revision_error"])
        self.assertEqual(result["trip_request"]["budget_total"], 3000)
        self.assertEqual(
            result["itinerary"][0]["activities"][0]["attraction_id"], "free"
        )

    def test_failed_revision_is_atomic(self):
        original_itinerary = [{
            "day": 1,
            "area": "黄浦区",
            "activities": [{"name": "原景点", "attraction_id": "original"}],
        }]
        state = {
            "trip_request": {
                "destination": "上海",
                "start_date": FUTURE_START,
                "end_date": FUTURE_END,
                "travelers": 2,
            },
            "itinerary": original_itinerary,
            "attraction_candidates": [],
            "revision_patch": {
                "operations": [{
                    "operation": "replace_activity",
                    "day": 1,
                    "target_name": "原景点",
                    "replacement_name": "不存在的景点",
                }],
            },
        }
        result = apply_revision_node(state)
        self.assertIn("当前已核实候选中没有", result["revision_error"])
        self.assertNotIn("itinerary", result)
        self.assertEqual(state["itinerary"], original_itinerary)

    def test_pace_revision_rebuilds_daily_activity_distribution(self):
        candidates = [
            {
                "id": f"a-{index}",
                "name": f"景点{index}",
                "area": "黄浦区",
                "evidence": [],
            }
            for index in range(4)
        ]
        state = {
            "trip_request": {
                "destination": "上海",
                "start_date": FUTURE_START,
                "end_date": FUTURE_END,
                "travelers": 2,
                "pace": "intensive",
            },
            "itinerary": [{
                "day": 1,
                "area": "黄浦区",
                "activities": [
                    {"name": item["name"], "attraction_id": item["id"]}
                    for item in candidates
                ],
            }],
            "attraction_candidates": candidates,
            "weather_result": {"forecast": []},
            "revision_patch": {
                "request_updates": {"pace": "relaxed"},
                "operations": [],
            },
        }

        result = apply_revision_node(state)

        self.assertIsNone(result["revision_error"])
        self.assertEqual(result["trip_request"]["pace"], "relaxed")
        self.assertTrue(
            all(len(day["activities"]) <= 2 for day in result["itinerary"])
        )

    def test_pace_revision_does_not_restore_previously_removed_candidate(self):
        candidates = [
            {"id": "kept", "name": "保留景点", "area": "黄浦区", "evidence": []},
            {"id": "removed", "name": "已删除景点", "area": "黄浦区", "evidence": []},
        ]
        state = {
            "trip_request": {
                "destination": "上海",
                "start_date": FUTURE_START,
                "end_date": FUTURE_END,
                "travelers": 2,
                "pace": "balanced",
            },
            "itinerary": [{
                "day": 1,
                "area": "黄浦区",
                "activities": [{"name": "保留景点", "attraction_id": "kept"}],
            }],
            "attraction_candidates": candidates,
            "weather_result": {"forecast": []},
            "revision_patch": {
                "request_updates": {"pace": "relaxed"},
                "operations": [],
            },
        }

        result = apply_revision_node(state)
        names = [
            activity["name"]
            for day in result["itinerary"] for activity in day["activities"]
        ]
        self.assertEqual(names, ["保留景点"])

    def test_completed_plan_revision_uses_dedicated_graph_branch(self):
        from app.agents.travel.graph import build_travel_graph

        graph = build_travel_graph(checkpointer=MemorySaver())
        state = {
            "messages": [{"role": "user", "content": "第一天把收费景点换成免费公园"}],
            "travel_stage": "completed",
            "trip_request": {
                "destination": "上海",
                "start_date": FUTURE_START,
                "end_date": FUTURE_START,
                "travelers": 2,
                "currency": "CNY",
            },
            "itinerary": [{
                "day": 1,
                "date": FUTURE_START,
                "area": "黄浦区",
                "activities": [{
                    "period": "上午",
                    "attraction_id": "paid",
                    "name": "收费景点",
                    "ticket_price_min": 100,
                    "ticket_price_max": 100,
                    "currency": "CNY",
                }],
            }],
            "attraction_candidates": [{
                "id": "free",
                "name": "免费公园",
                "area": "黄浦区",
                "ticket_price_min": 0,
                "ticket_price_max": 0,
                "currency": "CNY",
                "evidence": [{"source_url": "https://example.com/park"}],
            }],
            "hotel_candidates": [],
            "weather_result": {"forecast": []},
            "warnings": [],
            "sources": [],
        }
        revision = TripRevision.model_validate({
            "operations": [{
                "operation": "replace_activity",
                "day": 1,
                "target_name": "收费景点",
                "replacement_name": "免费公园",
            }],
        })
        with patch(
            "app.agents.travel.nodes.extract_trip_revision", return_value=revision
        ):
            result = graph.invoke(
                state, {"configurable": {"thread_id": "revision-graph-test"}}
            )
        self.assertEqual(result["travel_stage"], "completed")
        self.assertEqual(
            result["itinerary"][0]["activities"][0]["attraction_id"], "free"
        )
        self.assertEqual(result["travel_action"], "travel_revision")


if __name__ == "__main__":
    unittest.main()
