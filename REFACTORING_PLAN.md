# Ghost Protocol 리팩토링 기획안

## 1. 목적

이 문서는 Ghost Protocol v5 계열 코드베이스를 안정적으로 확장하고 유지보수할 수 있도록, 현재 구조의 문제를 정리하고 단계별 리팩토링 실행 계획을 제안한다.

이번 기획안의 핵심 목표는 다음 네 가지다.

- `app.py`에 과도하게 집중된 책임을 분리한다.
- UI, 상태 관리, 백그라운드 실행, 도메인 로직의 경계를 명확히 한다.
- 회귀 위험을 줄이기 위해 테스트 가능한 구조로 옮긴다.
- 현재 기능을 멈추지 않고 점진적으로 이행할 수 있는 순서를 만든다.

## 2. 현재 구조 진단

### 관찰 요약

- 메인 진입점은 `app.py`이며, 현재 UI 렌더링과 실행 제어의 실질적 허브다.
- 코어 모듈은 `ghost_protocol/scraper.py`, `ghost_protocol/brain.py`, `ghost_protocol/poster.py`, `ghost_protocol/database.py`, `ghost_protocol/cycle_memory.py`로 나뉘어 있다.
- 그러나 실제 런타임 흐름은 상당 부분 `app.py` 내부 함수와 세션 상태, 스레드 워커에 강하게 묶여 있다.

### 주요 문제

#### 2.1 `app.py`의 책임 과밀

`app.py`는 현재 다음 역할을 동시에 수행한다.

- Streamlit 페이지 초기화와 스타일 주입
- 세션 상태 초기화와 갱신
- 인텔 분석 실행
- 배치 생성 실행
- 연재 포스팅 실행
- 백그라운드 스레드 관리
- 로그/모니터링 렌더링
- 차트/CSV 다운로드 구성
- 검수 보드 렌더링

이 구조는 기능 추가 시 영향 범위를 크게 만들고, 작은 수정도 UI/실행 로직/상태 로직을 함께 건드리게 만든다.

#### 2.2 UI와 실행 로직의 강한 결합

현재 워커 함수들이 Streamlit 세션 상태와 밀접하게 연결되어 있다.

- UI 이벤트가 곧바로 워커 실행으로 연결된다.
- 워커 상태가 `st.session_state` 구조에 직접 반영된다.
- 중간 산출물과 화면 표시 형식이 함께 설계되어 있다.

이 때문에 CLI 실행, 배치 실행, 테스트 더블 주입 같은 대체 실행 경로를 만들기 어렵다.

#### 2.3 백그라운드 스레드 계약이 암묵적임

현재 스레드 워커들은 함수 인자, 세션 상태 키, 로그 콜백, stop event에 의존하는데 계약이 문서화되어 있지 않다.

- 어떤 입력이 필수인지 한눈에 알기 어렵다.
- 실패 상태와 종료 상태의 표현이 통일되지 않다.
- 스레드 간 공유 데이터의 책임이 분산되어 있다.

#### 2.4 구성 데이터와 도메인 규칙의 분산

다음과 같은 규칙이 여러 위치에 분산되어 있다.

- 페르소나 구성
- 톤/길이 옵션 매핑
- 반복 방지 규칙
- 감성 드리프트 보정
- 프롬프트 템플릿과 JSON 설정

일부는 `app.py`, 일부는 `cycle_memory.py`, 일부는 `prompts/*.json`, 일부는 `brain.py`에 있어 변경 지점 파악이 어렵다.

#### 2.5 테스트 진입점 부족

현재 자동 테스트 스위트가 보이지 않고, 다음 영역은 특히 회귀 위험이 크다.

- lineup 생성 규칙
- cycle memory 업데이트
- prompt rendering
- DB migration / UPSERT
- worker 상태 전이

## 3. 리팩토링 원칙

이번 리팩토링은 전면 재작성보다 "기능 유지형 분해"를 원칙으로 한다.

- 기능 동결 없이 단계적으로 이동한다.
- 먼저 경계를 만들고, 나중에 내부 구현을 정리한다.
- Streamlit 의존성을 도메인 계층 밖으로 밀어낸다.
- 스레드/세션 상태를 타입 있는 구조체로 치환한다.
- 외부 I/O는 얇은 어댑터로 감싼다.

## 4. 목표 아키텍처

권장하는 목표 구조는 아래와 같다.

```text
ghost_protocol/
  app/
    streamlit_app.py
    ui/
      layout.py
      fragments.py
      components.py
      formatters.py
    state/
      session.py
      view_models.py
  application/
    orchestrators/
      intel_service.py
      batch_service.py
      launch_service.py
    workers/
      intel_worker.py
      batch_worker.py
      post_worker.py
    dto.py
  domain/
    lineup.py
    cycle_policy.py
    generation_policy.py
    models.py
  infrastructure/
    scraper_client.py
    brain_client.py
    poster_client.py
    repository.py
    prompt_store.py
    logging.py
  shared/
    config.py
    paths.py
```

