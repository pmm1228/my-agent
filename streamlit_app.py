import asyncio

import streamlit as st

from app.services.chat_service import chat, close_resources, confirm_web_access


def _run_chat(message: str):
    async def _chat():
        try:
            return await chat(message, thread_id=st.session_state.thread_id)
        finally:
            await close_resources()

    return asyncio.run(_chat())


def _confirm_web(approved: bool):
    async def _confirm():
        try:
            return await confirm_web_access(
                thread_id=st.session_state.thread_id,
                approved=approved,
            )
        finally:
            await close_resources()

    return asyncio.run(_confirm())


st.set_page_config(page_title="My-Agent", page_icon="🌦️")
st.title("My-Agent")


if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_web_confirmation" not in st.session_state:
    st.session_state.pending_web_confirmation = None


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])


if st.session_state.pending_web_confirmation:
    confirmation = st.session_state.pending_web_confirmation
    st.warning(confirmation.get("message", "Agent 请求调用 Tavily，并将消耗搜索额度，是否允许？"))
    st.json(confirmation.get("tool_calls", []))
    allow_col, deny_col = st.columns(2)
    decision = None
    if allow_col.button("允许联网", type="primary"):
        decision = True
    if deny_col.button("拒绝联网"):
        decision = False
    if decision is not None:
        with st.spinner("继续处理中..."):
            response = _confirm_web(decision)
        st.session_state.pending_web_confirmation = response.confirmation
        if response.reply:
            st.session_state.messages.append(
                {"role": "assistant", "content": response.reply}
            )
        st.rerun()


if prompt := st.chat_input("问点什么，比如：上海今天会下雨吗？"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            response = _run_chat(prompt)
            st.session_state.thread_id = response.thread_id
            if response.status == "requires_confirmation":
                st.session_state.pending_web_confirmation = response.confirmation
                st.info("调用 Tavily 搜索并消耗额度前，需要你确认。")
            else:
                st.write(response.reply)
                st.session_state.messages.append(
                    {"role": "assistant", "content": response.reply}
                )
