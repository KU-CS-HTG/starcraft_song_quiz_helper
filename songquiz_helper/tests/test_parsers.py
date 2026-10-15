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


def test_section_headers_assign_language():
    from parsers import parse_txt
    txt = """# 메모는 주석
[한국어]
아이유 - 좋은 날
방탄소년단 - Dynamite

=== 영어 ===
Coldplay - Yellow
------
# 일본어
YOASOBI - アイドル
기타:
제목만
"""
    rows = parse_txt(txt.encode("utf-8"))
    assert [(r["artist"], r["title"], r.get("language")) for r in rows] == [
        ("아이유", "좋은 날", "ko"), ("방탄소년단", "Dynamite", "ko"),   # Dynamite 는 영문이어도 문단 표시가 우선
        ("Coldplay", "Yellow", "en"), ("YOASOBI", "アイドル", "ja"), ("", "제목만", "기타")]


def test_section_name_variants():
    from parsers import section_language as f
    for line, code in [("[한국어]", "ko"), ("한국어:", "ko"), ("## 영어", "en"), ("<일본어>", "ja"),
                       ("--- J-POP ---", "ja"), ("K-pop 노래", "ko"), ("한국어 (120곡)", "ko"),
                       ("English", "en"), ("[기타]", "기타")]:
        assert f(line) == code, line
    for line in ("BTS - Dynamite", "Yellow", "한국어 사랑", "", "-----"):
        assert f(line) is None, line


def test_no_headers_keeps_old_behavior():
    from parsers import parse_txt
    rows = parse_txt("A - B\n".encode())
    assert rows == [{"artist": "A", "title": "B"}]
