"""Claude 를 이용한 언어별 노래 추천.

토큰 절약: 취향 목록은 전부 보내지 않고 (총 곡수/언어 분포 + 아티스트 빈도 상위 + 랜덤 샘플) 로 요약한다.
중복 방지: 제외 목록을 프롬프트에 넣고, 응답도 코드로 한 번 더 걸러낸다(normalize.SongIndex 재사용).
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter
from typing import Callable

from normalize import SongIndex

# ▼ 사용할 Claude 모델. 바꾸고 싶으면 이 값만 수정하세요.
CLAUDE_MODEL = "claude-sonnet-5-5"

BATCH_SIZE = 10        # 한 번에 추천받는 곡 수
MAX_ATTEMPTS = 3       # 걸러져서 모자랄 때 재요청 최대 횟수
EXTRA_PER_REQUEST = 3  # 걸러질 것을 감안해 더 요청하는 여유분
TOP_ARTISTS = 30       # 요약에 넣을 아티스트 빈도 상위 수
SAMPLE_SIZE = 60       # 요약에 넣을 랜덤 샘플 곡 수
EXCLUDE_LIMIT = 500    # 프롬프트 제외 목록 최대 줄 수 (그 이상은 코드 필터가 담당)
MAX_TOKENS = 2500

LANG_NAMES = {"en": "영어(영미권 팝/록 등)", "ko": "한국어(K-pop 등)", "ja": "일본어(J-pop/애니송 등)"}

SYSTEM_PROMPT = (
    "당신은 스타크래프트 '노래맞추기' 유즈맵에 쓸 곡을 고르는 음악 큐레이터입니다. "
    "사용자의 취향 요약을 분석해 비슷한 분위기이면서 대중적으로 알려져 퀴즈로 내기 좋은 곡을 추천합니다. "
    "반드시 실제로 존재하는 곡만 추천하고, 확실하지 않은 곡은 제외하세요. "
    "출력은 JSON 배열 하나뿐이며 다른 설명·마크다운은 쓰지 않습니다."
)


# ---------------------------------------------------------------- 프롬프트 재료
def _fmt(s: dict) -> str:
    return f"{s['artist']} - {s['title']}" if s.get("artist") else s["title"]


def build_taste_summary(songs: list[dict], rng: random.Random | None = None) -> str:
    """취향 목록 요약 (토큰 절약용)."""
    rng = rng or random.Random()
    if not songs:
        return "(아직 취향 데이터가 없습니다. 대중적으로 인기 있는 곡 위주로 추천해 주세요.)"
    langs = Counter(s.get("language") or "기타" for s in songs)
    artists = Counter(s["artist"] for s in songs if s.get("artist"))
    top = ", ".join(f"{a}({n})" for a, n in artists.most_common(TOP_ARTISTS))
    sample = rng.sample(songs, min(SAMPLE_SIZE, len(songs)))
    return (
        f"총 {len(songs)}곡. 언어 분포: " + ", ".join(f"{k} {v}" for k, v in langs.most_common()) + "\n"
        f"자주 등장하는 아티스트(곡 수): {top or '-'}\n"
        "랜덤 샘플:\n" + "\n".join("- " + _fmt(s) for s in sample)
    )


def build_exclude_lines(excluded: list[dict], language: str, extra: list[str] = (),
                        rng: random.Random | None = None) -> list[str]:
    """제외 목록 줄. 같은 언어/미분류 곡을 우선하고 EXCLUDE_LIMIT 으로 자른다."""
    rng = rng or random.Random()
    pri = [s for s in excluded if (s.get("language") or "기타") in (language, "기타")]
    rest = [s for s in excluded if s not in pri]
    rng.shuffle(pri)
    rng.shuffle(rest)
    lines = list(extra) + [_fmt(s) for s in pri + rest]
    return lines[:EXCLUDE_LIMIT]


def build_user_prompt(language: str, taste: str, exclude_lines: list[str], count: int) -> str:
    return (
        f"## 사용자의 취향 요약\n{taste}\n\n"
        f"## 제외 목록 (이미 활용했거나, 활용 예정이거나, 이전에 추천한 곡 — 절대 다시 추천하지 마세요)\n"
        + ("\n".join(f"- {l}" for l in exclude_lines) if exclude_lines else "(없음)") + "\n\n"
        f"## 요청\n{LANG_NAMES.get(language, language)} 곡을 정확히 {count}곡 추천해 주세요.\n"
        "- 가수명과 곡 제목은 해당 곡의 일반적인 공식 표기를 사용하세요.\n"
        "- 같은 가수에 치우치지 않게 다양하게 고르세요.\n"
        "- reason 은 취향과 연결한 한국어 한 문장입니다.\n"
        '- 출력 형식(JSON 배열만): [{"title": "...", "artist": "...", "language": "'
        + language + '", "reason": "..."}]'
    )


def parse_response(text: str) -> list[dict]:
    """응답에서 JSON 배열을 꺼낸다. 코드펜스/앞뒤 설명이 섞여 있어도 허용."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("JSON 배열을 찾지 못했습니다.")
    data = json.loads(text[start:end + 1])
    out = []
    for d in data:
        if isinstance(d, dict) and str(d.get("title", "")).strip():
            out.append({"title": str(d["title"]).strip(), "artist": str(d.get("artist", "")).strip(),
                        "reason": str(d.get("reason", "")).strip()})
    return out


# ---------------------------------------------------------------- 메인 로직
def make_claude_ask(api_key: str) -> Callable[[str, str], str]:
    """Claude API 호출 함수(system, user → 텍스트)를 만든다."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=90.0)

    def ask(system: str, user: str) -> str:
        msg = client.messages.create(model=CLAUDE_MODEL, max_tokens=MAX_TOKENS, system=system,
                                     messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    return ask


def recommend_songs(language: str, taste_songs: list[dict], excluded: list[dict],
                    ask: Callable[[str, str], str], count: int = BATCH_SIZE,
                    rng: random.Random | None = None) -> dict:
    """언어별 추천.

    taste_songs: 취향 근거(활용한 노래/활용할 노래들 중 체크된 것)
    excluded:    제외 대상 전체(활용함 + 활용 예정 + 과거 추천)
    반환: {"items": [...], "attempts": n, "filtered": 걸러진 수, "shortfall": 부족한 수}
    """
    rng = rng or random.Random()
    index = SongIndex(excluded)
    taste = build_taste_summary(taste_songs, rng)
    kept: list[dict] = []
    extra_lines: list[str] = []
    filtered = attempts = 0
    last_error: Exception | None = None

    while attempts < MAX_ATTEMPTS and len(kept) < count:
        attempts += 1
        need = count - len(kept)
        prompt = build_user_prompt(language, taste,
                                   build_exclude_lines(excluded, language, extra_lines, rng),
                                   need + EXTRA_PER_REQUEST)
        try:
            candidates = parse_response(ask(SYSTEM_PROMPT, prompt))
        except ValueError as e:  # JSON 파싱 실패 → 재요청
            last_error = e
            continue
        for c in candidates:
            line = _fmt(c)
            c["language"] = language
            if index.find(c["artist"], c["title"]) is not None:
                filtered += 1
                extra_lines.append(line)
                continue
            if len(kept) < count:
                kept.append(c)
                index.add(c)
            extra_lines.append(line)

    if not kept and last_error:
        raise ValueError(f"추천 응답을 해석하지 못했어요: {last_error}")
    return {"items": kept, "attempts": attempts, "filtered": filtered,
            "shortfall": max(0, count - len(kept))}
