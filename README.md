# WADIPASS · SCARNON Maker Report (GitHub Pages)

SCARNON 메이커 리포트만 공개하는 GitHub Pages 전용 버전입니다.
관리자 페이지와 다른 메이커 페이지는 포함하지 않습니다.

## 구조
- `index.html` : SCARNON 메이커 페이지
- `assets/` : 기존 WADIPASS CSS/JS
- `data/` : 페이지가 읽는 분석 결과 JSON
- `python/` : 기존 Python 분석 로직 + 정적 JSON 생성기
- `.github/workflows/update-data.yml` : 15분마다 데이터를 다시 생성

## 1. GitHub에 업로드
새 저장소를 만들고 이 ZIP의 **내용물 전체**를 저장소 루트에 업로드하세요.

## 2. Google Sheet 주소 등록
GitHub 저장소 → Settings → Secrets and variables → Actions → Variables → New repository variable

- Name: `WADIPASS_GOOGLE_SHEET_URL`
- Value: 실제 설문 Google Sheet URL

`python/settings.json`에도 현재 Sheet URL이 기본값으로 들어 있어 같은 Sheet를 계속 쓴다면 생략할 수 있습니다.

## 3. NAVER API 키 등록
GitHub 저장소 → Settings → Secrets and variables → Actions → Secrets → New repository secret

- `WADIPASS_NAVER_CLIENT_ID`
- `WADIPASS_NAVER_CLIENT_SECRET`

절대로 API 키를 소스코드나 settings.json에 직접 넣지 마세요.

## 4. 첫 데이터 갱신
GitHub 저장소 → Actions → `Update SCARNON data` → Run workflow

성공하면 `data/scarnon.json`, `data/market.json`, `data/status.json`이 자동 갱신됩니다.
이후 기본 설정은 15분마다 자동 갱신입니다.

## 5. GitHub Pages 켜기
Settings → Pages → Build and deployment → Source를 `Deploy from a branch`로 선택

- Branch: `main`
- Folder: `/ (root)`

저장하면 다음 형태의 주소가 만들어집니다.

`https://깃허브아이디.github.io/저장소이름/`

이 주소를 SCARNON 메이커에게 전달하면 됩니다.

## 중요: 접근 보안
GitHub Pages는 정적 공개 사이트이므로 기존 FastAPI의 서버측 토큰 인증과 동일한 보안을 제공하지 않습니다.
이 배포본에는 원시 설문 전체가 아니라 SCARNON 메이커 리포트에 이미 노출되던 집계/코멘트 결과만 저장합니다.
민감하거나 비공개로 유지해야 하는 결과라면 GitHub Pages 단독 배포 대신 인증 가능한 호스팅을 사용하세요.
