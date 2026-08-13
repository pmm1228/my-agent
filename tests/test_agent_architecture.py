import unittest
from typing import get_type_hints
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command


class AgentArchitectureTests(unittest.TestCase):
    def setUp(self):
        def fake_synthesis(state):
            results = state.get("agent_results") or [state.get("agent_result") or {}]
            return AIMessage(
                content=results[-1].get("summary", ""),
                name="main_agent",
            )

        synthesis_patch = patch(
            "app.agents.supervisor.nodes.synthesize_agent_results",
            side_effect=fake_synthesis,
        )
        synthesis_patch.start()
        self.addCleanup(synthesis_patch.stop)

    @staticmethod
    def _build_root_graph():
        with patch(
            "app.core.checkpointer.get_checkpointer", return_value=MemorySaver()
        ):
            from app.graph.builder import build_graph
        return build_graph(checkpointer=MemorySaver())

    def test_travel_private_state_survives_parent_invocations(self):
        graph = self._build_root_graph()
        config = {"configurable": {"thread_id": "travel-private-state"}}
        with patch(
            "app.agents.travel.nodes.extract_trip_patch",
            side_effect=[{"destination": "上海"}, {"travelers": 2}],
        ):
            first = graph.invoke(
                {"messages": [{"role": "user", "content": "做一个上海旅行规划"}]},
                config,
            )
            second = graph.invoke(
                {"messages": [{"role": "user", "content": "2个人"}]},
                config,
            )

        self.assertEqual(first["workflow_agent"], "travel")
        self.assertEqual(first["workflow_status"], "active")
        self.assertEqual(first["state_schema_version"], 4)
        self.assertEqual(first["orchestration_phase"], "done")
        self.assertIsNone(first["pending_agent_call"])
        self.assertEqual(first["messages"][-1].name, "main_agent")
        self.assertEqual(first["route_decision"]["agent"], "travel")
        self.assertEqual(first["agent_result"]["agent"], "travel")
        self.assertEqual(first["agent_result"]["status"], "active")
        self.assertNotIn("trip_request", first["agent_result"]["data"])
        self.assertEqual(second["workflow_status"], "active")
        self.assertNotIn("trip_request", second)
        reply = second["messages"][-1].content
        self.assertIn("出发日期", reply)
        self.assertIn("返程日期", reply)
        self.assertNotIn("目的地、", reply)

    def test_root_graph_loops_from_child_back_to_main_agent(self):
        graph = self._build_root_graph().get_graph()
        nodes = set(graph.nodes)
        edges = {(edge.source, edge.target) for edge in graph.edges}

        self.assertIn("main_agent", nodes)
        self.assertIn("agent_executor", nodes)
        self.assertIn("collect_agent_result", nodes)
        self.assertIn("travel_agent", nodes)
        self.assertNotIn("general_agent", nodes)
        self.assertIn(("__start__", "main_agent"), edges)
        self.assertIn(("main_agent", "agent_executor"), edges)
        self.assertIn(("agent_executor", "travel_agent"), edges)
        self.assertIn(("travel_agent", "collect_agent_result"), edges)
        self.assertIn(("collect_agent_result", "main_agent"), edges)

    def test_agent_registry_and_state_boundaries_are_explicit(self):
        from app.agents.contracts import RootState
        from app.agents.registry import AGENT_SPECS
        from app.agents.travel.state import TravelState
        from app.graph.router import list_domains

        self.assertEqual(set(AGENT_SPECS), {"general", "travel"})
        self.assertEqual(set(list_domains()), {"general", "travel"})
        root_fields = get_type_hints(RootState, include_extras=True)
        travel_fields = get_type_hints(TravelState, include_extras=True)
        self.assertIn("workflow_agent", root_fields)
        self.assertIn("workflow_status", root_fields)
        self.assertNotIn("trip_request", root_fields)
        self.assertNotIn("travel_stage", root_fields)
        self.assertNotIn("travel_action", root_fields)
        self.assertIn("trip_request", travel_fields)
        self.assertIn("travel_stage", travel_fields)

    def test_nested_travel_confirmation_resumes_through_root(self):
        graph = self._build_root_graph()
        config = {"configurable": {"thread_id": "travel-nested-confirmation"}}
        request = {
            "destination": "上海",
            "start_date": "2099-10-02",
            "end_date": "2099-10-04",
            "travelers": 2,
        }
        weather = {
            "status": "out_of_range",
            "forecast": [],
            "message": "旅行日期超出可靠预报范围。",
        }
        with (
            patch("app.agents.travel.nodes.extract_trip_patch", return_value=request),
            patch("app.agents.travel.nodes.get_weather_forecast", return_value=weather),
        ):
            graph.invoke(
                {"messages": [{"role": "user", "content": "上海三日游怎么安排"}]},
                config,
            )
            snapshot = graph.get_state(config)
            self.assertTrue(snapshot.interrupts)
            self.assertEqual(snapshot.interrupts[0].value["type"], "web_confirmation")
            result = graph.invoke(Command(resume=False), config)

        self.assertFalse(graph.get_state(config).interrupts)
        self.assertEqual(result["workflow_status"], "completed")
        self.assertEqual(result["agent_result"]["agent"], "travel")
        self.assertEqual(result["agent_result"]["status"], "completed")
        self.assertEqual(result["messages"][-1].name, "main_agent")
        self.assertNotIn("travel_stage", result)
        self.assertNotIn("trip_request", result)
        self.assertIn("上海旅行方案", result["messages"][-1].content)

    def test_unrelated_turn_handoffs_to_general_without_losing_trip(self):
        def fake_chatbot(_):
            return {"messages": [AIMessage(content="这是普通问题的回答。")]}

        graph = self._build_root_graph()
        config = {"configurable": {"thread_id": "travel-general-handoff"}}
        with (
            patch("app.agents.supervisor.nodes.chatbot", fake_chatbot),
            patch(
                "app.agents.travel.nodes.extract_trip_patch",
                side_effect=[{"destination": "上海"}, {"travelers": 2}],
            ),
        ):
            graph.invoke(
                {"messages": [{"role": "user", "content": "做一个上海旅行规划"}]},
                config,
            )
            general = graph.invoke(
                {"messages": [{"role": "user", "content": "这个游戏怎么玩"}]},
                config,
            )
            resumed = graph.invoke(
                {"messages": [{"role": "user", "content": "2个人"}]},
                config,
            )

        self.assertEqual(general["messages"][-1].content, "这是普通问题的回答。")
        self.assertEqual(general["last_agent"], "general")
        self.assertEqual(general["agent_result"]["agent"], "general")
        self.assertEqual(general["agent_result"]["summary"], "这是普通问题的回答。")
        self.assertEqual(general["workflow_agent"], "travel")
        self.assertEqual(general["workflow_status"], "active")
        self.assertEqual(general["messages"][-1].name, "main_agent")
        self.assertIn("出发日期", resumed["messages"][-1].content)
        self.assertNotIn("目的地、", resumed["messages"][-1].content)


if __name__ == "__main__":
    unittest.main()
