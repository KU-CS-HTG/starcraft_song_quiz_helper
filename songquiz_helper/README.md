# 🎵 스타크래프트 노래맞추기 도우미

스타크래프트 "노래맞추기" 유즈맵을 만들 때 쓰는 개인용 웹앱입니다.
PC·노트북·휴대폰 어디서든 URL로 접속하고, 데이터는 클라우드 DB(Supabase PostgreSQL)에 저장되어 항상 동기화됩니다.

- **노래 검색**: 이미 활용한 곡인지 판별(순서 바뀜·괄호·feat. 등 무시) + 유튜브 링크 2개(조회수 최고 / 공식 추정)
- **활용한 노래 관리**: CSV·XLSX·TXT 업로드, 중복 건너뛰기, 목록 관리
- **노래 추천**: Claude가 취향을 분석해 언어별 10곡 추천 (과거 추천 곡은 다시 나오지 않음)
- **활용할 노래들**: 마음에 든 곡 저장, 활용 완료 처리
- **200곡 팩**: 200곡 단위 팩 관리, 진행도·언어 비율, CSV/TXT 내보내기

## 폴더 구조

```
(저장소 루트)
├── .gitignore                  # secrets.toml 등 비밀 파일 제외
└── songquiz_helper/
    ├── app.py                  # 진입점: 비밀번호 화면 + 사이드바 메뉴
    ├── auth.py                 # 비밀번호 로그인 + 로그인 유지(서명 쿠키)
    ├── config.py               # 상수(팩 크기, 언어), secrets 읽기
    ├── db.py                   # ★ DB 접근은 전부 여기 (엔진, 테이블, 모든 SQL)
    ├── normalize.py            # 정규화 / 중복 판별 / 언어 감지
    ├── parsers.py              # TXT·CSV·XLSX 업로드 파싱
    ├── youtube.py              # 유튜브 검색, 공식 추정 점수, DB 캐시
    ├── recommend.py            # Claude 추천 (모델명 상수는 이 파일 상단)
    ├── views/                  # 화면 (검색 / 활용한 노래 / 추천 / 활용할 노래들 / 팩)
    ├── tests/                  # 테스트
    ├── requirements.txt
    └── .streamlit/secrets.toml.example
```

> 이 앱은 파일(SQLite 등)에 아무것도 저장하지 않습니다. Streamlit Community Cloud는 재시작 때 파일이 사라지기 때문입니다.

---

## 0. 준비물 (모두 무료로 시작 가능, Anthropic만 유료 크레딧 필요)

| 서비스 | 용도 |
|---|---|
| GitHub 계정 | 코드 저장소 (비공개 권장) |
| Supabase 계정 | PostgreSQL DB |
| Streamlit Community Cloud | 앱 배포 (GitHub 계정으로 로그인) |
| Google Cloud 계정 | YouTube Data API v3 키 |
| Anthropic 계정 | Claude API 키 |

## 1. 계정 만들기

### 1-1. GitHub
1. <https://github.com> 에서 가입합니다.
2. 오른쪽 위 **+ → New repository** 에서 저장소를 만들고 **Private**(비공개)을 선택합니다.

### 1-2. Supabase
1. <https://supabase.com> → **Start your project** → GitHub 계정으로 가입합니다.

### 1-3. YouTube Data API 키
1. <https://console.cloud.google.com> 에서 새 프로젝트를 만듭니다.
2. **API 및 서비스 → 라이브러리**에서 `YouTube Data API v3` 를 검색해 **사용**을 누릅니다.
3. **API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → API 키**로 키를 만들고 복사해 둡니다.
4. (권장) 키 편집 화면의 **API 제한사항**에서 `YouTube Data API v3` 만 허용하도록 제한합니다.
   - 검색 1회(`search.list`)는 100 쿼터, 하루 기본 10,000 쿼터입니다. 같은 검색은 DB에 캐시되어 다시 호출하지 않습니다.

### 1-4. Anthropic API 키
1. <https://console.anthropic.com> 에서 가입하고 **Billing**에서 크레딧을 충전합니다.
2. **API Keys → Create Key** 로 키를 만들어 복사해 둡니다. (한 번만 보여줍니다)
3. 사용 모델을 바꾸고 싶으면 `songquiz_helper/recommend.py` 맨 위의 `CLAUDE_MODEL` 값을 수정합니다.

## 2. DB 생성 (Supabase)

1. Supabase 대시보드에서 **New project** 를 누릅니다.
   - Name: 아무거나 / **Database Password**: 강한 비밀번호를 정하고 **꼭 따로 저장**해 두세요.
   - Region: 가까운 곳(예: Northeast Asia - Seoul) 선택 → **Create new project** (1~2분 소요)
2. 프로젝트가 만들어지면 위쪽의 **Connect** 버튼을 누릅니다.
3. **Connection pooler** 항목(Transaction pooler 또는 Session pooler)의 URI를 복사합니다.
   ```
   postgresql://postgres.xxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres
   ```
   - `[YOUR-PASSWORD]` 를 위에서 정한 DB 비밀번호로 바꿉니다.
   - 비밀번호에 `@ : / # ?` 같은 특수문자가 있으면 URL 인코딩해야 합니다 (예: `@` → `%40`). 번거로우면 영문+숫자 비밀번호로 새로 설정하세요.
   - Direct connection(db.xxx.supabase.co)은 IPv6 전용이라 Streamlit Cloud에서 연결이 안 될 수 있습니다. **반드시 pooler URL**을 쓰세요.
4. **테이블은 직접 만들 필요가 없습니다.** 앱을 처음 실행하면 `songs`, `recommended_history`, `youtube_cache` 테이블과 인덱스가 자동으로 만들어집니다 (`CREATE TABLE IF NOT EXISTS`).

