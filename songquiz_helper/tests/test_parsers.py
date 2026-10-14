import pandas as pd
from parsers import parse_txt, read_table, rows_from_table


def test_txt_with_numbers_and_comments():
    data = "# 메모\n1. BTS - Dynamite\n\n아이유 - 좋은 날\n제목만\n".encode("utf-8-sig")
    rows = parse_txt(data)
    assert rows == [{"artist": "BTS", "title": "Dynamite"}, {"artist": "아이유", "title": "좋은 날"},
                    {"artist": "", "title": "제목만"}]


def test_csv_cp949_and_mapping():
    data = "가수,제목\n방탄소년단,다이너마이트\n".encode("cp949")
    df = read_table(data, "a.csv")
    assert rows_from_table(df, "제목", "가수") == [{"artist": "방탄소년단", "title": "다이너마이트"}]


def test_single_column_mode(tmp_path):
    p = tmp_path / "x.xlsx"
    pd.DataFrame({"곡": ["BTS - Dynamite"]}).to_excel(p, index=False)
    df = read_table(p.read_bytes(), "x.xlsx")
    assert rows_from_table(df, "곡") == [{"artist": "BTS", "title": "Dynamite"}]