### 계층 역할

- `app/`: Streamlit 전용 코드
- `application/`: 유스케이스 조합, 워커 실행, 상태 전이
- `domain/`: 순수 로직과 정책
- `infrastructure/`: Playwright, Gemini, SQLite, 파일, 프롬프트 I/O
- `shared/`: 설정과 공용 유틸

## 5. 우선순위

### 1순위

- `app.py` 분해
- 워커 계약 명문화
- 세션 상태 구조 정리

### 2순위

- 도메인 로직 추출
- 프롬프트/페르소나/라인업 정책 이동
- 테스트 기반 마련

### 3순위

- 인프라 어댑터 일원화
- 로깅/모니터링 모델 정리
- CLI 또는 headless entrypoint 확장

## 6. 단계별 실행 계획

### Phase 0. 안전장치 추가

목표는 리팩토링 도중 기능 회귀를 빨리 감지할 최소한의 가드를 마련하는 것이다.

작업 항목:

- `tests/` 디렉터리 추가
- `domain` 후보 순수 함수에 대한 스냅샷성 테스트 작성
- `database.py`의 핵심 쿼리와 UPSERT에 대한 smoke test 작성
- prompt 렌더링 테스트 작성
- worker 입력/출력 샘플 fixture 정리

완료 기준:

- CI가 없어도 로컬에서 빠르게 돌릴 수 있는 최소 테스트 묶음이 존재한다.
- 이후 분리 작업에서 가장 위험한 규칙 로직을 검증할 수 있다.

### Phase 1. `app.py`를 화면 코드와 실행 코드로 분리

목표는 가장 큰 결합점인 `app.py`를 먼저 쪼개는 것이다.

작업 항목:

- `streamlit_app.py`를 새 엔트리로 만들고, 기존 `app.py`는 임시 호환 래퍼로 축소
- CSS/레이아웃/fragment 렌더링을 `app/ui/*`로 이동
- `_init_state()`와 관련 세션 상태 유틸을 `app/state/session.py`로 이동
- `render_terminal`, `_build_intel_fig`, `_format_scripts_for_copy` 같은 뷰 헬퍼를 `app/ui/formatters.py`로 이동

완료 기준:

- UI 렌더 함수가 한 파일에 몰려 있지 않다.
- Streamlit 관련 import가 도메인/인프라 계층에 퍼지지 않는다.

### Phase 2. 워커 실행 계층 정리

목표는 백그라운드 워커를 UI 바깥으로 빼고 실행 계약을 명확히 하는 것이다.

작업 항목:

- `_intel_worker`, `_batch_gen_worker`, `_post_exec_worker`, `_swarm_worker`를 `application/workers/*`로 분리
- worker 입력을 dataclass 또는 TypedDict로 정의
- worker 결과를 `status`, `message`, `payload`, `metrics`, `error` 형태의 공통 구조로 통일
- stop event, log callback, queue 사용 패턴을 표준화

완료 기준:

- 워커 모듈이 Streamlit 없이도 호출 가능하다.
- 워커 시작과 상태 조회가 일관된 인터페이스를 가진다.

### Phase 3. 도메인 정책 추출

목표는 테스트하기 쉬운 순수 로직을 `app.py`에서 떼어내는 것이다.

우선 추출 대상:

- `_fix_consecutive_same`
- `_fix_consecutive_hot`
- `_sample_capped`
- `_build_balanced_lineup`
- cycle memory 정책과 sentiment drift 관련 판단
- 슬롯 다양성 검사 로직

권장 파일:

- `domain/lineup.py`
- `domain/cycle_policy.py`
- `domain/validators.py`

완료 기준:

- 라인업 생성과 감성 제어 로직이 순수 함수로 독립한다.
- Streamlit 세션 상태 없이도 테스트 가능하다.

### Phase 4. 설정과 프롬프트 경계 정리

목표는 코드에 섞여 있는 운영 규칙을 설정 계층으로 이동하는 것이다.

작업 항목:

- 페르소나 풀, 톤 맵, 길이 옵션, 감성 티어 규칙을 별도 설정 모듈로 이동
- `prompts/*.json`과 코드 상수 간 책임 구분 재정의
- `prompt_manager.py`를 `infrastructure/prompt_store.py` 성격으로 명확화
- `GhostBrain`이 직접 규칙을 조합하기보다 주입받도록 변경

완료 기준:

