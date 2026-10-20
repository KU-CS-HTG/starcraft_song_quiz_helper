"""[활용할 노래들] 조회 / 직접 추가 / 활용 완료 / 삭제."""
import streamlit as st

import db
from config import LANGUAGES, lang_label
from views import common


def render():
    st.header("📋 활용할 노래들")
    engine = common.need_engine()
    common.show_flash()

    with st.expander("곡 직접 추가"):
        with st.form("planned_add", clear_on_submit=True):
            artist = st.text_input("가수")
            title = st.text_input("제목")
            url = st.text_input("유튜브 링크 (선택)")
            lang_choice = st.selectbox("언어", common.language_options(), key="planned_add_lang",
                                       format_func=lambda c: c if c == common.AUTO else lang_label(c))
            if st.form_submit_button("추가"):
                if not title.strip():
                    st.warning("제목을 입력해 주세요.")
                else:
                    from normalize import detect_language
                    code = detect_language(artist, title) if lang_choice == common.AUTO else lang_choice
                    r = db.add_song(engine, artist, title, code, "planned", url.strip() or None)
                    if r["added"]:
                        st.success(f"추가했어요! (팩 {r['pack_no']})")
                        common.bump("planned")
                    else:
                        ex = r["existing"]
                        where = "활용한 노래" if ex and ex["status"] == "used" else "활용할 노래들"
                        st.warning(f"이미 {where}에 있는 곡이에요" + (f": {ex['artist']} - {ex['title']}" if ex else "."))

    common.show_cleanup_skipped()
    common.render_cleanup(engine, "planned")
    flang = st.selectbox("언어 필터", ["전체"] + list(LANGUAGES), key="planned_lang_filter",
                         format_func=lambda c: c if c == "전체" else lang_label(c))
    rows = db.list_songs(engine, status="planned", language=None if flang == "전체" else flang)
    no_artist = st.checkbox("가수가 비어 있는 곡만 보기", key="planned_no_artist")
    if no_artist:
        rows = [r for r in rows if not (r["artist"] or "").strip()]
    st.caption(f"{len(rows)}곡")
    ids = common.song_editor(engine, rows, f"planned_tbl_{common.ver('planned')}_{flang}_{no_artist}", with_pack=True)

    if ids:
        st.write(f"선택한 곡 {len(ids)}곡")
        if st.session_state.get("confirm_planned_del"):
            st.warning("정말 삭제할까요?")
            c1, c2 = st.columns(2)
            if c1.button("네, 삭제합니다", type="primary"):
                db.delete_songs(engine, ids)
                st.session_state["confirm_planned_del"] = False
                common.bump("planned")
                st.rerun()
            if c2.button("취소"):
                st.session_state["confirm_planned_del"] = False
                st.rerun()
        else:
            c1, c2 = st.columns(2)
            if c1.button("✅ 활용 완료로 변경", type="primary",
                         help="'활용한 노래'로 옮기고 팩에서는 빠져요."):
                n = db.mark_used(engine, ids)
                st.success(f"{n}곡을 활용 완료로 바꿨어요.")
                common.bump("planned")
                st.rerun()
            if c2.button("🗑 선택 삭제"):
                st.session_state["confirm_planned_del"] = True
                st.rerun()
