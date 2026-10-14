"""스타크래프트 노래맞추기 유즈맵 도우미 — 진입점.

실행:  cd songquiz_helper && streamlit run app.py
"""
import hmac

import streamlit as st

from config import get_secret

st.set_page_config(page_title="노래맞추기 도우미", page_icon="🎵", layout="wide")


def password_gate() -> None:
    """APP_PASSWORD 가 맞아야 진입. 내 API 키가 쓰이므로 비밀번호가 없으면 아예 막는다."""
    if st.session_state.get("authed"):
        return
    expected = get_secret("APP_PASSWORD")
    st.title("🎵 노래맞추기 도우미")
    if not expected:
        st.error("APP_PASSWORD 가 설정되지 않아 접속을 막았어요. Secrets 에 APP_PASSWORD 를 넣어 주세요.")
        st.stop()
    with st.form("login"):
        pw = st.text_input("비밀번호", type="password")
        ok = st.form_submit_button("입장", type="primary")
    if ok:
        if hmac.compare_digest(pw.encode(), expected.encode()):
            st.session_state["authed"] = True
            st.rerun()
        st.error("비밀번호가 틀렸어요.")
    st.stop()


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
        st.session_state.clear()
        st.rerun()

PAGES[page]()
