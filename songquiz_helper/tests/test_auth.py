from auth import make_token, verify_token


def test_token_roundtrip_and_expiry():
    t = make_token("pw", now=1000, days=1)
    assert verify_token("pw", t, now=1000 + 3600)
    assert not verify_token("pw", t, now=1000 + 86400 + 1)  # 만료


def test_token_rejects_tampering_and_other_password():
    t = make_token("pw", now=1000, days=1)
    exp, sig = t.split(".")
    assert not verify_token("other", t, now=1001)           # 비밀번호가 바뀌면 무효
    assert not verify_token("pw", f"{int(exp) + 999999}.{sig}", now=1001)  # 만료시각 위조
    for bad in (None, "", "abc", "1.2", "x.y"):
        assert not verify_token("pw", bad, now=1001)
