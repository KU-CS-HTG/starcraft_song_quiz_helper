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


def parse_txt(data: bytes) -> list[dict]:
    """한 줄에 "가수 - 제목". 빈 줄/# 주석은 무시."""
    rows = []
    for line in decode_bytes(data).splitlines():
        line = _NUM_PREFIX.sub("", line).strip()
        if not line or line.startswith("#"):
            continue
        artist, title = parse_line(line)
        rows.append({"artist": artist, "title": title})
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
