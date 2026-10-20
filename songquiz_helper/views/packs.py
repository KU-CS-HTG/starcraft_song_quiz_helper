"""[200곡 팩] 진행도 / 이동 / 제거 / 내보내기."""
from collections import Counter

import pandas as pd
import streamlit as st

import db
from config import PACK_SIZE, lang_label
from views import common


def _ratio_text(rows: list[dict]) -> str:
    if not rows:
        return "곡이 없어요."
    c = Counter(r["language"] for r in rows)
    order = ["en", "ko", "ja"] + [k for k in c if k not in ("en", "ko", "ja")]
    return " · ".join(f"{lang_label(k)} {c[k]}곡 ({c[k] / len(rows):.0%})" for k in order if c.get(k))


def _export_rows(rows: list[dict], with_link: bool) -> pd.DataFrame:
    data = [{"번호": i, "가수": r["artist"], "제목": r["title"], "언어": lang_label(r["language"]),
             **({"유튜브링크": r["youtube_url"] or ""} if with_link else {})}
            for i, r in enumerate(rows, 1)]
    return pd.DataFrame(data)


def _txt(rows: list[dict], with_link: bool) -> str:
    lines = []
    for i, r in enumerate(rows, 1):
        name = f"{r['artist']} - {r['title']}" if r["artist"] else r["title"]
        link = f" | {r['youtube_url']}" if with_link and r["youtube_url"] else ""
        lines.append(f"{i}. {name}{link}")
    return "\n".join(lines) + "\n"


def render():
    st.header("📦 200곡 팩")
    engine = common.need_engine()
    common.show_flash()

    counts = db.pack_counts(engine)
    current = db.current_pack_no(engine)
    n_cur = counts.get(current, 0)
    st.subheader(f"현재 팩: {current}번")
    st.progress(min(n_cur / PACK_SIZE, 1.0), text=f"{n_cur}/{PACK_SIZE}")
    if n_cur == 0 and not counts:
        st.caption("아직 활용할 노래가 없어요. 곡을 '활용할 노래들'에 저장하면 자동으로 팩에 담겨요. "
                   f"{PACK_SIZE}곡이 차면 다음 팩이 자동으로 만들어져요.")

    with st.expander("전체 팩 요약"):
        all_planned = db.list_songs(engine, status="planned")
        for p in sorted(counts):
            ps = [s for s in all_planned if s["pack_no"] == p]
            st.write(f"**{p}번 팩** {len(ps)}/{PACK_SIZE} — {_ratio_text(ps)}")

    packs = sorted(set(counts) | {current})
    sel = st.selectbox("팩 선택", packs, index=packs.index(current), format_func=lambda p: f"{p}번 팩")
    rows = db.list_songs(engine, status="planned", pack_no=sel, newest_first=False)
    st.progress(min(len(rows) / PACK_SIZE, 1.0), text=f"{sel}번 팩 {len(rows)}/{PACK_SIZE}")
    st.caption("언어 비율: " + _ratio_text(rows))
    ids = common.song_editor(engine, rows, f"pack_tbl_{common.ver('packs')}_{common.ver('planned')}_{sel}",
                             with_pack=True)

    if ids:
        st.write(f"선택한 곡 {len(ids)}곡")
        target = st.number_input("이동할 팩 번호", min_value=1, value=(sel + 1), step=1)
        if st.button("➡ 선택한 곡을 해당 팩으로 이동"):
            try:
                db.move_to_pack(engine, ids, int(target))
                common.bump("packs")
                common.bump("planned")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        if st.session_state.get("confirm_pack_del"):
            st.warning("선택한 곡을 '활용할 노래들'에서도 삭제할까요?")
            c1, c2 = st.columns(2)
            if c1.button("네, 삭제합니다", type="primary"):
                db.delete_songs(engine, ids)
                st.session_state["confirm_pack_del"] = False
                common.bump("packs")
                common.bump("planned")
                st.rerun()
            if c2.button("취소"):
                st.session_state["confirm_pack_del"] = False
                st.rerun()
        elif st.button("🗑 팩에서 제거 (곡 삭제)"):
            st.session_state["confirm_pack_del"] = True
            st.rerun()

    st.divider()
    st.subheader("내보내기")
    with_link = st.checkbox("유튜브 링크 포함", value=False)
    if rows:
        df = _export_rows(rows, with_link)
        c1, c2 = st.columns(2)
        c1.download_button("⬇ CSV", df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"pack_{sel}.csv", mime="text/csv")
        c2.download_button("⬇ TXT", _txt(rows, with_link).encode("utf-8"),
                           file_name=f"pack_{sel}.txt", mime="text/plain")
    else:
        st.caption("내보낼 곡이 없어요.")
