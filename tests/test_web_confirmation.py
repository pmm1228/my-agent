import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, ToolMessage

from app.graph.web_confirmation import tools_with_web_confirmation


class WebConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_web_call_is_not_executed(self):
        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_web",
                            "args": {"query": "最新新闻"},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }
        with (
            patch("app.graph.web_confirmation.interrupt", return_value=False) as ask,
            patch("app.graph.web_confirmation.tool_node.ainvoke", new=AsyncMock()) as invoke,
        ):
            result = await tools_with_web_confirmation(state, {})

        ask.assert_called_once()
        invoke.assert_not_awaited()
        self.assertIsInstance(result["messages"][0], ToolMessage)
        self.assertIn("拒绝", result["messages"][0].content)

    async def test_approved_web_call_is_executed(self):
        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "fetch_webpage",
                            "args": {"url": "https://example.com"},
                            "id": "call-2",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }
        expected = {"messages": []}
        with (
            patch("app.graph.web_confirmation.interrupt", return_value=True),
            patch(
                "app.graph.web_confirmation.tool_node.ainvoke",
                new=AsyncMock(return_value=expected),
            ) as invoke,
        ):
            result = await tools_with_web_confirmation(state, {})

        invoke.assert_awaited_once()
        self.assertIs(result, expected)

    async def test_fetch_webpage_does_not_require_confirmation(self):
        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "fetch_webpage",
                            "args": {"url": "https://example.com"},
                            "id": "call-3",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }
        expected = {"messages": []}
        with (
            patch("app.graph.web_confirmation.interrupt") as ask,
            patch(
                "app.graph.web_confirmation.tool_node.ainvoke",
                new=AsyncMock(return_value=expected),
            ) as invoke,
        ):
            result = await tools_with_web_confirmation(state, {})

        ask.assert_not_called()
        invoke.assert_awaited_once()
        self.assertIs(result, expected)


if __name__ == "__main__":
    unittest.main()
