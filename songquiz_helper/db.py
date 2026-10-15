"""DB 접근 계층. 앱의 모든 SQL 은 이 파일에만 있다.

- 운영: Supabase PostgreSQL (connection pooler URL)
- 테스트: SQLAlchemy 가 지원하는 아무 DB (예: sqlite://) — make_engine() 으로 엔진만 바꾸면 된다.
다른 DB 로 옮길 때는 이 파일만 수정하면 되도록, 함수는 단순 dict/list 만 주고받는다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import streamlit as st
from sqlalchemy import (BigInteger, Column, DateTime, Index, Integer, MetaData, bindparam,
                        String, Table, Text, create_engine, delete, func,
                        insert, select, update)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from config import PACK_SIZE, get_secret
from normalize import keys_for

metadata = MetaData()
_ID = BigInteger().with_variant(Integer, "sqlite")

songs = Table(
    "songs", metadata,
    Column("id", _ID, primary_key=True, autoincrement=True),
    Column("title", Text, nullable=False),
    Column("artist", Text, nullable=False, server_default=""),
    Column("language", String(8), nullable=False, server_default="기타"),  # en/ko/ja/기타
    Column("status", String(8), nullable=False),                          # used / planned
    Column("pack_no", Integer),                                            # planned 곡만 사용
    Column("youtube_url", Text),
    Column("added_at", DateTime(timezone=True), nullable=False),
    Column("norm_key", Text, nullable=False),
    Index("ix_songs_norm_key", "norm_key", unique=True),
    Index("ix_songs_status_pack", "status", "pack_no"),
)

recommended_history = Table(
    "recommended_history", metadata,
    Column("id", _ID, primary_key=True, autoincrement=True),
    Column("title", Text, nullable=False),
    Column("artist", Text, nullable=False, server_default=""),
    Column("language", String(8), nullable=False, server_default="기타"),
    Column("recommended_at", DateTime(timezone=True), nullable=False),
    Column("norm_key", Text, nullable=False),
    Index("ix_history_norm_key", "norm_key"),
)

youtube_cache = Table(
    "youtube_cache", metadata,
    Column("query", Text, primary_key=True),
    Column("result_json", Text, nullable=False),
    Column("cached_at", DateTime(timezone=True), nullable=False),
)


class DBNotConfigured(Exception):
    """DATABASE_URL 이 설정되지 않았을 때."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- 엔진
def _normalize_url(url: str) -> str:
    """postgres:// 나 postgresql:// 를 SQLAlchemy 용(psycopg2 드라이버) 으로 바꾼다."""
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


