"""여러 화면에서 같이 쓰는 컴포넌트."""
from __future__ import annotations

import logging
import re
from datetime import timezone

import pandas as pd
import streamlit as st

import db
import youtube
from cleanup import plan_name_fixes
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


# ---------------------------------------------------------------- 곡 목록 (표에서 바로 수정)
def _cell(v) -> str:
    return "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v).strip()


def collect_edits(rows: list[dict], edited: pd.DataFrame, to_code: dict) -> tuple[list[dict], list[int]]:
    """편집된 표(edited)를 원래 목록(rows)과 비교해 (바뀐 곡 목록, '선택' 체크된 곡 id 목록) 을 만든다."""
    changes, selected = [], []
    for i, r in enumerate(rows):
        e = edited.iloc[i]
        new = {"artist": _cell(e["가수"]), "title": _cell(e["제목"]),
               "language": to_code.get(_cell(e["언어"]), r["language"]), "youtube_url": _cell(e["유튜브 링크"])}
        old = {"artist": _cell(r["artist"]), "title": _cell(r["title"]),
               "language": r["language"], "youtube_url": _cell(r["youtube_url"])}
        if new != old:
            changes.append({"id": r["id"], **new})
        if bool(e["선택"]):
            selected.append(r["id"])
    return changes, selected


def song_editor(engine, rows: list[dict], key: str, with_pack: bool = False) -> list[int]:
    """곡 목록을 엑셀처럼 편집할 수 있는 표로 보여준다.

    - 가수/제목/언어/유튜브 링크 칸을 더블클릭하면 바로 수정, 여러 칸을 고친 뒤 [변경사항 저장] 한 번으로 반영.
    - '선택' 체크 열로 고른 곡의 id 목록을 돌려준다 (삭제/활용 완료/팩 이동 등 호출한 쪽의 작업용).
    - 표 내용(필터 등)이 바뀌면 입력 상태가 엉키지 않도록 호출하는 쪽에서 key 에 버전/필터를 포함시킨다.
    """
    if not rows:
        st.caption("곡이 없어요.")
        return []
    labels = {c: lang_label(c) for c in LANGUAGES}
    to_code = {v: k for k, v in labels.items()}
    for r in rows:  # 목록에 없는 언어 코드도 그대로 보여줄 수 있게
        to_code.setdefault(lang_label(r["language"]), r["language"])
    data = {"선택": False,
            "가수": [r["artist"] or "" for r in rows], "제목": [r["title"] or "" for r in rows],
            "언어": [lang_label(r["language"]) for r in rows],
            "유튜브 링크": [r["youtube_url"] or "" for r in rows]}
    if with_pack:
        data["팩"] = [r["pack_no"] for r in rows]
    data["추가일"] = [to_local(r["added_at"]) for r in rows]
    df = pd.DataFrame(data)

    st.caption("✏️ 가수·제목·언어·링크 칸을 **더블클릭**해서 바로 고치고, 여러 곡을 고친 뒤 **변경사항 저장**을 누르세요. "
               "삭제 등 다른 작업은 '선택' 칸을 체크하세요. (검색/필터를 바꾸면 저장하지 않은 수정은 사라져요)")
    edited = st.data_editor(
        df, hide_index=True, width="stretch", num_rows="fixed", key=key,
        height=min(38 + 35 * len(df), 560), disabled=[c for c in ("팩", "추가일") if c in df],
        column_config={
            "선택": st.column_config.CheckboxColumn("선택", width="small"),
            "제목": st.column_config.TextColumn("제목", required=True),
            "언어": st.column_config.SelectboxColumn("언어", options=list(to_code), required=True, width="small"),
            "유튜브 링크": st.column_config.TextColumn("유튜브 링크"),
            "팩": st.column_config.NumberColumn("팩", width="small"),
        },
    )

    changes, selected = collect_edits(rows, edited, to_code)

    if changes:
        st.warning(f"✏️ 저장하지 않은 변경이 {len(changes)}곡 있어요.")
        if any(not c["title"] for c in changes):
            st.error("제목이 비어 있는 곡이 있어요. 제목을 채우거나 되돌려 주세요.")
        elif st.button(f"💾 변경사항 저장 ({len(changes)}곡)", type="primary", key=f"{key}_save"):
            res = db.update_songs_bulk(engine, changes)
            msg = f"{res['updated']}곡을 수정했어요."
            if res["skipped"]:
                msg += f" (다른 곡과 겹쳐 수정하지 못한 곡 {len(res['skipped'])}곡)"
                st.session_state["_cleanup_skipped"] = res["skipped"]
            flash(msg)
            bump_all()
            st.rerun()
    elif selected:
        swappable = [r for r in rows if r["id"] in selected and _cell(r["artist"]) and _cell(r["title"])]
        if st.button(f"🔁 선택한 {len(selected)}곡 가수↔제목 바꾸기", key=f"{key}_swap", disabled=not swappable,
                     help="가수와 제목이 서로 뒤바뀌어 올라간 곡을 한 번에 고쳐요. 가수가 비어 있는 곡은 제외돼요."):
            res = db.update_songs_bulk(
                engine, [{"id": r["id"], "artist": r["title"], "title": r["artist"]} for r in swappable])
            msg = f"{res['updated']}곡의 가수와 제목을 바꿨어요."
            if res["skipped"]:
                msg += f" (다른 곡과 겹쳐 건너뛴 곡 {len(res['skipped'])}곡)"
                st.session_state["_cleanup_skipped"] = res["skipped"]
            flash(msg)
            bump_all()
            st.rerun()
    return selected


