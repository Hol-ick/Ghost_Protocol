# Web Studio 검증 기록

- 검증일: 2026-08-24 KST
- 범위: loopback Web Studio v1과 기존 Ghost Protocol 회귀

## 통과한 검사

| 검사 | 결과 |
|---|---|
| `python -m pytest -q` | 314 passed, 1 warning |
| `python -m pip check` | No broken requirements found |
| 신규 Python 모듈 `py_compile` | 통과 |
| `web/npm ci` | 통과, 취약점 0 |
| `web/npm run build` | Vite production build 통과 |
| Playwright Chromium desktop/mobile | 6 passed |
| `scripts/run_web_studio.ps1 -Port 8123` | loopback Uvicorn 시작·종료 통과 |
| 실제 정적 smoke | `/studio` 200, `/health` 200 |

## fixture 통합 시나리오

가짜 runner로 다음 event sequence를 확인했다.

```text
started → progress → insight → succeeded
```

`after=2` 재조회는 sequence `3, 4`만 반환했고, 두 번째 active Run은
`409 active_run`, 중단 요청은 terminal snapshot으로 수렴했다.

## 확인하지 않은 범위

- 실제 DCInside 수집
- 실제 Gemini 호출 및 비용 ledger 변화
- 계정 파일·쿠키·Playwright 세션 접근
- 실제 게시 또는 외부 커뮤니티 mutation
- 다른 PC에서의 원격 접속·tunnel·TLS·다중 사용자 인증
- GitHub 공개 배포 및 Pages 배포

위 항목은 이번 로컬 fixture/loopback 완료 판정에 포함하지 않았다.
