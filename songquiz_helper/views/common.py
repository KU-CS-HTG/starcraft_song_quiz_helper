"""여러 화면에서 같이 쓰는 컴포넌트."""
from __future__ import annotations

import logging
import re
from datetime import timezone

import pandas as pd
import streamlit as st

import db
import youtube
from config import LANGUAGES, get_secret, lang_label
from normalize import SongIndex, detect_language

AUTO = "자동 감지"


def _safe_error(e: Exception) -> str:
    """예외 문장에서 접속 주소의 비밀번호와 DATABASE_URL 원문을 가린다."""
    text = " ".join(str(getattr(e, "orig", None) or e).split())
    text = re.sub(r"(://[^:/@\s]+:)[^@\s]+@", r"\1****@", text)
    secret = get_secret("DATABASE_URL")
    if secret:
        text = text.replace(secret, "<DATABASE_URL>")
    return text[:600]


def _error_hint(detail: str) -> str:
    low = detail.lower()
    if "password authentication failed" in low:
        return "💡 DB 비밀번호가 틀렸어요. [YOUR-PASSWORD] 대괄호까지 실제 비밀번호로 바꿨는지, 특수문자는 URL 인코딩했는지 확인하세요."
    if "tenant or user not found" in low:
        return "💡 사용자 이름(postgres.프로젝트ID)이나 pooler 지역 주소가 프로젝트와 달라요. Connect 화면의 URI를 그대로 복사하세요."
    if "could not translate host name" in low or "name or service not known" in low:
        return "💡 주소(호스트) 오타예요. Connect 화면의 URI를 다시 복사하세요."
    if "network is unreachable" in low or "db." in low and "supabase.co" in low:
        return "💡 Direct 주소(db.xxx.supabase.co)는 안 돼요. pooler.supabase.com 주소를 쓰세요."
    if "timeout" in low or "timed out" in low:
        return "💡 응답이 없어요. Supabase 프로젝트가 일시 중지(Paused)됐는지 확인하고 Restore 하세요."
    return "💡 위 문장을 확인하세요. 프로젝트 일시 중지, 주소·비밀번호 오류가 가장 흔한 원인이에요."


def need_engine():
    """DB 엔진을 돌려준다. 설정/연결 문제가 있으면 안내 메시지를 보여주고 이 화면만 멈춘다."""
    try:
        return db.get_engine()
    except db.DBNotConfigured:
        st.warning("DATABASE_URL 이 설정되지 않았어요. Secrets 에 Supabase 연결 주소를 넣어 주세요. "
                   "(README 의 'DB 생성' 단계 참고)")
    except Exception as e:  # 연결 실패: 원인 문장은 보여주되 비밀번호는 가린다
        detail = _safe_error(e)
        logging.getLogger(__name__).error("DB 연결 실패: %s", detail)
        st.error(f"DB 에 연결하지 못했어요 ({type(e).__name__}). DATABASE_URL(비밀번호, 포트, "
                 "pooler 주소)을 확인해 주세요.")
        st.code(detail, language=None)
        st.caption(_error_hint(detail))
    st.stop()


def language_options() -> list[str]:
    return [AUTO] + list(LANGUAGES)


def pick_language(label: str, key: str, artist: str, title: str) -> str:
    """언어 선택 상자(기본: 자동 감지). 선택된 언어 코드를 돌려준다."""
    choice = st.selectbox(label, language_options(), key=key,
                          format_func=lambda c: c if c == AUTO else lang_label(c))
    return detect_language(artist, title) if choice == AUTO else choice


def to_local(dt) -> str:
    """DB 시각 → 한국 시간 문자열."""
    if dt is None or pd.isna(dt):
        return ""
    ts = pd.Timestamp(dt)
    if ts.tzinfo is None:
        ts = ts.tz_localize(timezone.utc)
    return ts.tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M")


def songs_df(rows: list[dict], with_pack: bool = False) -> pd.DataFrame:
    cols = {"artist": "가수", "title": "제목", "language": "언어"}
    if with_pack:
        cols["pack_no"] = "팩"
    cols.update({"youtube_url": "유튜브", "added_at": "추가일"})
    df = pd.DataFrame(rows, columns=["id", *cols])
    df["language"] = df["language"].map(lang_label)
    df["added_at"] = df["added_at"].map(to_local)
    return df.rename(columns=cols)


def select_table(rows: list[dict], key: str, with_pack: bool = False) -> list[int]:
    """곡 목록 표를 보여주고, 사용자가 선택한 곡의 id 목록을 돌려준다.

    표 내용(필터 등)이 바뀌면 선택 상태가 엉키지 않도록 호출하는 쪽에서 key 에 버전/필터를 포함시킨다.
    """
    if not rows:
        st.caption("곡이 없어요.")
        return []
    df = songs_df(rows, with_pack)
    event = st.dataframe(
        df.drop(columns=["유튜브"]) if df["유튜브"].isna().all() else df,
        hide_index=True, on_select="rerun", selection_mode="multi-row", key=key,
        width="stretch", column_config={"id": None, "유튜브": st.column_config.LinkColumn("유튜브", display_text="열기")},
    )
    return [rows[i]["id"] for i in event.selection.rows if i < len(rows)]


