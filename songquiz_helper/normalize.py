"""곡 정규화 / 중복 판별 / 언어 감지. (Streamlit·DB 의존 없음 → 단독 테스트 가능)

판별 흐름
1. 정규화: NFKC, 소문자화, 괄호 안 내용 / feat. / Remastered / Official MV / "- Live" 등 제거,
   특수문자·공백 제거.
2. 정확 일치: "가수+제목" 키가 같거나, 가수/제목 순서를 바꾼 키가 같으면 같은 곡.
3. 유사 일치: rapidfuzz 유사도가 SIMILAR_THRESHOLD(90) 이상이면 "비슷한 곡".
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from rapidfuzz import fuzz, process

SIMILAR_THRESHOLD = 90

# ---------------------------------------------------------------- 정규화
_OPEN = "([{（［【〈《「『<"
_CLOSE = ")]}）］】〉》」』>"
_BRACKET_PAIR = re.compile(
    "[" + re.escape(_OPEN) + "][^" + re.escape(_OPEN + _CLOSE) + "]*[" + re.escape(_CLOSE) + "]"
)
_BRACKET_UNCLOSED = re.compile("[" + re.escape(_OPEN) + "].*$")
_FEAT = re.compile(r"\b(?:feat|ft|featuring)\b\.?.*$", re.I)
_NOISE = re.compile(
    r"\d{4}\s*remaster(?:ed)?"
    r"|remaster(?:ed)?(?:\s*\d{2,4})?"
    r"|official\s*(?:music\s*)?(?:video|audio|mv|m/v)"
    r"|music\s*video|lyrics?\s*video|m/v|\bmv\b",
    re.I,
)
_LIVE_TAIL = re.compile(r"[-–—]\s*live\b.*$|\blive\s+version\b", re.I)
_NON_WORD = re.compile(r"[\W_]+", re.U)
_SEP = re.compile(r"\s[-–—]\s")


def clean_text(s: str) -> str:
    """공백은 남기고 군더더기만 제거한 문자열 (토큰 비교용)."""
    s = unicodedata.normalize("NFKC", s or "").lower()
    prev = None
    while prev != s:  # 중첩 괄호까지 반복 제거
        prev = s
        s = _BRACKET_PAIR.sub(" ", s)
    s = _BRACKET_UNCLOSED.sub(" ", s)
    s = _FEAT.sub(" ", s)
    s = _LIVE_TAIL.sub(" ", s)
    s = _NOISE.sub(" ", s)
    return " ".join(_NON_WORD.sub(" ", s).split())


def normalize_text(s: str) -> str:
    """공백·특수문자까지 모두 제거한 비교용 문자열."""
    return clean_text(s).replace(" ", "")


def parse_line(text: str) -> tuple[str, str]:
    """"가수 - 제목" 형식을 (artist, title) 로 분리. 구분자가 없으면 artist 는 빈 문자열."""
    text = (text or "").strip()
    lead = re.match(r"[-–—]\s+", text)  # "- 제목": 가수만 비우고 구분자는 남긴 경우
    if lead:
        return "", text[lead.end():].strip()
    if re.search(r"\s[-–—]$", text):  # "제목 -": 끝에 구분자만 남은 경우
        return "", text[:-1].strip()
    m = _SEP.search(text)
    if not m:
        return "", text
    return text[: m.start()].strip(), text[m.end():].strip()


def keys_for(artist: str, title: str) -> tuple[str, str]:
    """(저장용 norm_key, 가수/제목을 뒤집은 키). 정규화 결과가 비면 원문으로 대체."""
    a, t = normalize_text(artist), normalize_text(title)
    key, swapped = a + t, t + a
    if not key:
        key = swapped = (artist + title).strip().lower() or "?"
    return key, swapped


def make_key(artist: str, title: str) -> str:
    return keys_for(artist, title)[0]


# ---------------------------------------------------------------- 언어 감지
def detect_language(*texts: str) -> str:
    """문자 종류로 언어를 추정: 한글→ko, 가나→ja, 라틴만→en, 한자 위주 등→기타."""
    hangul = kana = han = latin = 0
    for ch in "".join(t or "" for t in texts):
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            hangul += 1
        elif 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF:
            kana += 1
        elif 0x4E00 <= o <= 0x9FFF:
            han += 1
        elif ch.isascii() and ch.isalpha():
            latin += 1
    if hangul and hangul >= kana:
        return "ko"
    if kana:
        return "ja"
    if han:
        return "기타"
    if latin:
        return "en"
    return "기타"


# ---------------------------------------------------------------- 중복 판별
@dataclass
class Match:
    kind: str  # 'exact' | 'similar'
    score: float
    item: dict  # 인덱스에 넣은 원본 dict (artist/title/status 등)

    def label(self) -> str:
        a = self.item.get("artist") or ""
        return f"{a} - {self.item.get('title')}" if a else str(self.item.get("title"))


class SongIndex:
    """artist/title 키를 가진 dict 목록에서 같은/비슷한 곡을 찾는 인덱스."""

    def __init__(self, items: Iterable[dict] = ()):
        self._items: list[dict] = []
        self._exact: dict[str, dict] = {}
        self._keys: list[str] = []
        self._tkeys: list[str] = []
        self._tokens: list[str] = []
        for it in items:
            self.add(it)

    def __len__(self) -> int:
        return len(self._items)

    def add(self, item: dict) -> None:
        artist, title = item.get("artist") or "", item.get("title") or ""
        key = keys_for(artist, title)[0]
        self._items.append(item)
        self._exact.setdefault(key, item)
        self._keys.append(key)
        self._tkeys.append(normalize_text(title))
        self._tokens.append(clean_text(artist + " " + title))

    def find(self, artist: str, title: str) -> Match | None:
        if not self._items:
            return None
        key, swapped = keys_for(artist, title)
        for k in (key, swapped):  # 정확 일치 (순서 바뀜 허용)
            if k in self._exact:
                return Match("exact", 100.0, self._exact[k])

        best: tuple[float, int] | None = None

        def consider(query: str, choices: list[str], scorer=fuzz.ratio) -> None:
            nonlocal best
            if not query:
                return
            r = process.extractOne(query, choices, scorer=scorer, score_cutoff=SIMILAR_THRESHOLD)
            if r and (best is None or r[1] > best[0]):
                best = (r[1], r[2])

        consider(key, self._keys)
        consider(swapped, self._keys)
        consider(clean_text(artist + " " + title), self._tokens, fuzz.token_sort_ratio)
        if not (artist or "").strip():  # 제목만 입력한 경우: 저장된 곡의 제목과도 비교
            consider(key, self._tkeys)
        if best is None:
            return None
        score, idx = best
        return Match("similar", float(score), self._items[idx])
