from youtube import pick_most_viewed, pick_official, score_official


def V(i, title, channel, views):
    return {"id": i, "title": title, "channel": channel, "views": views, "url": f"u/{i}"}


VIDEOS = [
    V("cover", "BTS Dynamite (Piano Cover)", "PianoGuy", 9_000_000),
    V("mv", "BTS (방탄소년단) 'Dynamite' Official MV", "HYBE LABELS", 1_800_000_000),
    V("lyr", "BTS - Dynamite (Lyrics) 가사", "LyricsTube", 50_000_000),
    V("react", "BTS Dynamite REACTION", "Reactor", 70_000_000),
]


def test_most_viewed_and_official():
    assert pick_most_viewed(VIDEOS)["id"] == "mv"
    off = pick_official(VIDEOS, "BTS", "Dynamite")
    assert off and off.video["id"] == "mv"


def test_negative_keywords_penalize():
    s, why = score_official(VIDEOS[2], "BTS", "Dynamite")
    assert s < 0 and any("lyrics" in w for w in why)


def test_no_official_when_below_threshold():
    assert pick_official([VIDEOS[0], VIDEOS[3]], "BTS", "Dynamite") is None


def test_vevo_and_topic():
    s, _ = score_official(V("x", "Song", "ArtistVEVO", 1), "Artist", "Song")
    assert s >= 4
    s2, _ = score_official(V("y", "Song", "Artist - Topic", 1), "Artist", "Song")
    assert s2 >= 4