def bump(name: str) -> None:
    """표 위젯 key 의 버전을 올려 선택 상태를 초기화한다 (데이터 변경 후 호출)."""
    st.session_state[f"ver_{name}"] = st.session_state.get(f"ver_{name}", 0) + 1


def ver(name: str) -> int:
    return st.session_state.get(f"ver_{name}", 0)


# ---------------------------------------------------------------- 중복 확인
def check_duplicate(engine, artist: str, title: str) -> dict:
    """활용한 곡 / 활용 예정 곡 / 이전 추천 곡 각각에서 같은·비슷한 곡 찾기."""
    songs = db.list_songs(engine)
    used = SongIndex(s for s in songs if s["status"] == "used")
    planned = SongIndex(s for s in songs if s["status"] == "planned")
    hist = SongIndex(db.list_history(engine))
    return {"used": used.find(artist, title), "planned": planned.find(artist, title),
            "history": hist.find(artist, title)}


def render_duplicate(res: dict) -> None:
    """중복 판별 결과를 눈에 띄게 표시."""
    shown = False
    u = res["used"]
    if u:
        shown = True
        if u.kind == "exact":
            st.error(f"🚫 **이미 활용한 노래입니다** — 일치: {u.label()}")
        else:
            st.warning(f"⚠️ **비슷한 곡(이미 활용했을 수 있음)** — {u.label()} (유사도 {u.score:.0f})")
    p = res["planned"]
    if p:
        shown = True
        kind = "이미 있습니다" if p.kind == "exact" else f"비슷한 곡이 있습니다 (유사도 {p.score:.0f})"
        st.info(f"📋 활용할 노래들에 {kind}: {p.label()}")
    h = res["history"]
    if h:
        shown = True
        st.info(f"🕘 이전에 추천받은 적 있는 곡: {h.label()}")
    if not shown:
        st.success("✅ 활용한 적 없는 새로운 곡이에요.")


# ---------------------------------------------------------------- 유튜브 패널
def _fmt_views(n: int) -> str:
    return f"{n:,}회"


def _video_block(label: str, video: dict, engine, artist: str, title: str, key: str) -> None:
    st.markdown(f"**{label}**")
    st.markdown(f"[{video['title']}]({video['url']})")
    st.caption(f"채널: {video['channel']} · 조회수 {_fmt_views(video['views'])}")
    if st.button("➕ 활용할 노래들에 추가", key=key):
        lang = detect_language(artist, title)
        res = db.add_song(engine, artist, title, lang, "planned", video["url"])
        if res["added"]:
            st.success(f"추가했어요! (팩 {res['pack_no']})")
            bump("planned")
        elif res["existing"]:
            ex = res["existing"]
            where = "활용한 노래" if ex["status"] == "used" else "활용할 노래들"
            st.warning(f"이미 {where}에 있는 곡이에요: {ex['artist']} - {ex['title']}")
        else:
            st.warning("이미 있는 곡이라 추가하지 않았어요.")


def render_youtube(engine, artist: str, title: str, key_prefix: str) -> None:
    """유튜브 링크 2개(조회수 최고 / 공식 추정)를 보여준다."""
    api_key = get_secret("YOUTUBE_API_KEY")
    if not api_key:
        st.info("YOUTUBE_API_KEY 가 설정되지 않아 유튜브 링크는 건너뛰었어요. (README 참고)")
        return
    try:
        with st.spinner("유튜브 검색 중…"):
            r = youtube.analyze(engine, api_key, artist, title)
    except youtube.YouTubeError as e:
        st.error(str(e))
        return
    if not r["top"]:
        st.warning("유튜브에서 검색 결과를 찾지 못했어요.")
        return

    st.caption(("💾 캐시된 결과 (API 호출 없음)" if r["cached"] else "🔎 새로 검색함 (API 100 쿼터 사용)")
               + f" · 검색어: {r['query']}")
    off = r["official"]
    if r["same"]:
        _video_block("조회수 최고 영상 = 공식 추정 영상", r["top"], engine, artist, title, f"{key_prefix}_add_same")
    else:
        _video_block("① 조회수가 가장 높은 영상", r["top"], engine, artist, title, f"{key_prefix}_add_top")
        if off:
            _video_block("② 공식 영상으로 추정", off.video, engine, artist, title, f"{key_prefix}_add_off")
        else:
            st.markdown("**② 공식 영상으로 추정**")
            st.caption(f"기준({youtube.OFFICIAL_MIN_SCORE}점 이상)을 넘는 후보가 없어요.")
    if off:
        st.caption(f"공식 추정 점수 {off.score}점 (기준 {youtube.OFFICIAL_MIN_SCORE}점 이상) — "
                   + " / ".join(off.reasons))
    with st.expander("공식 추정 점수 기준 보기"):
        st.caption("\n\n".join("• " + t for t in youtube.RULES_TEXT)
                   + f"\n\n합계가 {youtube.OFFICIAL_MIN_SCORE}점 이상인 영상 중 최고점(동점이면 조회수 높은 쪽)을 고릅니다. "
                     "최종 판단은 직접 해 주세요.")
