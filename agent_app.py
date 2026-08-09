import asyncio

import streamlit as st

from app.services.chat_service import chat


def send_message(message: str):
    return asyncio.run(
        chat(
            message,
            thread_id=st.session_state.thread_id,
        )
    )


st.set_page_config(page_title="LangGraph 天气聊天机器人", page_icon="🌦️")
st.title("LangGraph 天气聊天机器人")


if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


for item in st.session_state.chat_history:
    with st.chat_message(item["role"]):
        st.write(item["content"])


if prompt := st.chat_input("问点什么，比如：上海今天会下雨吗？"):
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("查询中..."):
            response = send_message(prompt)
            st.session_state.thread_id = response.thread_id
            st.write(response.reply)
            st.session_state.chat_history.append(
                {"role": "assistant", "content": response.reply}
            )
