"""중복 판별 테스트.  실행: songquiz_helper/ 폴더에서  python -m pytest -q"""
from normalize import (SongIndex, detect_language, keys_for, normalize_text,
                       parse_line)


def _index(*lines):
    return SongIndex({"artist": a, "title": t} for a, t in map(parse_line, lines))


def test_official_mv_equals_plain_query():
    # 요구사항 예시: 두 표기는 같은 곡이어야 한다
    idx = _index("BTS - Dynamite (Official MV)")
    m = idx.find(*parse_line("bts dynamite"))
    assert m is not None and m.kind == "exact"


def test_swapped_order_is_exact():
    idx = _index("방탄소년단 - 다이너마이트")
    m = idx.find(*parse_line("다이너마이트 - 방탄소년단"))
    assert m and m.kind == "exact"


def test_feat_remaster_live_removed():
    assert normalize_text("Song (feat. Someone)") == normalize_text("Song")
    assert normalize_text("Song feat. Someone") == normalize_text("Song")
    assert normalize_text("Song - Remastered 2011") == normalize_text("Song")
    assert normalize_text("Song - Live at Wembley") == normalize_text("Song")
    assert normalize_text("Song [Official Video]") == normalize_text("Song")
    assert normalize_text("Song (Live)") == normalize_text("Song")


def test_title_with_live_word_kept():
    assert normalize_text("Live Forever") == "liveforever"


def test_special_chars_and_case():
    assert keys_for("A-ha", "Take On Me!")[0] == keys_for("a ha", "take on me")[0]


def test_similar_but_not_exact():
    idx = _index("IU - Good Day")
    m = idx.find("IU", "Good Days")
    assert m and m.kind == "similar" and m.score >= 90


def test_different_songs_not_matched():
    idx = _index("BTS - Dynamite")
    assert idx.find("BTS", "Butter") is None
    assert idx.find("Coldplay", "Yellow") is None


def test_title_only_query_flags_similar():
    idx = _index("BTS - Dynamite")
    m = idx.find("", "Dynamite")
    assert m and m.kind == "similar"


def test_word_order_swapped_freeform():
    idx = _index("BTS - Dynamite")
    assert idx.find("", "dynamite bts") is not None


def test_empty_index():
    assert SongIndex().find("a", "b") is None


def test_parse_line():
    assert parse_line("A-ha - Take On Me") == ("A-ha", "Take On Me")
    assert parse_line("그냥 제목") == ("", "그냥 제목")


def test_detect_language():
    assert detect_language("BTS", "다이너마이트") == "ko"
    assert detect_language("YOASOBI", "夜に駆ける") == "ja"
    assert detect_language("周杰倫", "晴天") == "기타"
    assert detect_language("YOASOBI", "アイドル") == "ja"
    assert detect_language("Coldplay", "Yellow") == "en"


def test_parse_line_blank_artist_variants():
    assert parse_line("제목만") == ("", "제목만")
    assert parse_line(" - 제목") == ("", "제목")
    assert parse_line("- 제목") == ("", "제목")
    assert parse_line("제목 -") == ("", "제목")
    assert parse_line("A-ha - Take On Me") == ("A-ha", "Take On Me")  # 단어 속 하이픈은 그대로


def test_parse_line_colon_separator():
    assert parse_line("BTS: Dynamite") == ("BTS", "Dynamite")
    assert parse_line("BTS : Dynamite") == ("BTS", "Dynamite")
    assert parse_line("아이유:좋은 날") == ("아이유", "좋은 날")      # 공백 없는 콜론
    assert parse_line("아이유：좋은 날") == ("아이유", "좋은 날")      # 전각 콜론
    assert parse_line("A - Title: Sub") == ("A", "Title: Sub")        # 먼저 나온 구분자 기준
    assert parse_line("A: Title - Remix") == ("A", "Title - Remix")
    assert parse_line("Re:Zero - 곡") == ("Re:Zero", "곡")            # 공백 없는 콜론은 하이픈보다 약함
    assert parse_line("제목:") == ("", "제목") and parse_line(": 제목") == ("", "제목")