def bump_all() -> None:
    """모든 목록 표의 선택 상태를 초기화한다 (곡이 수정/이동/삭제된 뒤)."""
    for n in ("used", "planned", "packs"):
        bump(n)


def flash(msg: str) -> None:
    """다음 화면(rerun 이후)에 한 번만 보여줄 성공 메시지."""
    st.session_state["_flash"] = msg


def show_flash() -> None:
    msg = st.session_state.pop("_flash", None)
    if msg:
        st.success(msg)


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


# ---------------------------------------------------------------- 가수/제목 일괄 정리
def render_cleanup(engine, status: str) -> None:
    """가수가 비어 있고 제목에 '가수 - 제목' / '가수: 제목' 이 통째로 들어간 곡을 한꺼번에 정리."""
    plan = plan_name_fixes(db.list_songs(engine, status=status))
    with st.expander(f"🧹 가수/제목 한꺼번에 정리 (후보 {len(plan)}곡)", expanded=bool(plan)):
        if not plan:
            st.caption("정리할 곡이 없어요. 가수가 비어 있으면서 제목에 ' - ' 나 ':' 구분자가 들어간 곡이 대상이에요.")
            return
        st.caption("가수가 비어 있는 곡의 제목을 다시 나눈 결과예요. 맞지 않는 줄은 체크를 해제하거나 "
                   "가수/제목 칸을 직접 고친 뒤 적용하세요. (예: 가수 없이 콜론이 든 제목 'Mission: Impossible')")
        df = pd.DataFrame({"적용": True, "현재 제목": [p["old_title"] for p in plan],
                           "가수": [p["artist"] for p in plan], "제목": [p["title"] for p in plan]})
        key = f"cleanup_{status}_{ver('cleanup')}_{len(plan)}"
        edited = st.data_editor(df, hide_index=True, width="stretch", key=key, disabled=["현재 제목"],
                                column_config={"적용": st.column_config.CheckboxColumn("적용", width="small")})
        chosen = edited[edited["적용"]]
        if st.button(f"✅ 선택한 {len(chosen)}곡 정리 적용", type="primary", disabled=chosen.empty, key=f"{key}_go"):
            fixes = [{"id": plan[i]["id"], "artist": row["가수"], "title": row["제목"]}
                     for i, row in chosen.iterrows()]
            res = db.apply_name_fixes(engine, fixes)
            msg = f"{res['updated']}곡을 정리했어요."
            if res["skipped"]:
                msg += f" (다른 곡과 겹쳐 건너뛴 곡 {len(res['skipped'])}곡)"
                st.session_state["_cleanup_skipped"] = res["skipped"]
            flash(msg)
            bump("cleanup")
            bump_all()
            st.rerun()


def show_cleanup_skipped() -> None:
    sk = st.session_state.pop("_cleanup_skipped", None)
    if sk:
        with st.expander(f"겹쳐서 건너뛴 곡 {len(sk)}곡 보기", expanded=True):
            st.write("\n".join(
                f"- {s['artist'] + ' - ' if s['artist'] else ''}{s['title']}  ⟵ 이미 있음: "
                f"{s['existing']['artist'] + ' - ' if s['existing']['artist'] else ''}{s['existing']['title']}"
                for s in sk))
