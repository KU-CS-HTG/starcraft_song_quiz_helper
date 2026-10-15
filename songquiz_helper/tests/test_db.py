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


def test_update_song_recomputes_key_and_blocks_clash(eng):
    # 구분자 없이 올라가서 가수가 비어 있는 곡
    db.add_song(eng, "", "BTS-Dynamite", "en", "used")
    db.add_song(eng, "IU", "Good Day", "ko", "used")
    sid = next(s["id"] for s in db.list_songs(eng) if s["title"] == "BTS-Dynamite")

    assert db.update_song(eng, sid, "BTS", "Dynamite", "ko", "http://y")["updated"]
    s = next(s for s in db.list_songs(eng) if s["id"] == sid)
    assert (s["artist"], s["title"], s["language"], s["youtube_url"]) == ("BTS", "Dynamite", "ko", "http://y")
    # 수정 뒤에는 새 표기로 중복이 판별된다
    assert not db.add_song(eng, "bts", "dynamite (Official MV)", "en", "used")["added"]

    # 다른 곡과 같아지는 수정(순서 뒤바뀜 포함)은 거부
    other = next(s["id"] for s in db.list_songs(eng) if s["artist"] == "IU")
    r = db.update_song(eng, other, "Dynamite", "BTS", "en")
    assert not r["updated"] and r["existing"]["id"] == sid

    # 자기 자신과 같은 표기로 저장(언어만 변경)은 허용, 빈 제목은 오류
    assert db.update_song(eng, sid, "BTS", "Dynamite", "en")["updated"]
    with pytest.raises(ValueError):
        db.update_song(eng, sid, "BTS", "  ", "en")


def test_bulk_language_update_for_existing(eng):
    db.add_songs_bulk(eng, [{"artist": "IU", "title": "Good Day", "language": "en"},
                            {"artist": "A", "title": "x", "language": "en"}], "used")
    rows = [{"artist": "IU", "title": "Good Day", "language": "ko", "explicit": True},
            {"artist": "A", "title": "x", "language": "ja", "explicit": False}]  # 확정 아님 → 건드리지 않음
    r0 = db.add_songs_bulk(eng, rows, "used")
    assert r0["language_updated"] == 0                              # 옵션을 켜지 않으면 변경 없음
    r1 = db.add_songs_bulk(eng, rows, "used", update_language=True)
    assert r1["added"] == 0 and r1["language_updated"] == 1
    langs = {s["artist"]: s["language"] for s in db.list_songs(eng)}
    assert langs == {"IU": "ko", "A": "en"}
