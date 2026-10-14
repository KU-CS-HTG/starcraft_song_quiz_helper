import json
import random

from recommend import build_taste_summary, parse_response, recommend_songs


def test_parse_with_fence_and_noise():
    txt = '설명...\n```json\n[{"title":"A","artist":"B","reason":"c"},{"title":""}]\n```'
    assert parse_response(txt) == [{"title": "A", "artist": "B", "reason": "c"}]


def test_summary_is_compact():
    songs = [{"artist": f"a{i % 5}", "title": f"t{i}", "language": "en"} for i in range(1000)]
    s = build_taste_summary(songs, random.Random(1))
    assert "총 1000곡" in s and s.count("\n- ") == 60


def test_filter_and_retry():
    excluded = [{"artist": "BTS", "title": "Dynamite", "language": "en"}]
    calls = []

    def fake_ask(system, user):
        calls.append(user)
        n = len(calls)
        items = [{"title": f"New{n}-{i}", "artist": f"Art{n}-{i}", "reason": "r"} for i in range(5)]
        if n == 1:  # 제외 곡 + 배치 내 중복을 섞어 보냄
            items = [{"title": "Dynamite (Official MV)", "artist": "BTS", "reason": "x"}] + items + [items[0]]
        return json.dumps(items)

    r = recommend_songs("en", [], excluded, fake_ask, count=10, rng=random.Random(0))
    keys = {(i["artist"], i["title"]) for i in r["items"]}
    assert len(r["items"]) == 10 and len(keys) == 10
    assert all(i["artist"] != "BTS" for i in r["items"])
    assert r["filtered"] >= 2 and r["attempts"] == 2
    assert "Art1-0" in calls[1]  # 재요청 때 앞서 받은 곡이 제외 목록에 포함됨


def test_gives_up_after_max_attempts():
    r = recommend_songs("ko", [], [], lambda s, u: "[]", count=10)
    assert r["items"] == [] and r["attempts"] == 3 and r["shortfall"] == 10
