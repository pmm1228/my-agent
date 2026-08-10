import asyncio

import streamlit as st

from app.services.chat_service import chat, close_resources


def _run_chat(message: str):
    async def _chat():
        try:
            return await chat(message, thread_id=st.session_state.thread_id)
        finally:
            await close_resources()

    return asyncio.run(_chat())


st.set_page_config(page_title="My-Agent", page_icon="🌦️")
st.title("My-Agent")


if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])


if prompt := st.chat_input("问点什么，比如：上海今天会下雨吗？"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            response = _run_chat(prompt)
            st.session_state.thread_id = response.thread_id
            st.write(response.reply)
            st.session_state.messages.append(
                {"role": "assistant", "content": response.reply}
            )
