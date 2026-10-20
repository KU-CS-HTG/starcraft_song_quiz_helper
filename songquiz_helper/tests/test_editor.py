"""표 편집 내용 비교(collect_edits) 테스트 — 여러 곡을 한꺼번에 고쳤을 때 바뀐 곡만 정확히 골라내는지."""
import numpy as np
import pandas as pd

from views.common import collect_edits

ROWS = [
    {"id": 1, "artist": "Coldplay", "title": "Yellow", "language": "en", "youtube_url": None},
    {"id": 2, "artist": "IU", "title": "Good Day", "language": "en", "youtube_url": "http://a"},
    {"id": 3, "artist": "", "title": "BTS - Dynamite", "language": "기타", "youtube_url": None},
]
TO_CODE = {"영어": "en", "한국어": "ko", "일본어": "ja", "기타": "기타"}


def _df(**over):
    df = pd.DataFrame({"선택": [False] * 3, "가수": ["Coldplay", "IU", ""], "제목": ["Yellow", "Good Day", "BTS - Dynamite"],
                       "언어": ["영어", "영어", "기타"], "유튜브 링크": ["", "http://a", ""]})
    for col, vals in over.items():
        df[col] = vals
    return df


def test_no_edit_means_no_change():
    assert collect_edits(ROWS, _df(), TO_CODE) == ([], [])


def test_multiple_rows_and_columns_changed():
    df = _df(가수=["Coldplay", "아이유", "BTS"], 제목=["Yellow", "좋은 날", "Dynamite"],
             언어=["영어", "한국어", "영어"])
    changes, _ = collect_edits(ROWS, df, TO_CODE)
    assert [c["id"] for c in changes] == [2, 3]          # 안 바뀐 1번 곡은 제외
    assert changes[0] == {"id": 2, "artist": "아이유", "title": "좋은 날", "language": "ko", "youtube_url": "http://a"}
    assert changes[1]["artist"] == "BTS" and changes[1]["language"] == "en"


def test_url_and_whitespace_and_nan_handling():
    df = _df(제목=["Yellow ", "Good Day", "BTS - Dynamite"], 가수=["Coldplay", None, np.nan])  # 공백만 다름 / 비움 / NaN
    df["유튜브 링크"] = ["http://new", "http://a", None]
    changes, _ = collect_edits(ROWS, df, TO_CODE)
    assert {c["id"]: c for c in changes}[1]["youtube_url"] == "http://new"
    assert {c["id"] for c in changes} == {1, 2}           # 2번: 가수를 비움 → 변경, 3번: NaN=빈칸이라 변경 없음


def test_selection_is_separate_from_edits():
    changes, selected = collect_edits(ROWS, _df(선택=[True, False, True]), TO_CODE)
    assert changes == [] and selected == [1, 3]
