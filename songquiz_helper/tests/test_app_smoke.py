"""앱 전체 스모크 테스트: 비밀번호 게이트 + 각 화면이 예외 없이 뜨는지 (SQLite 인메모리 사용)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture()
def at(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import db
    db.get_engine.clear()
    t = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=30)
    t.run()
    return t


def _login(at):
    at.text_input[0].set_value("pw")
    at.button[0].click()
    at.run()


def test_password_gate(at):
    assert not at.exception
    at.text_input[0].set_value("wrong")
    at.button[0].click()
    at.run()
    assert any("틀렸" in e.value for e in at.error)
    _login(at)
    assert at.session_state["authed"] is True and not at.exception


@pytest.mark.parametrize("page", ["🔍 노래 검색", "📚 활용한 노래 관리", "🎧 노래 추천", "📋 활용할 노래들", "📦 200곡 팩"])
def test_pages_render(at, page):
    _login(at)
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, at.exception


def test_search_flow_duplicate(at):
    import db
    _login(at)
    db.add_song(db.get_engine(), "BTS", "Dynamite (Official MV)", "en", "used")
    at.sidebar.radio[0].set_value("🔍 노래 검색").run()
    at.text_input[0].set_value("bts dynamite")
    at.button[0].click()
    at.run()
    assert not at.exception
    assert any("이미 활용한 노래입니다" in e.value for e in at.error)


def _seed():
    import db
    e = db.get_engine()
    db.add_songs_bulk(e, [{"artist": f"A{i}", "title": f"T{i}", "language": "ko" if i % 2 else "en"}
                          for i in range(7)], "planned")
    db.add_songs_bulk(e, [{"artist": "U", "title": "used1", "language": "en"}], "used")
    return e


@pytest.mark.parametrize("page", ["📚 활용한 노래 관리", "📋 활용할 노래들", "📦 200곡 팩"])
def test_pages_with_data(at, page):
    _login(at)
    _seed()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, at.exception
    assert len(at.dataframe) >= 1


def test_recommend_flow_with_fakes(at, monkeypatch):
    import json
    import db
    import recommend
    import youtube
    from views import common

    _login(at)
    e = _seed()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("YOUTUBE_API_KEY", "y")
    n = {"i": 0}

    def fake_ask(system, user):
        n["i"] += 1
        import hashlib  # 서로 확실히 다른 이름(유사도 90 미만)을 만들기 위해 해시 사용
        h = lambda x: hashlib.md5(x.encode()).hexdigest()[:10]
        return json.dumps([{"title": h(f"t{n['i']}-{i}"), "artist": h(f"a{n['i']}-{i}"), "reason": "r"}
                           for i in range(13)])

    monkeypatch.setattr(recommend, "make_claude_ask", lambda key: fake_ask)
    video = {"id": "v1", "title": "x Official MV", "channel": "xVEVO", "views": 5, "url": "http://y/v1"}
    monkeypatch.setattr(youtube, "analyze", lambda *a, **k: {
        "query": "q", "cached": True, "videos": [video], "top": video,
        "official": youtube.pick_official([video], "x", "x"), "same": True})

    at.sidebar.radio[0].set_value("🎧 노래 추천").run()
    next(b for b in at.button if "추천 받기" in b.label).click()
    at.run()
    assert not at.exception, at.exception
    assert len(at.session_state["rec_items"]) == 10
    assert len(db.list_history(e)) == 10  # 추천 곡은 모두 기록됨

    # 저장 버튼 → planned 로 저장되고 결과 목록은 유지
    next(b for b in at.button if "마음에 들어요" in b.label).click()
    at.run()
    assert not at.exception and len(at.session_state["rec_items"]) == 10
    assert len(db.list_songs(e, status="planned")) == 8

    # 유튜브 확인 버튼 → 패널 표시 + '활용할 노래들에 추가' 버튼 노출
    next(b for b in at.button if "유튜브 확인" in b.label).click()
    at.run()
    assert not at.exception and any("활용할 노래들에 추가" in b.label for b in at.button)

    # 다시 받아도 이전 추천 곡이 반복되지 않음
    next(b for b in at.button if "추천 받기" in b.label).click()
    at.run()
    keys = {(h["artist"], h["title"]) for h in db.list_history(e)}
    assert len(keys) == len(db.list_history(e)) == 20
