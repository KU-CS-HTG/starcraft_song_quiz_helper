"""스타크래프트 노래맞추기 유즈맵 도우미 — 진입점.

실행:  cd songquiz_helper && streamlit run app.py
"""
import streamlit as st

from auth import logout, password_gate

st.set_page_config(page_title="노래맞추기 도우미", page_icon="🎵", layout="wide")


password_gate()

from views import packs, planned, recommend_page, search, used  # noqa: E402  (로그인 후에만 로드)

PAGES = {
    "🔍 노래 검색": search.render,
    "📚 활용한 노래 관리": used.render,
    "🎧 노래 추천": recommend_page.render,
    "📋 활용할 노래들": planned.render,
    "📦 200곡 팩": packs.render,
}

with st.sidebar:
    st.title("🎵 노래맞추기 도우미")
    page = st.radio("메뉴", list(PAGES), label_visibility="collapsed")
    st.divider()
    st.caption("추천 시 취향 근거로 사용")
    st.checkbox("활용한 노래 포함", value=True, key="use_used")
    st.checkbox("활용할 노래들 포함", value=True, key="use_planned")
    st.divider()
    if st.button("로그아웃"):
        logout()

PAGES[page]()
