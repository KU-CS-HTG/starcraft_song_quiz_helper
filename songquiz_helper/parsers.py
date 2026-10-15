"""업로드 파일(TXT / CSV / XLSX) 읽기. Streamlit 의존 없음."""
from __future__ import annotations

import io
import re

import pandas as pd

from normalize import parse_line

_NUM_PREFIX = re.compile(r"^\s*\d+\s*[.)]\s+")  # 내보내기 형식 "12. 가수 - 제목" 의 번호 제거

ARTIST_HINTS = ("가수", "아티스트", "artist", "singer", "싱어")
TITLE_HINTS = ("제목", "곡명", "곡", "노래", "title", "song", "track")


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "utf-16"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- TXT 문단(언어) 표시
# 줄 전체가 아래 이름 중 하나이면 "여기서부터 이 언어" 라는 문단 표시로 본다.
# 장식 문자([] # = - : 등)와 '노래/곡/목록', '120곡' 같은 꼬리는 무시한다.
_SECTION_NAMES = {
    "ko": {"한국어", "한글", "한국", "국내", "가요", "국내가요", "한", "ko", "kr", "kor", "korean", "korea", "kpop"},
    "en": {"영어", "영문", "영", "팝송", "미국", "en", "eng", "english", "us", "usa"},
    "ja": {"일본어", "일어", "일본", "일", "제이팝", "ja", "jp", "jpn", "japanese", "japan", "jpop"},
    "기타": {"기타", "etc", "other", "others"},
}
_SECTION_LOOKUP = {name: code for code, names in _SECTION_NAMES.items() for name in names}
_COUNT_TAIL = re.compile(r"\d+\s*곡")
_NAME_TAIL = re.compile(r"(노래들?|곡들?|목록|리스트|모음|songs?|list)$")


def section_language(line: str) -> str | None:
    """문단 표시 줄이면 언어 코드(en/ko/ja/기타), 아니면 None."""
    text = _COUNT_TAIL.sub("", line.strip().lower())
    key = re.sub(r"[\W_]+", "", text)
    key = _NAME_TAIL.sub("", key) or key
    return _SECTION_LOOKUP.get(key)


def parse_txt(data: bytes) -> list[dict]:
    """한 줄에 "가수 - 제목". 빈 줄/# 주석은 무시.

    '[한국어]', '# 영어', '=== 일본어 ===' 같은 문단 표시 줄을 만나면 그 아래 곡들의 language 를
    해당 언어로 지정한다 (다음 표시가 나올 때까지). 표시 이전의 곡은 language 키가 없다.
    """
    rows, section = [], None
    for line in decode_bytes(data).splitlines():
        line = line.strip()
        lang = section_language(line)  # 주석(#) 처리보다 먼저: '# 한국어' 도 표시로 인식
        if lang:
            section = lang
            continue
        line = _NUM_PREFIX.sub("", line).strip()
        if not line or line.startswith("#") or not re.search(r"\w", line):
            continue  # 빈 줄, 주석, '-----' 같은 구분선
        artist, title = parse_line(line)
        row = {"artist": artist, "title": title}
        if section:
            row["language"] = section
        rows.append(row)
    return rows


def sheet_names(data: bytes) -> list[str]:
    return pd.ExcelFile(io.BytesIO(data)).sheet_names


def read_table(data: bytes, filename: str, sheet: str | None = None,
               has_header: bool = True) -> pd.DataFrame:
    """CSV/XLSX → DataFrame (모든 값을 문자열로)."""
    header = 0 if has_header else None
    if filename.lower().endswith((".xlsx", ".xlsm")):
        df = pd.read_excel(io.BytesIO(data), sheet_name=sheet or 0, header=header,
                           dtype=str, engine="openpyxl")
    else:
        df = pd.read_csv(io.StringIO(decode_bytes(data)), sep=None, engine="python",
                         header=header, dtype=str)
    if not has_header:
        df.columns = [f"컬럼{i + 1}" for i in range(len(df.columns))]
    return df.fillna("")


def guess_column(columns: list[str], hints: tuple[str, ...]) -> int | None:
    for i, c in enumerate(columns):
        low = str(c).strip().lower()
        if any(h in low for h in hints):
            return i
    return None


def rows_from_table(df: pd.DataFrame, title_col: str, artist_col: str | None = None) -> list[dict]:
    """매핑된 컬럼으로 행 목록 생성. artist_col 이 None 이면 title_col 을 "가수 - 제목" 으로 해석."""
    rows = []
    for _, r in df.iterrows():
        title = str(r[title_col]).strip()
        if not title:
            continue
        if artist_col:
            rows.append({"artist": str(r[artist_col]).strip(), "title": title})
        else:
            artist, t = parse_line(title)
            rows.append({"artist": artist, "title": t})
    return rows
