import pytest

import db
from cleanup import plan_name_fixes


@pytest.fixture()
def eng():
    return db.make_engine("sqlite://")


def _seed(eng):
    rows = [("", "아이유: 좋은 날"), ("", "BTS - Dynamite"), ("", "- 앞에 하이픈"), ("", "그냥 제목"),
            ("Coldplay", "Yellow: Live"),               # 가수가 있으면 건드리지 않음
            ("", "Mission: Impossible Theme")]          # 오인되는 케이스(사용자가 후보에서 제외)
    for a, t in rows:
        db.add_song(eng, a, t, "ko", "used")
    return db.list_songs(eng, newest_first=False)


def test_plan_only_empty_artist_changed_rows(eng):
    plan = plan_name_fixes(_seed(eng))
    got = {p["old_title"]: (p["artist"], p["title"]) for p in plan}
    assert got == {"아이유: 좋은 날": ("아이유", "좋은 날"), "BTS - Dynamite": ("BTS", "Dynamite"),
                   "- 앞에 하이픈": ("", "앞에 하이픈"), "Mission: Impossible Theme": ("Mission", "Impossible Theme")}


def test_apply_updates_and_dedupe_keys(eng):
    plan = plan_name_fixes(_seed(eng))
    res = db.apply_name_fixes(eng, plan)
    assert res["updated"] == 4 and res["skipped"] == []
    by = {s["title"]: s["artist"] for s in db.list_songs(eng)}
    assert by["좋은 날"] == "아이유" and by["Dynamite"] == "BTS"
    # 정리 뒤에는 새 표기로 중복이 판별된다
    assert not db.add_song(eng, "bts", "dynamite (Official MV)", "en", "used")["added"]


def _raw_insert(eng, artist, title, key):
    """norm_key 가 일관되지 않은 데이터(예전 버전/수동 입력)를 흉내 내려고 DB 에 직접 넣는다."""
    from datetime import datetime, timezone
    from sqlalchemy import insert
    with eng.begin() as conn:
        conn.execute(insert(db.songs).values(artist=artist, title=title, language="ko", status="used",
                                             added_at=datetime.now(timezone.utc), norm_key=key))


def test_apply_skips_clashes(eng):
    _raw_insert(eng, "Dynamite", "BTS", "dynamitebts")        # 순서가 뒤집힌 같은 곡이 이미 있음
    _raw_insert(eng, "", "BTS - Dynamite", "k-old-1")          # 정리하면 위 곡과 같아짐 → 건너뜀
    _raw_insert(eng, "", "IU: Good Day", "k-old-2")
    _raw_insert(eng, "", "IU - Good Day", "k-old-3")           # 같은 배치 안에서 서로 충돌 → 나중 것 건너뜀
    fixes = plan_name_fixes(db.list_songs(eng, newest_first=False))
    res = db.apply_name_fixes(eng, fixes)
    assert res["updated"] == 1 and len(res["skipped"]) == 2
    assert any(sk["existing"]["title"] == "BTS" for sk in res["skipped"])
    assert len(db.list_songs(eng)) == 4                        # 아무것도 삭제되지 않음


def test_key_unchanged_for_normal_rows(eng):
    # 구분자는 키에서 지워지므로, 정리해도 중복 판별 결과는 같다
    db.add_song(eng, "", "아이유: 좋은 날", "ko", "used")
    before = db.list_songs(eng)[0]["norm_key"]
    db.apply_name_fixes(eng, plan_name_fixes(db.list_songs(eng)))
    assert db.list_songs(eng)[0]["norm_key"] == before
