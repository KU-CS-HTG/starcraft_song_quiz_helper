"""앱 전역 설정과 비밀값(secrets) 읽기."""
import os

import streamlit as st

# 한 팩에 들어가는 곡 수
PACK_SIZE = 200

# 언어 코드 -> 화면 표시 이름
LANGUAGES = {"en": "영어", "ko": "한국어", "ja": "일본어", "기타": "기타"}
# 추천 기능에서 선택 가능한 언어
REC_LANGUAGES = ["en", "ko", "ja"]


def lang_label(code: str) -> str:
    return LANGUAGES.get(code, code or "기타")


def get_secret(name: str) -> str | None:
    """st.secrets 에서 비밀값을 읽는다. 없으면 None.

    secrets.toml 이 아예 없는 로컬 환경에서도 예외 없이 None 을 돌려준다.
    (보조로 같은 이름의 환경변수도 허용 — 코드/깃에는 값이 들어가지 않는다.)
    """
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    if value is None:
        value = os.environ.get(name)
    if value is None:
        return None
    value = str(value).strip()
    return value or None
