"""[활용한 노래 관리] 업로드 / 직접 추가 / 목록·삭제."""
from collections import Counter

import streamlit as st

import db
import parsers
from config import LANGUAGES, lang_label
from normalize import detect_language
from views import common


def _upload_section(engine):
    st.subheader("파일 업로드")
    up = st.file_uploader("CSV / XLSX / TXT (TXT 는 한 줄에 '가수 - 제목' 또는 '가수: 제목')",
                          type=["csv", "xlsx", "txt"], key=f"used_upload_{common.ver('used_upload')}")
    if not up:
        return
    data, name = up.getvalue(), up.name
    rows: list[dict] = []
    try:
        if name.lower().endswith(".txt"):
            rows = parsers.parse_txt(data)
        else:
            sheet = None
            if name.lower().endswith((".xlsx", ".xlsm")):
                sheets = parsers.sheet_names(data)
                if len(sheets) > 1:
                    sheet = st.selectbox("시트", sheets)
            has_header = st.checkbox("첫 행은 컬럼명입니다", value=True)
            df = parsers.read_table(data, name, sheet, has_header)
            cols = list(df.columns)
            single = st.checkbox("한 컬럼에 '가수 - 제목'(또는 '가수: 제목') 형태로 들어 있어요", value=False)
            ai = parsers.guess_column(cols, parsers.ARTIST_HINTS)
            ti = parsers.guess_column(cols, parsers.TITLE_HINTS)
            title_col = st.selectbox("제목 컬럼" if not single else "'가수 - 제목' 컬럼", cols,
                                     index=ti if ti is not None else 0)
            artist_col = None
            if not single:
                artist_col = st.selectbox("가수 컬럼", cols, index=ai if ai is not None else min(1, len(cols) - 1))
            rows = parsers.rows_from_table(df, title_col, artist_col)
            st.caption("미리보기")
            st.dataframe(df.head(5), hide_index=True, width="stretch")
    except Exception as e:
        st.error(f"파일을 읽지 못했어요 ({type(e).__name__}). 형식/인코딩을 확인해 주세요.")
        return

    st.write(f"읽은 곡: **{len(rows)}곡**")
    marked = [r for r in rows if r.get("language")]
    if marked:
        cnt = Counter(r["language"] for r in marked)
        st.info("📑 문단 표시를 인식했어요: " + " · ".join(f"{lang_label(k)} {v}곡" for k, v in cnt.items())
                + f" · 표시 없음 {len(rows) - len(marked)}곡")
    elif name.lower().endswith(".txt"):
        st.caption("💡 TXT 안에 [한국어] / [영어] / [일본어] 같은 줄을 넣으면 그 아래 곡들의 언어가 자동 지정돼요.")
    lang_choice = st.selectbox("문단 표시가 없는 곡의 언어" if marked else "언어", common.language_options(),
                               key="used_up_lang",
                               format_func=lambda c: c if c == common.AUTO else lang_label(c),
                               help="자동 감지는 한글→한국어, 가나→일본어, 영문→영어로 추정해요.")
    fix_lang = False
    if marked:
        fix_lang = st.checkbox("이미 있는 곡도 문단 표시의 언어로 고치기", value=True,
                               help="예전에 올려서 언어가 잘못 저장된 곡을, 같은 곡이 표시된 문단의 언어로 바꿔요. "
                                    "가수/제목은 그대로 두고 언어만 바뀝니다.")
    if st.button(f"활용한 노래로 저장 ({len(rows)}곡)", type="primary", disabled=not rows):
        for r in rows:
            r["explicit"] = bool(r.get("language"))  # 문단 표시로 확정된 언어인지
            if not r.get("language"):  # 문단 표시가 있으면 그것이 우선
                r["language"] = detect_language(r["artist"], r["title"]) if lang_choice == common.AUTO else lang_choice
        with st.spinner("저장 중…"):
            res = db.add_songs_bulk(engine, rows, "used", update_language=fix_lang)
        st.session_state["upload_result"] = res
        common.bump("used")
        common.bump("used_upload")
        st.rerun()


def render():
    st.header("📚 활용한 노래 관리")
    engine = common.need_engine()

    common.show_flash()
    res = st.session_state.pop("upload_result", None)
    if res:
        st.success(f"✅ {res['added']}곡 추가 · 중복 {len(res['duplicates'])}곡 건너뜀"
                   + (f" · 제목 없는 줄 {res['invalid']}개 무시" if res["invalid"] else "")
                   + (f" · 기존 곡 {res['language_updated']}곡의 언어 수정" if res.get("language_updated") else ""))
        if res["duplicates"]:
            with st.expander("중복으로 건너뛴 곡 보기"):
                st.write("\n".join(f"- {d['artist']} - {d['title']}" if d["artist"] else f"- {d['title']}"
                                   for d in res["duplicates"]))

    _upload_section(engine)

    with st.expander("곡 1개 직접 추가"):
        with st.form("used_add", clear_on_submit=True):
            artist = st.text_input("가수")
            title = st.text_input("제목")
            lang = st.selectbox("언어", common.language_options(), key="used_add_lang",
                                format_func=lambda c: c if c == common.AUTO else lang_label(c))
            if st.form_submit_button("추가"):
                if not title.strip():
                    st.warning("제목을 입력해 주세요.")
                else:
                    code = detect_language(artist, title) if lang == common.AUTO else lang
                    r = db.add_song(engine, artist, title, code, "used")
                    if r["added"]:
                        st.success("추가했어요.")
                        common.bump("used")
                    else:
                        ex = r["existing"]
                        st.warning("이미 있는 곡이에요" + (f": {ex['artist']} - {ex['title']}" if ex else "."))

    st.divider()
    common.show_cleanup_skipped()
    common.render_cleanup(engine, "used")
    st.subheader("활용한 노래 목록")
    f1 = st.selectbox("언어 필터", ["전체"] + list(LANGUAGES), key="used_lang_filter",
                      format_func=lambda c: c if c == "전체" else lang_label(c))
    rows = db.list_songs(engine, status="used", language=None if f1 == "전체" else f1)
    kw = st.text_input("목록 안에서 검색", key="used_kw").strip().lower()
    if kw:
        rows = [r for r in rows if kw in f"{r['artist']} {r['title']}".lower()]
    no_artist = st.checkbox("가수가 비어 있는 곡만 보기", key="used_no_artist",
                            help="TXT 에서 ' - ' 구분이 없어 가수가 분리되지 않은 곡을 찾을 때 사용하세요.")
    if no_artist:
        rows = [r for r in rows if not (r["artist"] or "").strip()]
    st.caption(f"{len(rows)}곡 · 표에서 곡을 선택하면 아래에서 수정/삭제할 수 있어요")
    ids = common.select_table(rows, f"used_tbl_{common.ver('used')}_{f1}_{kw}_{no_artist}")
    common.render_edit(engine, rows, ids)

    if ids:
        st.write(f"선택한 곡 {len(ids)}곡")
        if st.session_state.get("confirm_used_del"):
            st.warning("정말 삭제할까요? 삭제하면 다시 중복 검사에 걸리지 않게 됩니다.")
            c1, c2 = st.columns(2)
            if c1.button("네, 삭제합니다", type="primary"):
                db.delete_songs(engine, ids)
                st.session_state["confirm_used_del"] = False
                common.bump("used")
                st.rerun()
            if c2.button("취소"):
                st.session_state["confirm_used_del"] = False
                st.rerun()
        elif st.button("🗑 선택 삭제"):
            st.session_state["confirm_used_del"] = True
            st.rerun()