def make_engine(url: str) -> Engine:
    """엔진 생성 + 테이블 자동 생성. (캐시 없는 순수 함수 — 테스트에서도 사용)"""
    url = _normalize_url(url)
    if url.startswith("sqlite"):
        engine = create_engine(url, poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
    else:
        engine = create_engine(
            url,
            pool_size=2, max_overflow=3,   # pooler 연결 수를 아끼기 위해 작게
            pool_pre_ping=True,            # 끊긴 연결 자동 복구
            pool_recycle=1800,
            connect_args={"connect_timeout": 10},
        )
    init_schema(engine)
    return engine


def init_schema(engine: Engine) -> None:
    """테이블이 없으면 만든다 (CREATE TABLE IF NOT EXISTS)."""
    metadata.create_all(engine, checkfirst=True)


@st.cache_resource(show_spinner="DB에 연결하는 중…")
def get_engine() -> Engine:
    """앱 전체에서 한 번만 만들어지는 엔진. 실패하면 예외 (캐시되지 않음)."""
    url = get_secret("DATABASE_URL")
    if not url:
        raise DBNotConfigured("DATABASE_URL 이 설정되지 않았습니다.")
    return make_engine(url)


# ---------------------------------------------------------------- 공통 유틸
def _rows(result) -> list[dict]:
    return [dict(r._mapping) for r in result]


def _assign_packs(conn, n: int) -> list[int]:
    """새 활용할 노래 n 곡이 들어갈 팩 번호. 가장 앞의 '안 찬' 팩부터 채우고, 다 차면 다음 팩 생성."""
    rows = conn.execute(
        select(songs.c.pack_no, func.count()).where(
            songs.c.status == "planned", songs.c.pack_no.is_not(None)
        ).group_by(songs.c.pack_no)
    ).all()
    counts = {p: c for p, c in rows}
    out, pack = [], 1
    for _ in range(n):
        while counts.get(pack, 0) >= PACK_SIZE:
            pack += 1
        out.append(pack)
        counts[pack] = counts.get(pack, 0) + 1
    return out


# ---------------------------------------------------------------- songs
def list_songs(engine: Engine, status: str | None = None, language: str | None = None,
               pack_no: int | None = None, newest_first: bool = True) -> list[dict]:
    q = select(songs)
    if status:
        q = q.where(songs.c.status == status)
    if language:
        q = q.where(songs.c.language == language)
    if pack_no is not None:
        q = q.where(songs.c.pack_no == pack_no)
    q = q.order_by(songs.c.id.desc() if newest_first else songs.c.id.asc())
    with engine.connect() as conn:
        return _rows(conn.execute(q))


def add_song(engine: Engine, artist: str, title: str, language: str, status: str,
             youtube_url: str | None = None) -> dict:
    """곡 1개 추가. 이미 같은 곡(순서 뒤바뀜 포함)이 있으면 추가하지 않는다.

    반환: {"added": bool, "existing": dict | None, "pack_no": int | None}
    """
    artist, title = (artist or "").strip(), (title or "").strip()
    key, swapped = keys_for(artist, title)
    try:
        with engine.begin() as conn:
            ex = conn.execute(
                select(songs).where(songs.c.norm_key.in_({key, swapped})).limit(1)
            ).first()
            if ex:
                return {"added": False, "existing": dict(ex._mapping), "pack_no": None}
            pack = _assign_packs(conn, 1)[0] if status == "planned" else None
            conn.execute(insert(songs).values(
                title=title, artist=artist, language=language or "기타", status=status,
                pack_no=pack, youtube_url=youtube_url or None, added_at=_now(), norm_key=key,
            ))
            return {"added": True, "existing": None, "pack_no": pack}
    except IntegrityError:  # 동시 추가 등으로 unique 인덱스에 걸린 경우
        return {"added": False, "existing": None, "pack_no": None}


def add_songs_bulk(engine: Engine, rows: list[dict], status: str,
                   update_language: bool = False) -> dict:
    """여러 곡 추가 (업로드용). rows: [{artist, title, language, explicit(선택)}].

    반환: {"added": int, "duplicates": [row...], "invalid": int, "language_updated": int}
    - 이미 DB 에 있거나(순서 뒤바뀜 포함) 파일 안에서 반복된 곡은 건너뛴다.
    - update_language=True 이면, 이미 있는 곡 중 row["explicit"](문단 표시 등 확실한 언어)이 있고
      저장된 언어와 다른 곡은 언어만 갱신한다.
    """
    with engine.connect() as conn:
        existing_rows = conn.execute(select(songs.c.id, songs.c.norm_key, songs.c.language)).all()
    existing = {k for (_, k, _) in existing_rows}
    by_key = {k: (i, lang) for (i, k, lang) in existing_rows}
    lang_fixes: dict[int, str] = {}
    seen, new_rows, dups, invalid = set(existing), [], [], 0
    for r in rows:
        artist, title = (r.get("artist") or "").strip(), (r.get("title") or "").strip()
        if not title:
            invalid += 1
            continue
        key, swapped = keys_for(artist, title)
        if key in seen or swapped in seen:
            dups.append({"artist": artist, "title": title})
            hit = by_key.get(key) or by_key.get(swapped)
            if update_language and r.get("explicit") and hit and hit[1] != r.get("language"):
                lang_fixes[hit[0]] = r["language"]
            continue
        seen.add(key)
        new_rows.append({"artist": artist, "title": title, "key": key,
                         "language": r.get("language") or "기타"})

    def _payload(conn):
        packs = _assign_packs(conn, len(new_rows)) if status == "planned" else [None] * len(new_rows)
        now = _now()
        return [dict(title=n["title"], artist=n["artist"], language=n["language"], status=status,
                     pack_no=p, youtube_url=None, added_at=now, norm_key=n["key"])
                for n, p in zip(new_rows, packs)]

    added = 0
    if new_rows:
        try:
            with engine.begin() as conn:
                conn.execute(insert(songs), _payload(conn))
            added = len(new_rows)
        except IntegrityError:  # 드문 경합 상황: 한 곡씩 다시 시도
            for n in new_rows:
                res = add_song(engine, n["artist"], n["title"], n["language"], status)
                if res["added"]:
                    added += 1
                else:
                    dups.append({"artist": n["artist"], "title": n["title"]})
    for sid, lang in lang_fixes.items():
        with engine.begin() as conn:
            conn.execute(update(songs).where(songs.c.id == sid).values(language=lang))
    return {"added": added, "duplicates": dups, "invalid": invalid, "language_updated": len(lang_fixes)}


def update_song(engine: Engine, song_id: int, artist: str, title: str, language: str,
                youtube_url: str | None = None) -> dict:
    """곡 정보 수정. 가수/제목이 바뀌면 중복 판별 키(norm_key)도 다시 계산한다.

    다른 곡과 같은 곡(순서 뒤바뀜 포함)이 되어 버리면 수정하지 않는다.
    반환: {"updated": bool, "existing": dict | None}  (existing: 충돌한 다른 곡)
    """
    artist, title = (artist or "").strip(), (title or "").strip()
    if not title:
        raise ValueError("제목은 비워 둘 수 없어요.")
    key, swapped = keys_for(artist, title)
    try:
        with engine.begin() as conn:
            clash = conn.execute(
                select(songs).where(songs.c.norm_key.in_({key, swapped}), songs.c.id != song_id).limit(1)
            ).first()
            if clash:
                return {"updated": False, "existing": dict(clash._mapping)}
            n = conn.execute(update(songs).where(songs.c.id == song_id).values(
                artist=artist, title=title, language=language or "기타",
                youtube_url=(youtube_url or "").strip() or None, norm_key=key)).rowcount
            return {"updated": n > 0, "existing": None}
    except IntegrityError:
        return {"updated": False, "existing": None}


def apply_name_fixes(engine: Engine, fixes: list[dict]) -> dict:
    """가수/제목 일괄 수정 (한 트랜잭션). fixes: [{id, artist, title}].

    다른 곡(이번 일괄 수정으로 바뀐 곡 포함)과 같은 곡이 되어 버리는 항목은 건너뛴다.
    반환: {"updated": int, "skipped": [{"id", "artist", "title", "existing": dict}]}
    """
    skipped, to_apply = [], []
    with engine.begin() as conn:
        rows = conn.execute(select(songs.c.id, songs.c.artist, songs.c.title, songs.c.status,
                                   songs.c.norm_key)).all()
        info = {r.id: r for r in rows}
        owner = {r.norm_key: r.id for r in rows}
        for f in fixes:
            sid, artist, title = f["id"], (f.get("artist") or "").strip(), (f.get("title") or "").strip()
            old = info.get(sid)
            if not old or not title:
                continue
            key, swapped = keys_for(artist, title)
            clash = next((owner[k] for k in (key, swapped) if k in owner and owner[k] != sid), None)
            if clash is not None:
                c = info[clash]
                skipped.append({"id": sid, "artist": artist, "title": title,
                                "existing": {"artist": c.artist, "title": c.title, "status": c.status}})
                continue
            if owner.get(old.norm_key) == sid:
                del owner[old.norm_key]
            owner[key] = sid
            to_apply.append({"b_id": sid, "b_artist": artist, "b_title": title, "b_key": key})
        if to_apply:
            conn.execute(
                update(songs).where(songs.c.id == bindparam("b_id")).values(
                    artist=bindparam("b_artist"), title=bindparam("b_title"), norm_key=bindparam("b_key")),
                to_apply)
    return {"updated": len(to_apply), "skipped": skipped}


def delete_songs(engine: Engine, ids: list[int]) -> int:
    if not ids:
        return 0
    with engine.begin() as conn:
        return conn.execute(delete(songs).where(songs.c.id.in_(ids))).rowcount


def mark_used(engine: Engine, ids: list[int]) -> int:
    """활용할 노래 → 활용 완료. 팩에서는 빠진다(pack_no 해제)."""
    if not ids:
        return 0
    with engine.begin() as conn:
        return conn.execute(
            update(songs).where(songs.c.id.in_(ids), songs.c.status == "planned")
            .values(status="used", pack_no=None)
        ).rowcount


def move_to_pack(engine: Engine, ids: list[int], pack_no: int) -> int:
    """곡을 다른 팩으로 이동. 대상 팩이 가득 차면 ValueError."""
    if not ids:
        return 0
    with engine.begin() as conn:
        already = conn.execute(
            select(func.count()).where(songs.c.pack_no == pack_no, songs.c.status == "planned",
                                       songs.c.id.in_(ids))
        ).scalar_one()
        current = conn.execute(
            select(func.count()).where(songs.c.pack_no == pack_no, songs.c.status == "planned")
        ).scalar_one()
        incoming = len(ids) - already
        if current + incoming > PACK_SIZE:
            raise ValueError(f"{pack_no}번 팩은 {PACK_SIZE}곡까지만 담을 수 있어요 "
                             f"(현재 {current}곡, 추가하려는 곡 {incoming}곡).")
        return conn.execute(
            update(songs).where(songs.c.id.in_(ids), songs.c.status == "planned")
            .values(pack_no=pack_no)
        ).rowcount


def pack_counts(engine: Engine) -> dict[int, int]:
    """{pack_no: 곡 수} (planned 만)."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(songs.c.pack_no, func.count()).where(
                songs.c.status == "planned", songs.c.pack_no.is_not(None)
            ).group_by(songs.c.pack_no).order_by(songs.c.pack_no)
        ).all()
    return {p: c for p, c in rows}


def current_pack_no(engine: Engine) -> int:
    """지금 채우는 중인 팩 번호 (가장 앞의 안 찬 팩)."""
    with engine.connect() as conn:
        return _assign_packs(conn, 1)[0]


# ---------------------------------------------------------------- 추천 기록
def list_history(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        return _rows(conn.execute(select(recommended_history).order_by(recommended_history.c.id.desc())))


def add_history(engine: Engine, items: list[dict]) -> int:
    """추천했던 곡을 기록한다(이미 기록된 곡은 건너뜀). 반환: 새로 기록한 수."""
    if not items:
        return 0
    with engine.connect() as conn:
        seen = {k for (k,) in conn.execute(select(recommended_history.c.norm_key))}
    payload, now = [], _now()
    for it in items:
        key = keys_for(it.get("artist", ""), it.get("title", ""))[0]
        if key in seen:
            continue
        seen.add(key)
        payload.append(dict(title=it["title"], artist=it.get("artist", ""),
                            language=it.get("language") or "기타", recommended_at=now, norm_key=key))
    if payload:
        with engine.begin() as conn:
            conn.execute(insert(recommended_history), payload)
    return len(payload)


# ---------------------------------------------------------------- 유튜브 캐시
def cache_get(engine: Engine, query: str, ttl_days: int = 30):
    """캐시된 검색 결과(파이썬 객체). 없거나 만료되면 None."""
    with engine.connect() as conn:
        row = conn.execute(
            select(youtube_cache.c.result_json, youtube_cache.c.cached_at)
            .where(youtube_cache.c.query == query)
        ).first()
    if not row:
        return None
    cached_at = row.cached_at
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    if _now() - cached_at > timedelta(days=ttl_days):
        return None
    return json.loads(row.result_json)


def cache_put(engine: Engine, query: str, result) -> None:
    with engine.begin() as conn:
        conn.execute(delete(youtube_cache).where(youtube_cache.c.query == query))
        conn.execute(insert(youtube_cache).values(
            query=query, result_json=json.dumps(result, ensure_ascii=False), cached_at=_now()))
