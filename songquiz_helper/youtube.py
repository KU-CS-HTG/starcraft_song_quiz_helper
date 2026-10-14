"""YouTube 검색 + 조회수 + '공식 영상 추정' 점수제.

search.list 는 호출당 100 쿼터(하루 10,000)이므로 결과를 DB(youtube_cache)에 캐시한다.
캐시에는 후보 영상 정보만 저장하고, 점수 계산은 매번 코드로 한다(가수명이 바뀌어도 재사용 가능).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

import db
from normalize import normalize_text

MAX_RESULTS = 10          # 검색 후보 수 (search.list 비용은 개수와 무관하게 100)
CACHE_TTL_DAYS = 30
OFFICIAL_MIN_SCORE = 4    # 이 점수 이상이어야 '공식 추정'으로 표시

# (설명, 점수) — 화면에 그대로 보여주는 기준표이기도 하다
RULES_TEXT = [
    "채널명에 VEVO: +3",
    "채널명에 Official: +2",
    "채널명이 '- Topic' (자동 생성 음원 채널): +2",
    "채널명이 입력한 가수명과 유사: +2",
    "제목에 Official: +2",
    "제목에 MV / M/V / 뮤직비디오: +2",
    "제목에 '공식': +2",
    "제목에 곡 제목이 포함: +2",
    "제목에 Cover / Live / Reaction / Lyrics / 가사 / 커버 / 직캠 / Remix: 키워드당 −3",
]
_NEGATIVE = ["cover", "live", "reaction", "lyrics", "lyric", "가사", "커버", "직캠", "remix"]


class YouTubeError(Exception):
    """사용자에게 그대로 보여줄 수 있는 YouTube 관련 오류."""


@dataclass
class Official:
    video: dict
    score: int
    reasons: list[str]


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _squash(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower())


def _word(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def score_official(video: dict, artist: str, title: str) -> tuple[int, list[str]]:
    """영상 1개의 '공식 영상 추정' 점수와 근거 목록."""
    ch, vt = video.get("channel", ""), video.get("title", "")
    score, why = 0, []

    def add(pts: int, msg: str) -> None:
        nonlocal score
        score += pts
        why.append(f"{pts:+d} {msg}")

    if _word(r"vevo", ch):
        add(3, "채널명에 VEVO")
    if _word(r"official|공식", ch):
        add(2, "채널명에 Official")
    if _word(r"-\s*topic\s*$", ch):
        add(2, "'- Topic' 채널")
    a = normalize_text(artist)
    c = re.sub(r"vevo|official|topic|channel|tv|공식", "", normalize_text(ch))
    if a and c:
        sim = fuzz.ratio(a, c) if len(a) <= 3 else max(fuzz.ratio(a, c), fuzz.partial_ratio(a, c) - 5)
        if sim >= 85:
            add(2, "채널명이 가수명과 유사")
    if _word(r"official", vt):
        add(2, "제목에 Official")
    if _word(r"(?<![a-z])(mv|m/v)(?![a-z])|뮤직\s*비디오", vt):
        add(2, "제목에 MV")
    if "공식" in vt:
        add(2, "제목에 '공식'")
    t = normalize_text(title)
    if t and t in _squash(vt):
        add(2, "제목에 곡 제목 포함")
    for kw in _NEGATIVE:
        if kw in vt.lower():
            add(-3, f"제목에 '{kw}'")
    return score, why


def pick_most_viewed(videos: list[dict]) -> dict | None:
    return max(videos, key=lambda v: v.get("views", 0), default=None)


def pick_official(videos: list[dict], artist: str, title: str) -> Official | None:
    """가장 점수가 높은 영상(동점이면 조회수 높은 쪽). 기준 미달이면 None."""
    best: Official | None = None
    for v in videos:
        s, why = score_official(v, artist, title)
        cand = Official(v, s, why)
        if best is None or (s, v.get("views", 0)) > (best.score, best.video.get("views", 0)):
            best = cand
    if best and best.score >= OFFICIAL_MIN_SCORE:
        return best
    return None


# ---------------------------------------------------------------- API 호출
def _fetch(api_key: str, query: str) -> list[dict]:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    try:
        yt = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        res = yt.search().list(q=query, part="snippet", type="video",
                               maxResults=MAX_RESULTS).execute()
        ids = [it["id"]["videoId"] for it in res.get("items", [])]
        if not ids:
            return []
        vids = yt.videos().list(part="snippet,statistics", id=",".join(ids)).execute()
    except HttpError as e:
        text = str(e)
        if "quotaExceeded" in text:
            raise YouTubeError("YouTube API 하루 쿼터를 모두 사용했어요. 내일(태평양 시간 자정 이후) 다시 시도해 주세요.") from e
        if "keyInvalid" in text or "API key not valid" in text:
            raise YouTubeError("YOUTUBE_API_KEY 가 올바르지 않아요. Secrets 값을 확인해 주세요.") from e
        if "accessNotConfigured" in text or "has not been used" in text:
            raise YouTubeError("Google Cloud 에서 'YouTube Data API v3' 를 사용 설정해 주세요.") from e
        raise YouTubeError(f"YouTube API 호출 중 오류가 발생했어요: {getattr(e, 'status_code', '')}") from e
    except Exception as e:  # 네트워크 등
        raise YouTubeError(f"YouTube 에 연결하지 못했어요 ({type(e).__name__}).") from e

    by_id = {v["id"]: v for v in vids.get("items", [])}
    out = []
    for vid in ids:  # 검색 순위 유지
        v = by_id.get(vid)
        if not v:
            continue
        out.append({
            "id": vid,
            "title": v["snippet"].get("title", ""),
            "channel": v["snippet"].get("channelTitle", ""),
            "views": int(v.get("statistics", {}).get("viewCount", 0) or 0),
            "url": watch_url(vid),
        })
    return out


def analyze(engine, api_key: str, artist: str, title: str) -> dict:
    """곡 하나에 대한 유튜브 분석 결과.

    반환: {query, cached, videos, top, official(Official|None), same(bool)}
    """
    query = f"{artist} {title}".strip()
    cache_key = f"{' '.join(query.lower().split())}|n={MAX_RESULTS}"
    videos = db.cache_get(engine, cache_key, CACHE_TTL_DAYS)
    cached = videos is not None
    if videos is None:
        videos = _fetch(api_key, query)
        db.cache_put(engine, cache_key, videos)
    top = pick_most_viewed(videos)
    official = pick_official(videos, artist, title)
    same = bool(top and official and top["id"] == official.video["id"])
    return {"query": query, "cached": cached, "videos": videos, "top": top,
            "official": official, "same": same}
