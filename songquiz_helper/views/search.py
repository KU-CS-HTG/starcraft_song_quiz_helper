"""[노래 검색] 중복 확인 + 유튜브 링크."""
import streamlit as st

from normalize import parse_line
from views import common


def render():
    st.header("🔍 노래 검색")
    engine = common.need_engine()

    with st.form("search_form"):
        q = st.text_input("가수 - 제목 (또는 아무 검색어)", placeholder="예: BTS - Dynamite  또는  BTS: Dynamite")
        submitted = st.form_submit_button("검색", type="primary")
    if submitted and q.strip():
        artist, title = parse_line(q)
        st.session_state["search_state"] = {"raw": q.strip(), "artist": artist, "title": title}

    state = st.session_state.get("search_state")
    if not state:
        st.caption("곡을 입력하면 이미 활용한 곡인지 확인하고, 유튜브 링크를 찾아줘요.")
        return

    artist, title = state["artist"], state["title"]
    st.subheader(f"{artist + ' - ' if artist else ''}{title}")
    common.render_duplicate(common.check_duplicate(engine, artist, title))
    st.divider()
    common.render_youtube(engine, artist, title, "search")
