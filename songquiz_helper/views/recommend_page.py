"""[노래 추천] 언어별 10곡 추천."""
import pandas as pd
import streamlit as st

import db
import recommend
from config import REC_LANGUAGES, get_secret, lang_label
from normalize import keys_for
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
    tab_rec, tab_hist = st.tabs(["🎲 추천 받기", "📜 추천 기록"])
    with tab_rec:
        _recommend_tab(engine)
    with tab_hist:
        _history_tab(engine)


def _recommend_tab(engine):
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


# ---------------------------------------------------------------- 추천 기록
_STATE_LABEL = {"used": "✅ 활용함", "planned": "📋 활용 예정"}
_NOT_SAVED = "— 미저장"


def _history_rows(engine) -> list[dict]:
    """추천 기록에 '지금 내 목록에 있는지(활용함/활용 예정/미저장)' 상태를 붙인다."""
    status = {s["norm_key"]: s["status"] for s in db.list_songs(engine)}
    rows = db.list_history(engine)
    for h in rows:
        key, swapped = keys_for(h["artist"], h["title"])
        h["state"] = _STATE_LABEL.get(status.get(key) or status.get(swapped), _NOT_SAVED)
    return rows


def _history_tab(engine):
    common.show_flash()
    rows = _history_rows(engine)
    if not rows:
        st.info("아직 추천 기록이 없어요. [추천 받기]를 누르면 추천된 곡이 여기에 자동으로 기록돼요.")
        return
    st.caption(f"지금까지 추천받은 곡 {len(rows)}곡 — 이 기록은 DB에 저장되어 앱을 재시작해도 남고, "
               "여기 있는 곡은 다음 추천에서 다시 나오지 않아요.")
    c1, c2 = st.columns(2)
    lang = c1.selectbox("언어", ["전체"] + REC_LANGUAGES, key="hist_lang",
                        format_func=lambda c: c if c == "전체" else lang_label(c))
    only_unsaved = c2.checkbox("아직 저장 안 한 곡만 보기", key="hist_unsaved")
    if lang != "전체":
        rows = [r for r in rows if r["language"] == lang]
    if only_unsaved:
        rows = [r for r in rows if r["state"] == _NOT_SAVED]
    st.caption(f"{len(rows)}곡 · 표에서 곡을 선택하면 아래에서 저장/유튜브 확인을 할 수 있어요")
    if not rows:
        return

    df = pd.DataFrame({"추천일시": [common.to_local(r["recommended_at"]) for r in rows],
                       "가수": [r["artist"] for r in rows], "제목": [r["title"] for r in rows],
                       "언어": [lang_label(r["language"]) for r in rows],
                       "상태": [r["state"] for r in rows], "이유": [r.get("reason") or "" for r in rows]})
    ev = st.dataframe(df, hide_index=True, on_select="rerun", selection_mode="multi-row", width="stretch",
                      key=f"hist_tbl_{common.ver('history')}_{lang}_{only_unsaved}")
    picked = [rows[i] for i in ev.selection.rows if i < len(rows)]
    if not picked:
        return

    todo = [r for r in picked if r["state"] == _NOT_SAVED]
    if st.button(f"💚 선택한 곡 활용할 노래들에 저장 ({len(todo)}곡)", type="primary", disabled=not todo,
                 help="이미 활용했거나 활용 예정인 곡은 제외해요."):
        added = sum(db.add_song(engine, r["artist"], r["title"], r["language"], "planned")["added"] for r in todo)
        common.flash(f"{added}곡을 활용할 노래들에 저장했어요.")
        common.bump("history")
        common.bump_all()
        st.rerun()
    if len(picked) == 1:
        r = picked[0]
        if r.get("reason"):
            st.caption("추천 이유: " + r["reason"])
        st.markdown(f"**▶ 유튜브 확인: {r['artist']} - {r['title']}**")
        common.render_youtube(engine, r["artist"], r["title"], f"hist_{r['id']}")
    else:
        st.caption("유튜브 확인은 곡을 하나만 선택했을 때 할 수 있어요.")