- 규칙 변경 시 수정 위치가 예측 가능하다.
- 프롬프트 자산과 생성 정책의 경계가 분명해진다.

### Phase 5. 인프라 레이어 정돈

목표는 외부 의존성을 인터페이스 뒤로 숨기는 것이다.

작업 항목:

- `scraper.py`, `brain.py`, `poster.py`, `database.py`를 직접 호출하지 않고 application service를 통해 접근
- DB 접근을 repository 계층으로 얇게 감싸기
- Playwright 세션, 계정 로딩, 스크린샷 저장, 로그 저장을 adapter로 분리
- 에러 타입을 계층별로 정리

완료 기준:

- 유스케이스 코드가 Playwright/SQLite/Gemini 상세 구현에 덜 의존한다.
- 모킹 가능한 경계가 생긴다.

### Phase 6. 관측성과 운영성 개선

목표는 운영 중 문제를 더 빨리 파악할 수 있게 만드는 것이다.

작업 항목:

- 로그 이벤트 스키마 통일
- 워커별 lifecycle 로그 추가
- 실패 원인 분류 코드 도입
- 상태 패널에서 공통 메트릭을 읽을 수 있는 view model 도입

완료 기준:

- 실패가 "어디서 왜 났는지"를 로그만 보고 좁힐 수 있다.
- UI 모니터링이 내부 구현 세부사항에 덜 묶인다.

## 7. 제안하는 실제 분해 순서

가장 안전한 순서는 아래와 같다.

1. 테스트 최소 가드 추가
2. `app.py`에서 UI 헬퍼/세션 상태 유틸 먼저 이동
3. 워커 함수 분리
4. 라인업/감성 정책 추출
5. 프롬프트/설정 정리
6. 인프라 어댑터 정리

이 순서를 권장하는 이유는, 기능 가시성이 높은 영역부터 경계를 만들고 가장 위험한 I/O 변경은 뒤로 미루기 위해서다.

## 8. 예상 산출물

리팩토링 종료 시점에 기대하는 결과물은 다음과 같다.

- `app.py`는 얇은 진입점 또는 호환 래퍼 수준으로 축소
- 워커 모듈이 독립 파일로 분리
- 순수 도메인 로직에 대한 테스트 존재
- 세션 상태 키가 구조화된 모델로 정리
- 프롬프트/규칙/설정의 수정 지점이 명확해짐

## 9. 위험 요소

### 기능적 위험

- Streamlit fragment 재렌더링 타이밍이 달라질 수 있다.
- 세션 상태 키 이동 중 기존 UI가 깨질 수 있다.
- 워커 분리 중 stop/reset 동작이 달라질 수 있다.

### 운영적 위험

- Playwright 세션 처리와 계정 캐시 로직은 작은 변경도 민감하다.
- DC Inside 대응 로직은 리팩토링보다 안정성 보존이 우선이다.

### 완화 전략

- 각 Phase 종료 후 수동 시나리오 체크리스트를 운영한다.
- UI 변경과 실행 로직 변경을 한 커밋에 섞지 않는다.
- poster/scraper의 I/O 동작은 초기 단계에서 되도록 건드리지 않는다.

## 10. 첫 번째 실행 티켓 제안

바로 시작한다면 첫 작업은 아래 범위가 가장 적절하다.

### Ticket A. `app.py`에서 UI 헬퍼 분리

범위:

- `render_terminal`
- `_format_scripts_for_copy`
- `_build_intel_fig`
- CSV cache wrapper

이유:

- 비교적 부작용이 작다.
- 파일 크기를 즉시 줄일 수 있다.
- 이후 fragment 분리의 발판이 된다.

### Ticket B. 라인업 정책 모듈 추출

범위:

- `_fix_consecutive_same`
- `_fix_consecutive_hot`
- `_sample_capped`
- `_build_balanced_lineup`

이유:

- 순수 함수라서 테스트 작성이 쉽다.
- 생성 품질 규칙의 중심부라 가시적 가치가 크다.

### Ticket C. worker contract 정의

범위:

- batch/intel/post worker 입력 dataclass
- 공통 worker result 구조

이유:

- 이후 리팩토링 전체의 접착제가 된다.
- UI와 실행 계층을 분리하는 첫 기준선이 된다.

## 11. 결론

이 프로젝트는 이미 기능적으로는 고도화되어 있지만, 유지보수성의 병목이 `app.py`와 암묵적 실행 계약에 집중되어 있다. 따라서 이번 리팩토링은 "기능 추가"보다 "경계 재설계"에 초점을 맞춰야 한다.

가장 현실적인 전략은 다음 한 문장으로 요약된다.

"`app.py`에서 화면, 상태, 워커, 정책을 분리하고, 순수 로직부터 테스트 가능한 구조로 옮긴다."
