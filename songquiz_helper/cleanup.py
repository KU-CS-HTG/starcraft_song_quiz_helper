"""가수가 비어 있는 곡의 제목에서 '가수 - 제목' / '가수: 제목' 을 다시 분리하는 계획 만들기. (순수 함수)"""
from __future__ import annotations

from normalize import parse_line


def plan_name_fixes(rows: list[dict]) -> list[dict]:
    """가수가 비어 있고, 제목을 다시 해석하면 달라지는 곡만 골라 [{id, old_title, artist, title}] 로 돌려준다.

    - '아이유: 좋은 날' → 가수 '아이유', 제목 '좋은 날'
    - '- 제목' 처럼 구분자만 남은 제목은 구분자를 떼어 낸다.
    - 이미 가수가 있는 곡은 건드리지 않는다.
    """
    out = []
    for r in rows:
        if (r.get("artist") or "").strip():
            continue
        title = (r.get("title") or "").strip()
        artist, new_title = parse_line(title)
        if not new_title or (artist, new_title) == ("", title):
            continue
        out.append({"id": r["id"], "old_title": r["title"], "artist": artist, "title": new_title})
    return out
