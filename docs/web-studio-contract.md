# Ghost Protocol Web Studio 로컬 워커 계약

## 목적

Web Studio는 로컬에서 실행되는 Ghost Protocol worker를 브라우저로 조작하기
위한 얇은 제어면이다. 브라우저는 실행 thread, `queue.Queue`, stop event,
SQLite, Playwright session, 계정 파일에 직접 접근하지 않는다. 이 문서의
계약은 이후 FastAPI control plane과 React UI가 같은 실행 상태를 관찰하도록
고정한다.

## 소유권 경계

```text
Browser UI
    │ JSON snapshot/event
    ▼
FastAPI local control plane
    │ RunSpec / RunEvent
    ▼
LocalWorkerRuntime (one active run)
    │ private thread + stop event
    ▼
worker adapter: run(spec, emit, stop_event) -> None
```

- `LocalWorkerRuntime`은 하나의 active Run만 허용한다.
- worker adapter는 `RunSpec`, 이벤트 emitter, `threading.Event`만 받는다.
- runtime 밖으로 thread, queue, stop event 객체를 반환하지 않는다.
- v1 서버는 `127.0.0.1`에만 바인딩한다. 원격 접속·공개 tunnel·외부 인증은
  이 계약의 범위가 아니다.

## 입력 모델

```python
RunSpec(
    mode="sample",                 # 비어 있지 않은 실행 모드
    params={"pages": 1},            # worker adapter 전용 입력
)
```

`RunSpec`은 생성 시 `mode`를 정리하고 `params`를 복사한다. 호출자가 이후에
원본 dictionary를 변경해도 이미 시작한 Run의 입력은 바뀌지 않는다.

## 상태 모델

| 상태 | 의미 |
| --- | --- |
| `idle` | 저장된 Run이 없거나 active Run이 없는 유휴 상태 |
| `queued` | `start()`가 Run을 등록했고 worker thread가 시작되기를 기다리는 상태 |
| `running` | worker adapter가 실행 중인 상태 |
| `stopping` | 중단 요청이 전달됐고 adapter가 반환하기를 기다리는 상태 |
| `succeeded` | adapter가 예외 없이 반환한 terminal 상태 |
| `failed` | adapter가 예외를 발생시킨 terminal 상태 |
| `stopped` | stop event가 설정된 뒤 adapter가 반환한 terminal 상태 |

`start()` 직후에는 `queued` snapshot이 반환될 수 있다. worker thread가 실행되면
정상 흐름은 `running`과 `started` event를 거쳐 terminal 상태가 된다. 이미
stop 요청이 들어온 경우 `started` event 없이 `stopping → stopped`가 될 수 있다.

## 런타임 인터페이스

```python
runtime = LocalWorkerRuntime(runner=runner)

snapshot = runtime.start(RunSpec(mode="sample", params={}))
snapshot = runtime.snapshot(snapshot.run_id)
events = runtime.events_after(snapshot.run_id, after=0, limit=200)
snapshot = runtime.stop(snapshot.run_id)
```

- `start(spec) -> RunSnapshot`: active Run이 있으면 `ActiveRunError`를 발생시킨다.
- `snapshot(run_id=None) -> RunSnapshot`: id를 생략하면 가장 최근 Run을 조회한다.
- `snapshots() -> list[RunSnapshot]`: 생성 순서대로 현재 저장된 Run을 조회한다.
- `events_after(run_id, after=0, limit=200) -> list[RunEvent]`: cursor보다 큰
  sequence만 반환한다. `limit`은 양수여야 한다.
- `stop(run_id) -> RunSnapshot`: 중단 요청은 idempotent하다. terminal Run에 대한
  호출은 기존 terminal snapshot을 그대로 반환한다.
- 모르는 id는 `RunNotFoundError`를 발생시킨다.

## Worker adapter와 이벤트

adapter는 다음 형태를 사용한다.

```python
def run(spec: RunSpec, emit, stop_event: threading.Event) -> None:
    emit("progress", "수집 중", {"completed": 1, "total": 2})
    if stop_event.is_set():
        return
    emit({
        "kind": "log",
        "message": "fixture complete",
        "payload": {"source": "test"},
    })
```

`emit`은 다음 세 입력을 허용한다.

1. `emit(kind, message, payload)`
2. `emit({"kind": ..., "message": ..., "payload": ...})`
3. `emit(RunEvent(...))`

기존 `worker_contracts.worker_message()`의 `{"type": ..., ...}` dictionary도
받을 수 있다. 이 경우 `type`은 event `kind`가 되고 `data`는 기본 message가
된다. 구체적인 `MSG_*` 의미를 Web Studio 의미로 바꾸는 일은 작업 2의
`studio_event_adapter` 책임이다.

모든 event는 runtime이 sequence를 부여한다.

```python
RunEvent(
    sequence=2,
    kind="progress",
    message="수집 중",
    payload={"completed": 1, "total": 2},
    created_at="2026-08-24T13:00:00.000+00:00",
)
```

예약된 runtime event kind는 다음과 같다.

- `started`: worker adapter 실행 시작
- `stopping`: `stop()` 요청 접수
- `succeeded`: 예외 없이 정상 반환
- `failed`: 예외 반환. payload에 `error`, `error_type` 포함
- `stopped`: stop event가 설정된 뒤 worker 반환

adapter가 보내는 `progress`, `log`, `preview`, `insight` 등 추가 event는
그대로 보존한다. `progress` event의 payload는 snapshot의 `progress`에도
반영한다.

## 순서와 보존

- sequence는 Run별로 `1`부터 증가하며 terminal sequence도 포함한다.
- `events_after()`는 sequence cursor를 사용하므로 polling client가 중복을
  제거할 수 있다.
- runtime은 기본 최근 500개 event만 보존한다. 보존 한도를 넘은 오래된 event는
  삭제되지만 `last_event_sequence`는 줄어들지 않는다.
- API가 cursor보다 오래된 event를 요청한 경우에도 보존된 범위에서 가능한
  event만 반환한다. 전체 로그가 필요하면 로컬 운영 로그를 사용한다.

## 중단과 오류

- `stop()`은 강제 thread 종료가 아니라 stop event를 설정하는 협력적 중단이다.
- adapter는 반복 작업 사이에서 `stop_event.is_set()`을 확인해야 한다.
- adapter가 stop 요청 후 정상 반환하면 runtime은 `stopped`로 종료한다.
- adapter가 예외를 발생시키면 runtime은 `failed`로 종료하고 예외 문자열과
  타입을 event/snapshot에 남긴다.
- terminal Run은 이후 `stop()` 호출로 다시 active 상태가 되지 않는다.

## 안전 경계

이 계약은 수집·분석·draft·rehearsal·human review만 제어한다. Web Studio
adapter는 `poster.py`, 계정 회전, 자동 게시, 외부 커뮤니티 mutation endpoint를
호출하지 않는다. API key, cookie, Playwright session, SQLite 경로는
`RunSpec.params`를 통해 브라우저로 전달하지 않고 로컬 adapter가 소유한다.