## 3. 로컬에서 먼저 실행해 보기

Python 3.10 이상이 필요합니다.

```bash
cd songquiz_helper
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# secrets.toml 을 열어 4가지 값을 채웁니다 (DATABASE_URL 은 위 Supabase pooler URL 그대로)

streamlit run app.py
```

브라우저에서 <http://localhost:8501> 이 열리면 `APP_PASSWORD` 로 입장합니다.

- 키가 비어 있어도 앱은 죽지 않고 해당 기능에만 안내 메시지가 나옵니다. (`APP_PASSWORD` 가 없으면 보안을 위해 접속 자체를 막습니다.)
- `.streamlit/secrets.toml` 은 `.gitignore` 에 들어 있어 GitHub에 올라가지 않습니다.

테스트 실행 (DB·API 키 불필요, SQLite 인메모리 사용):

```bash
python -m pytest -q
```

## 4. GitHub에 올리기

저장소 루트(= `songquiz_helper/` 의 부모 폴더)에서:

```bash
git add .
git status        # secrets.toml 이 목록에 없는지 꼭 확인!
git commit -m "노래맞추기 도우미"
git remote add origin https://github.com/<내아이디>/<저장소이름>.git
git push -u origin main
```

> ⚠️ 실수로 키를 올렸다면 저장소를 지우는 것으로는 부족합니다. 해당 키를 즉시 폐기(재발급)하세요.

## 5. Streamlit Community Cloud 배포

1. <https://share.streamlit.io> 에 GitHub 계정으로 로그인합니다. (비공개 저장소는 처음에 접근 권한 허용이 필요합니다)
2. **Create app → Deploy a public app from GitHub** 를 선택합니다. (저장소가 비공개여도 앱 자체는 비밀번호로 보호됩니다)
3. 아래처럼 입력합니다.
   - Repository: 방금 올린 저장소
   - Branch: `main`
   - Main file path: `songquiz_helper/app.py`
   - App URL: 원하는 주소 (이 URL로 어디서든 접속)
4. **Advanced settings → Python version** 은 3.11 이상을 권장합니다.
5. **Advanced settings → Secrets** 칸에 아래 형식으로 붙여넣습니다 (값은 본인 것으로):

   ```toml
   APP_PASSWORD = "내가-정한-접속-비밀번호"
   YOUTUBE_API_KEY = "AIza..."
   ANTHROPIC_API_KEY = "sk-ant-..."
   DATABASE_URL = "postgresql://postgres.xxxxxxxxxxxx:비밀번호@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres"
   ```
6. **Deploy** 를 누르면 몇 분 뒤 앱이 열립니다. 비밀번호 입력 후 사용하세요.
7. 휴대폰에서도 같은 URL로 접속하면 됩니다. 홈 화면에 추가하면 앱처럼 쓸 수 있어요.

Secrets 는 나중에도 앱 메뉴(**Settings → Secrets**)에서 수정할 수 있습니다.

## 사용 팁

- **로그인 유지**: 한 번 로그인하면 이 브라우저에서 30일 동안 새로고침·재접속해도 비밀번호를 다시 묻지 않습니다. 사이드바의 **로그아웃**을 누르면 바로 해제됩니다. `APP_PASSWORD` 를 바꾸면 모든 기기의 로그인이 풀립니다. 공용 PC에서는 사용 후 꼭 로그아웃하세요.
- **곡 수정**: 활용한 노래 관리 / 활용할 노래들 / 200곡 팩 화면의 표에서 곡을 **하나** 선택하면 아래에 수정 폼이 나옵니다. 가수·제목·언어·유튜브 링크를 고칠 수 있고, `가수↔제목 바꿔서 저장` 버튼으로 순서가 뒤집힌 곡을 한 번에 고칠 수 있어요. TXT 에서 ` - ` 구분이 없어 가수가 비어 버린 곡은 `가수가 비어 있는 곡만 보기`로 모아서 고치세요. 수정하면 중복 판별 기준도 새 표기로 갱신됩니다.
- **업로드 형식**: TXT 는 한 줄에 `가수 - 제목` (앞에 `1.` 같은 번호가 있어도 됩니다 — 팩 내보내기 파일을 다시 올려도 OK). CSV/XLSX 는 화면에서 가수·제목 컬럼을 고릅니다.
- **중복 판별 규칙**: 소문자화 → 괄호 안 내용, `feat.`/`ft.`, `Remastered`, `Official MV`, `- Live` 제거 → 특수문자·공백 제거 → `가수+제목` 비교(순서 바뀜 허용). 유사도 90 이상이면 "비슷한 곡"으로 따로 표시합니다.
- **팩 규칙**: 활용할 노래는 가장 앞의 안 찬 팩부터 채워지고, 200곡이 차면 다음 팩이 자동 생성됩니다. `활용 완료`로 바꾼 곡은 팩에서 빠집니다.
- **유튜브 공식 추정**: 점수제이며 근거와 기준표가 화면에 표시됩니다. 최종 판단은 직접 해 주세요.
- **추천 결과의 실존 여부**: AI가 없는 곡을 지어낼 수 있으니 `유튜브 확인` 버튼으로 꼭 확인하세요.
- **비용**: 추천 1회는 Claude 요청 1~3회입니다. 취향 목록은 요약해서 보내 토큰을 아낍니다.
- 한동안 접속이 없으면 Streamlit Cloud가 앱을 잠재울 수 있습니다. 접속하면 다시 깨어납니다 (데이터는 DB에 있어 안전합니다).
