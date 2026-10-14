"""db.py 로직 테스트 (SQLite 인메모리 사용 — 운영은 PostgreSQL)."""
import pytest

import db
from config import PACK_SIZE


@pytest.fixture()
def eng():
    return db.make_engine("sqlite://")


def test_add_song_and_duplicate(eng):
    assert db.add_song(eng, "BTS", "Dynamite (Official MV)", "en", "used")["added"]
    r = db.add_song(eng, "Dynamite", "BTS", "en", "planned")  # 순서 뒤바뀜도 중복
    assert not r["added"] and r["existing"]["status"] == "used"


def test_bulk_upload_counts(eng):
    rows = [{"artist": "A", "title": "x"}, {"artist": "A", "title": "x (Live)"},
            {"artist": "B", "title": "y"}, {"artist": "", "title": ""}]
    res = db.add_songs_bulk(eng, rows, "used")
    assert (res["added"], len(res["duplicates"]), res["invalid"]) == (2, 1, 1)
    res2 = db.add_songs_bulk(eng, rows, "used")
    assert res2["added"] == 0 and len(res2["duplicates"]) == 3


def test_pack_auto_rollover_and_move(eng):
    rows = [{"artist": "a", "title": f"song{i}", "language": "en"} for i in range(PACK_SIZE + 5)]
    db.add_songs_bulk(eng, rows, "planned")
    assert db.pack_counts(eng) == {1: PACK_SIZE, 2: 5}
    assert db.current_pack_no(eng) == 2
    ids = [s["id"] for s in db.list_songs(eng, pack_no=2)]
    with pytest.raises(ValueError):
        db.move_to_pack(eng, ids, 1)  # 1번 팩은 가득 참
    # 1번 팩에서 한 곡을 빼면(활용 완료) 자리가 생긴다
    first = db.list_songs(eng, pack_no=1, newest_first=False)[0]["id"]
    db.mark_used(eng, [first])
    assert db.move_to_pack(eng, ids[:1], 1) == 1
    assert db.pack_counts(eng) == {1: PACK_SIZE, 2: 4}


def test_mark_used_delete(eng):
    db.add_song(eng, "a", "b", "en", "planned")
    sid = db.list_songs(eng)[0]["id"]
    db.mark_used(eng, [sid])
    s = db.list_songs(eng)[0]
    assert s["status"] == "used" and s["pack_no"] is None
    assert db.delete_songs(eng, [sid]) == 1


def test_history_and_cache(eng):
    n = db.add_history(eng, [{"artist": "a", "title": "t", "language": "ko"},
                             {"artist": "a", "title": "t (feat. z)", "language": "ko"}])
    assert n == 1 and len(db.list_history(eng)) == 1
    assert db.cache_get(eng, "q") is None
    db.cache_put(eng, "q", [{"x": 1}])
    db.cache_put(eng, "q", [{"x": 2}])
    assert db.cache_get(eng, "q") == [{"x": 2}]
    assert db.cache_get(eng, "q", ttl_days=0) is None
