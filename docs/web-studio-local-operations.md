# Web Studio 로컬 운영

Web Studio는 공개 웹 서비스가 아니라 같은 PC에서 실행 중인 Ghost Protocol
worker를 조작하는 loopback control plane이다. 브라우저는 `127.0.0.1`의 FastAPI
프로세스에만 연결하며, Gemini 키·계정 파일·쿠키·Playwright 세션·SQLite 경로를
브라우저로 전달하지 않는다.

## 개발 모드

터미널 1:

```powershell
python -m uvicorn ghost_protocol.api.main:app --host 127.0.0.1 --port 8000
```

터미널 2:

```powershell
Push-Location web
npm install
npm run dev -- --host 127.0.0.1 --port 5173
Pop-Location
```

브라우저에서 `http://127.0.0.1:5173/studio`를 연다. Vite 개발 서버는 `/health`와
`/v1` 요청을 로컬 FastAPI로 proxy한다.

## 단일 로컬 실행

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_web_studio.ps1
```

`web/dist`가 없으면 먼저 번들을 만들고, Uvicorn을 `127.0.0.1:8000`에 실행한다.
이미 포트가 사용 중이면 프로세스를 종료하지 않고 오류를 보고한다. 종료는 실행 중인
터미널에서 `Ctrl+C`로 수행한다.

## 안전 경계

- Web Studio의 v1 Run은 `sample`, `intel`, `rehearsal`만 사용한다.
- 동시에 하나의 Run만 실행하며 두 번째 시작은 `409 active_run`이다.
- `poster.py`, 계정 회전, 자동 게시, 외부 커뮤니티 mutation endpoint는 Web Studio에 연결하지 않는다.
- 실제 커뮤니티 수집·Gemini 호출·세션 접근은 fixture 테스트에 사용하지 않는다.
- 다른 PC에서 접속하는 원격 공개, tunnel, pairing, TLS, 다중 사용자 인증은 별도 설계 없이는 지원하지 않는다.
