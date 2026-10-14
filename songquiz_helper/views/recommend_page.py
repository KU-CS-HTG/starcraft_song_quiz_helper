"""[노래 추천] 언어별 10곡 추천."""
import streamlit as st

import db
import recommend
from config import REC_LANGUAGES, get_secret, lang_label
from views import common


def _taste_songs(engine) -> list[dict]:
    """사이드바 체크박스에 따라 취향 근거 목록을 만든다."""
    out = []
    if st.session_state.get("use_used", True):
        out += db.list_songs(engine, status="used")
    if st.session_state.get("use_planned", True):
        out += db.list_songs(engine, status="planned")
    return out


def _request(engine, lang: str, api_key: str):
    songs = db.list_songs(engine)
    excluded = songs + db.list_history(engine)  # 제외는 체크박스와 무관하게 항상 전체
    taste = _taste_songs(engine)
    try:
        res = recommend.recommend_songs(lang, taste, excluded, recommend.make_claude_ask(api_key))
    except ValueError as e:
        st.error(str(e))
        return
    except Exception as e:  # anthropic 인증/한도/네트워크 오류
        st.error(f"Claude API 호출에 실패했어요 ({type(e).__name__}). API 키·잔액·모델명을 확인해 주세요.")
        return
    items = res["items"]
    db.add_history(engine, items)  # 보여준 곡은 모두 기록 → 다음엔 절대 반복되지 않음
    for it in items:
        it["saved"], it["check"] = False, False
    st.session_state["rec_items"] = items
    st.session_state["rec_batch"] = st.session_state.get("rec_batch", 0) + 1
    st.session_state["rec_info"] = res


def render():
    st.header("🎧 노래 추천")
    engine = common.need_engine()
    api_key = get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        st.info("ANTHROPIC_API_KEY 가 설정되지 않아 추천 기능을 쓸 수 없어요. (README 참고)")

    lang = st.radio("언어", REC_LANGUAGES, horizontal=True, format_func=lang_label)
    taste_n = 0
    if api_key:
        taste_n = len(_taste_songs(engine))
        st.caption(f"취향 근거: 현재 {taste_n}곡 (사이드바 체크박스로 조절) · 모델: {recommend.CLAUDE_MODEL}")
    if st.button("🎲 추천 받기", type="primary", disabled=not api_key):
        with st.spinner("Claude 가 취향을 분석하는 중…"):
            _request(engine, lang, api_key)

    items = st.session_state.get("rec_items")
    if not items:
        return
    info = st.session_state.get("rec_info", {})
    st.caption(f"{len(items)}곡 추천됨 · 중복으로 걸러낸 곡 {info.get('filtered', 0)}개 · 요청 {info.get('attempts', 1)}회"
               " · 새로 추천받으면 이 목록은 사라지지만 추천 기록은 남아 다시 나오지 않아요.")
    if info.get("shortfall"):
        st.warning(f"중복을 걸러내느라 {info['shortfall']}곡이 모자라요. 한 번 더 눌러 보세요.")

    batch = st.session_state.get("rec_batch", 0)
    for i, it in enumerate(items):
        with st.container(border=True):
            st.markdown(f"**{it['artist']} - {it['title']}**")
            if it.get("reason"):
                st.caption(it["reason"])
            c1, c2 = st.columns(2)
            if it["saved"]:
                c1.success("✅ 저장됨")
            elif c1.button("💚 마음에 들어요 → 저장", key=f"rec_save_{batch}_{i}"):
                r = db.add_song(engine, it["artist"], it["title"], it["language"], "planned")
                if r["added"]:
                    it["saved"] = True
                    common.bump("planned")
                    st.rerun()
                else:
                    ex = r["existing"]
                    st.warning("이미 목록에 있는 곡이에요" + (f": {ex['artist']} - {ex['title']}" if ex else "."))
            label = "▲ 유튜브 닫기" if it["check"] else "▶ 유튜브 확인"
            if c2.button(label, key=f"rec_yt_{batch}_{i}"):
                it["check"] = not it["check"]
                st.rerun()
            if it["check"]:
                common.render_youtube(engine, it["artist"], it["title"], f"rec_{batch}_{i}")
