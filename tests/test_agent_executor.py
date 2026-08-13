import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import MemorySaver

from app.agents.contracts import AgentSpec, RouteDecision
from app.agents.executor import (
    AGENT_EXECUTOR_ERROR_KEY,
    agent_executor_node,
    agent_failure_fallback,
    collect_agent_result_node,
)
from app.agents.supervisor.nodes import main_agent_node, synthesize_agent_results


class AgentExecutorTests(unittest.TestCase):
    def test_executor_consumes_registered_agent_call(self):
        result = agent_executor_node({
            "pending_agent_call": {
                "call_id": "call-1",
                "agent": "travel",
                "task": "规划上海旅行",
                "context": {},
            }
        })

        self.assertEqual(result["next_action"], "travel")
        self.assertEqual(result["active_agent"], "travel")
        self.assertEqual(result["agent_status"], "running")

    def test_executor_rejects_unknown_agent(self):
        result = agent_executor_node({
            "pending_agent_call": {
                "call_id": "call-2",
                "agent": "missing",
                "task": "unknown",
                "context": {},
            }
        })

        self.assertEqual(result["next_action"], "invalid")
        self.assertEqual(result["agent_result"]["status"], "failed")
        self.assertEqual(
            result["agent_result"]["errors"][0]["code"],
            "UNKNOWN_AGENT",
        )

    def test_child_exception_becomes_failed_agent_result(self):
        result = agent_failure_fallback({
            "pending_agent_call": {
                "call_id": "call-3",
                "agent": "travel",
                "task": "规划上海旅行",
                "context": {},
            },
            AGENT_EXECUTOR_ERROR_KEY: RuntimeError("broken child"),
        })

        self.assertEqual(result["agent_result"]["status"], "failed")
        self.assertEqual(
            result["agent_result"]["errors"][0]["code"],
            "AGENT_EXECUTION_FAILED",
        )
        self.assertEqual(result["execution_error"]["type"], "RuntimeError")

    def test_collector_attaches_call_id_and_returns_to_synthesis(self):
        result = collect_agent_result_node({
            "pending_agent_call": {
                "call_id": "call-4",
                "agent": "travel",
                "task": "规划上海旅行",
                "context": {},
            },
            "agent_result": {
                "agent": "travel",
                "status": "completed",
                "summary": "旅行方案",
                "data": {"budget": 3000},
                "warnings": [],
                "errors": [],
            },
            "agent_results": [],
        })

        self.assertEqual(result["orchestration_phase"], "synthesizing")
        self.assertEqual(result["agent_results"][0]["call_id"], "call-4")

    def test_synthesis_receives_data_warnings_and_errors(self):
        class FakeModel:
            def __init__(self):
                self.messages = None

            def invoke(self, messages):
                self.messages = messages
                return AIMessage(content="已综合结果")

        model = FakeModel()
        state = {
            "messages": [{"role": "user", "content": "给我最终方案"}],
            "agent_results": [{
                "agent": "travel",
                "status": "completed",
                "summary": "上海三日方案",
                "data": {"budget": 3000},
                "warnings": [{"message": "酒店价格未实时核实"}],
                "errors": [{"message": "缺少返程航班价格"}],
            }],
        }

        with patch("app.agents.supervisor.nodes.get_llm", return_value=model):
            response = synthesize_agent_results(state)

        prompt = model.messages[-1].content
        self.assertEqual(response.content, "已综合结果")
        self.assertIn("3000", prompt)
        self.assertIn("酒店价格未实时核实", prompt)
        self.assertIn("缺少返程航班价格", prompt)

    def test_synthesis_failure_uses_structured_fallback(self):
        state = {
            "messages": [{"role": "user", "content": "给我最终方案"}],
            "orchestration_phase": "synthesizing",
            "pending_agent_call": {
                "call_id": "call-5",
                "agent": "travel",
                "task": "给我最终方案",
                "context": {},
            },
            "agent_results": [{
                "agent": "travel",
                "status": "failed",
                "summary": "只能提供部分方案",
                "data": {},
                "warnings": [{"message": "价格未核实"}],
                "errors": [{"message": "搜索服务不可用"}],
            }],
        }

        with patch(
            "app.agents.supervisor.nodes.synthesize_agent_results",
            side_effect=RuntimeError("model unavailable"),
        ):
            result = main_agent_node(state)

        content = result["messages"][-1].content
        self.assertIn("只能提供部分方案", content)
        self.assertIn("价格未核实", content)
        self.assertIn("搜索服务不可用", content)
        self.assertEqual(result["orchestration_phase"], "done")
        self.assertIsNone(result["pending_agent_call"])

    def test_root_graph_recovers_from_child_exception(self):
        with patch(
            "app.core.checkpointer.get_checkpointer", return_value=MemorySaver()
        ):
            from app.graph.builder import build_graph

        def broken_agent(_state):
            raise RuntimeError("broken child")

        def fake_synthesis(state):
            return AIMessage(
                content=state["agent_results"][-1]["summary"],
                name="main_agent",
            )

        specs = {
            "general": AgentSpec("general", "general", lambda: None),
            "broken": AgentSpec(
                "broken",
                "broken",
                lambda: None,
                router=lambda _state: RouteDecision(
                    "broken", True, 100, "explicit broken test"
                ),
                priority=100,
            ),
        }
        with (
            patch("app.graph.builder.build_registered_agents", return_value={
                "broken": RunnableLambda(broken_agent),
            }),
            patch("app.agents.supervisor.nodes.AGENT_SPECS", specs),
            patch("app.agents.executor.AGENT_SPECS", specs),
            patch(
                "app.agents.supervisor.nodes.synthesize_agent_results",
                side_effect=fake_synthesis,
            ),
        ):
            graph = build_graph(checkpointer=MemorySaver())
            result = graph.invoke(
                {"messages": [{"role": "user", "content": "触发失败 Agent"}]},
                {"configurable": {"thread_id": "broken-agent"}},
            )

        self.assertEqual(result["agent_result"]["status"], "failed")
        self.assertEqual(
            result["agent_result"]["errors"][0]["code"],
            "AGENT_EXECUTION_FAILED",
        )
        self.assertEqual(result["messages"][-1].name, "main_agent")


if __name__ == "__main__":
    unittest.main()
