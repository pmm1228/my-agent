import unittest
from unittest.mock import patch

from app.agents.contracts import AgentSpec, RouteDecision
from app.agents.supervisor.nodes import supervisor_node


def _spec(name: str, score: int, priority: int) -> AgentSpec:
    return AgentSpec(
        name=name,
        description=name,
        graph_factory=lambda: None,
        router=lambda _state: RouteDecision(
            agent=name,
            matched=True,
            score=score,
            reason=f"{name} matched",
        ),
        priority=priority,
    )


class SupervisorRoutingTests(unittest.TestCase):
    def test_score_wins_before_priority(self):
        specs = {
            "general": AgentSpec("general", "general", lambda: None),
            "alpha": _spec("alpha", 80, 100),
            "beta": _spec("beta", 90, 0),
        }
        with patch("app.agents.supervisor.nodes.AGENT_SPECS", specs):
            result = supervisor_node({"messages": []})

        self.assertEqual(result["route"], "beta")
        self.assertEqual(result["route_decision"]["score"], 90)

    def test_priority_breaks_equal_score(self):
        specs = {
            "general": AgentSpec("general", "general", lambda: None),
            "alpha": _spec("alpha", 80, 100),
            "beta": _spec("beta", 80, 50),
        }
        with patch("app.agents.supervisor.nodes.AGENT_SPECS", specs):
            result = supervisor_node({"messages": []})

        self.assertEqual(result["route"], "alpha")

    def test_exact_tie_falls_back_to_general(self):
        specs = {
            "general": AgentSpec("general", "general", lambda: None),
            "alpha": _spec("alpha", 80, 100),
            "beta": _spec("beta", 80, 100),
        }
        with patch("app.agents.supervisor.nodes.AGENT_SPECS", specs):
            result = supervisor_node({"messages": []})

        self.assertEqual(result["route"], "general")
        self.assertTrue(result["route_decision"]["ambiguous"])

    def test_low_score_falls_back_to_general(self):
        specs = {
            "general": AgentSpec("general", "general", lambda: None),
            "alpha": _spec("alpha", 50, 100),
        }
        with patch("app.agents.supervisor.nodes.AGENT_SPECS", specs):
            result = supervisor_node({"messages": []})

        self.assertEqual(result["route"], "general")

    def test_broken_domain_router_does_not_break_general_chat(self):
        def broken_router(_state):
            raise RuntimeError("broken")

        specs = {
            "general": AgentSpec("general", "general", lambda: None),
            "broken": AgentSpec(
                "broken",
                "broken",
                lambda: None,
                router=broken_router,
                priority=100,
            ),
        }
        with patch("app.agents.supervisor.nodes.AGENT_SPECS", specs):
            result = supervisor_node({"messages": []})

        self.assertEqual(result["route"], "general")
        self.assertEqual(
            result["route_decision"]["candidates"][0]["error_type"],
            "RuntimeError",
        )

    def test_route_score_must_be_bounded(self):
        with self.assertRaises(ValueError):
            RouteDecision("travel", True, 101, "invalid")

    def test_explicit_agent_beats_active_workflow_continuation(self):
        specs = {
            "general": AgentSpec("general", "general", lambda: None),
            "travel": AgentSpec(
                "travel",
                "travel",
                lambda: None,
                router=lambda _state: RouteDecision(
                    "travel",
                    True,
                    100,
                    "active workflow",
                    kind="continuation",
                ),
                priority=100,
            ),
            "analytics": _spec("analytics", 90, 100),
        }
        with patch("app.agents.supervisor.nodes.AGENT_SPECS", specs):
            result = supervisor_node({"messages": []})

        self.assertEqual(result["route"], "analytics")

    def test_continuation_is_used_without_explicit_domain_match(self):
        specs = {
            "general": AgentSpec("general", "general", lambda: None),
            "travel": AgentSpec(
                "travel",
                "travel",
                lambda: None,
                router=lambda _state: RouteDecision(
                    "travel",
                    True,
                    100,
                    "active workflow",
                    kind="continuation",
                ),
                priority=100,
            ),
        }
        with patch("app.agents.supervisor.nodes.AGENT_SPECS", specs):
            result = supervisor_node({"messages": []})

        self.assertEqual(result["route"], "travel")

    def test_completed_travel_does_not_capture_generic_edit_request(self):
        from app.agents.travel.routing import route_travel_request

        decision = route_travel_request({
            "workflow_agent": "travel",
            "workflow_status": "completed",
            "workflow_route_hints": ["上海博物馆"],
            "messages": [{"role": "user", "content": "删除数据库里的测试数据"}],
        })
        self.assertFalse(decision.matched)

    def test_completed_travel_routes_edit_of_known_candidate(self):
        from app.agents.travel.routing import route_travel_request

        decision = route_travel_request({
            "workflow_agent": "travel",
            "workflow_status": "completed",
            "workflow_route_hints": ["上海博物馆", "世纪公园"],
            "messages": [{"role": "user", "content": "把上海博物馆换成世纪公园"}],
        })
        self.assertTrue(decision.matched)
        self.assertEqual(decision.agent, "travel")

    def test_completed_travel_accepts_bare_replan_command(self):
        from app.agents.travel.routing import route_travel_request

        decision = route_travel_request({
            "workflow_agent": "travel",
            "workflow_status": "completed",
            "messages": [{"role": "user", "content": "重新规划"}],
        })
        self.assertTrue(decision.matched)
        self.assertEqual(decision.reason, "明确要求重新规划已有旅行")


if __name__ == "__main__":
    unittest.main()
