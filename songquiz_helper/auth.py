"""비밀번호 로그인 + 로그인 유지(서명된 쿠키).

- 비밀번호가 맞으면 '만료시각.서명' 형태의 쿠키를 브라우저에 저장한다 (비밀번호 자체는 저장하지 않음).
- 서명은 APP_PASSWORD 로 만든 HMAC 이라 위조할 수 없고, APP_PASSWORD 를 바꾸면 기존 로그인은 모두 무효가 된다.
- 새로고침/재접속 때 쿠키가 유효하면 비밀번호 화면을 건너뛴다. 로그아웃하면 쿠키를 지운다.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import streamlit as st
import streamlit.components.v1 as components

from config import get_secret

COOKIE_NAME = "sq_auth"
COOKIE_DAYS = 30


# ---------------------------------------------------------------- 토큰 (순수 함수 — 테스트 가능)
def _sign(secret: str, msg: str) -> str:
    key = ("songquiz-helper:" + secret).encode()
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


def make_token(secret: str, now: float | None = None, days: int = COOKIE_DAYS) -> str:
    expires = str(int((now if now is not None else time.time()) + days * 86400))
    return f"{expires}.{_sign(secret, expires)}"


def verify_token(secret: str, token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expires, sig = token.split(".", 1)
    if not expires.isdigit() or not hmac.compare_digest(sig, _sign(secret, expires)):
        return False
    return int(expires) > (now if now is not None else time.time())


# ---------------------------------------------------------------- 쿠키 입출력
def _run_js_cookie(value: str, max_age: int) -> None:
    """브라우저 쿠키를 설정(또는 max_age=0 으로 삭제). 보이지 않는 작은 컴포넌트로 실행."""
    components.html(
        f"""<script>
        try {{
          var p = window.parent;
          var secure = p.location.protocol === 'https:' ? '; Secure' : '';
          p.document.cookie = "{COOKIE_NAME}={value}; Max-Age={max_age}; Path=/; SameSite=Lax" + secure;
        }} catch (e) {{}}
        </script>""",
        height=0,
    )


def _cookie_token() -> str | None:
    try:
        return st.context.cookies.get(COOKIE_NAME)
    except Exception:
        return None


def flush_cookie_actions() -> None:
    """로그인/로그아웃 직후 한 번만 쿠키를 쓰거나 지운다. 매 실행 맨 앞에서 호출."""
    token = st.session_state.pop("_set_cookie", None)
    if token:
        _run_js_cookie(token, COOKIE_DAYS * 86400)
    if st.session_state.pop("_clear_cookie", False):
        _run_js_cookie("", 0)


# ---------------------------------------------------------------- 게이트 / 로그아웃
def password_gate() -> None:
    """APP_PASSWORD 가 맞아야 진입. 내 API 키가 쓰이므로 비밀번호가 없으면 아예 막는다."""
    expected = get_secret("APP_PASSWORD")
    flush_cookie_actions()
    if st.session_state.get("authed"):
        return
    if expected and not st.session_state.get("logged_out") and verify_token(expected, _cookie_token()):
        st.session_state["authed"] = True  # 쿠키로 자동 로그인
        return

    st.title("🎵 노래맞추기 도우미")
    if not expected:
        st.error("APP_PASSWORD 가 설정되지 않아 접속을 막았어요. Secrets 에 APP_PASSWORD 를 넣어 주세요.")
        st.stop()
    with st.form("login"):
        pw = st.text_input("비밀번호", type="password")
        ok = st.form_submit_button("입장", type="primary")
    if ok:
        if hmac.compare_digest(pw.encode(), expected.encode()):
            st.session_state["authed"] = True
            st.session_state["logged_out"] = False
            st.session_state["_set_cookie"] = make_token(expected)
            st.rerun()
        st.error("비밀번호가 틀렸어요.")
    st.stop()


def logout() -> None:
    """로그아웃: 세션 데이터와 쿠키를 지운다.

    st.context.cookies 는 접속 시점의 값이라 같은 세션에서는 갱신되지 않으므로,
    logged_out 표시로 쿠키 자동 로그인을 막는다 (새로고침하면 지워진 쿠키가 반영됨).
    """
    st.session_state.clear()
    st.session_state["logged_out"] = True
    st.session_state["_clear_cookie"] = True
    st.rerun()
