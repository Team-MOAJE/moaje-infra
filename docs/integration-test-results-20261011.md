# 통합 테스트 결과 · 2026-10-11

**후속 수정:** 아래 잠금 해제와 구형 페르소나 도구 문제는 이후 수정·재검증했다. 최초 실패 기록은 유지하며 [후속 결과](gateway-persona-retest-20261011.md)를 함께 확인한다.

## 결론

**송금 → Banking Outbox → Kafka → Asset → Work 흐름과 장애 복구는 이번 조건에서 통과했다.**
다만 Gateway를 통한 JWT 없는 앱 잠금 해제는 401로 차단된다. 전체 기능에 문제가 없다는 뜻은 아니다.

[검증 기록 JSON](integration-test-results-20261011.json): **187개 기록, PASS 184개, FAIL 3개**.
재검증 기록을 포함한 수치이며, 서로 다른 API 187개를 시험했다는 뜻은 아니다.
FAIL 3개 중 2개는 시험 준비·대기 방식의 문제로 후속 재검증이 통과했고, 1개는 미해결 연동 문제다. 최초 실패도 삭제하지 않았다.

## 검증 기준

| 저장소 | 브랜치 | 로컬 기준 commit |
|---|---|---|
| moaje-infra | main | `3ddb859` |
| moaje-banking | main | `ee36b69` |
| moaje-asset | main | `ba67f54` |
| backing-mockup | main | `13d172b` |
| moaje-auth | dev | `15bcb57` |
| moaje-work | dev | `746e4d0` |
| moaje-grpc-contracts | main | `b40e773` |

- 기존 통합 환경의 로컬 이미지를 `--no-build`로 사용했다. 이번 실행에서 모든 이미지를 새로 빌드한 것은 아니다.
- 앱 소스는 변경하지 않았다. 테스트 요청·검증 대기 방식과 문서를 수정했다.
- 기준 확인 당시 Infra에 기존 미추적 `docs/blog/`, `tmp/`, API PDF가 있었다. 해당 파일을 삭제하거나 커밋하지 않았다.
- 테스트 프로젝트: `moaje-e2e-20261011`, Gateway: `127.0.0.1:19080`.
- DB 4개, Redis 2개, Kafka를 **새 볼륨 7개**로 실행했다. 기존 `moaje-infra` 개발 환경과 분리했다.
- `tests/docker-compose.e2e.yaml`에서 대사 주기를 5초, 전월 재집계를 15초로 설정했다. 월초까지 기다리지 않고 실제 집계 경로를 실행하기 위한 시험 설정이다.

실행 이미지 ID 앞 12자리: Auth `e624d19dcf52`, Work `3616ffb3bc97`, Banking `7347f238799a`, Asset `3b52907c434c`, Mock `2369d2323111`, Gateway `d1c0f28a97fa`.

## 주요 결과

| 영역 | 실제 시험 | 결과 |
|---|---|---|
| 가입·로그인 | 휴대폰 번호·6자리 PIN·확인 PIN·필수 약관, 중복 가입, 잘못된 PIN | 통과 |
| 회원 관리 | 내 정보 조회, 이름·이메일 변경, 이메일 삭제, PIN 변경, 탈퇴 | 통과 |
| 세션 | refresh 교체·재사용 차단, PIN 변경 후 세션 폐기, 로그아웃·탈퇴 후 refresh 차단 | 통과 |
| 인증·소유권 | JWT 없는 요청·위조 사용자 헤더, 타인 계좌 출금·조회·토큰 생성 차단 | 통과 |
| 정상 송금 | Mock 잔액 100,000→90,000 / 0→10,000, Banking SUCCEEDED, Outbox PUBLISHED, Asset 거래 1건 | 통과 |
| 금융 멱등성 | 완료 거래 재요청 시 Mock 추가 호출 0회, 같은 키 12건 동시 요청 시 DB 1행·Mock 1회 | 통과 |
| 충돌·명확 실패 | 같은 키에 다른 금액·수취계좌 409, 키 누락 400, 잔액 부족 FAILED | 통과 |
| 거래 조회 | 외부 결제 121건 수집 후 커서 50·50·23건, 보이는 거래 123건과 일치·중복 없음 | 통과 |
| 계좌 refresh | 반복 실행 시 거래 건수 유지, Mock·Asset 최종 잔액 일치 | 통과 |
| 일별 계산·RPC | 계좌 미연동 409 / RPC FAILED_PRECONDITION, 빈 ID INVALID_ARGUMENT, ACTIVE 0원 정상 | 통과 |
| 계좌 해지 | Mock CLOSED를 refresh로 반영 후 잔액 합산 제외, 일별 계산 409 | 통과 |
| 월별 집계 | CAFE 121원, 개인 간 송금 TRANSFER 분리, 거래 없는 사용자 0원 조회 | 통과 |
| 과거 거래 | Mock에서 3개월 24건 생성, 반복 생성 0건, 전월 revision 1→2·Work 지출 153,500원 동기화 | 통과 |
| Work 기능 | 온보딩·시뮬레이터·준비도·학사 일정·소비 분석·Recap·FDS·운영자 API의 실행 경로 | 통과 |
| 실제 gRPC | Work→Asset mTLS 잔액 조회, 시뮬레이터 current_asset과 Asset 잔액 비교 | 통과 |
| 메시지 중복 | 동일 payload 및 다른 eventId 재발행 후 Asset 잔액·거래 건수, Work 처리 건수 유지 | 통과 |
| 수정 이벤트 | 낮은 revision 재발행 시 Work 최신 월별 집계 유지 | 통과 |
| 손상 메시지 | 잘못된 Protobuf를 DLT에서 1건 확인, 원본 Topic·Offset·예외 헤더 보존 | 통과 |
| DLT 후 복구 | 복구 대상 지정 지표 증가, 스냅샷 후 SYNCED·잔액 유지 | 통과 |
| Swagger | 통합 화면과 Auth·Banking·Asset·Work 명세·Asset UI 리소스 라우팅 | 통과 |
| 빈 DB 준비 | Auth Alembic `004_drop_sms_verifications`, Banking Flyway V1~V6, Asset V1~V5 | 통과 |

위 표의 Work API 통과는 주로 응답 상태와 일부 금액·중복 여부 검증이다. AI 분석 품질이나 모든 응답 필드의 정확성을 증명하지 않는다.

## 실제 장애 주입

### 1. Mock 성공 후 응답 Timeout

Mock의 실제 송금 응답을 프록시가 35초 지연했다. Banking은 UNKNOWN과 대사 필요 상태를 저장했고,
대사 1회 후 SUCCEEDED, 성공 Outbox PUBLISHED, Asset 거래 1건을 확인했다.
감사 로그에는 `UNREADABLE_RESPONSE` 이후 `SUCCESS`가 남았으며 실패 이벤트는 생성되지 않았다.

최초 시험은 SUCCEEDED 직후 Outbox를 바로 읽어 PENDING을 실패로 판정했다.
비동기 발행의 완료 조건을 최대 45초 기다리도록 테스트를 보완하고 **새 멱등성 키로 실제 Timeout을 다시 주입**해 통과했다. 완료 조건은 완화하지 않았다.

### 2. Kafka 중단

테스트 Kafka 컨테이너를 중단한 상태에서 송금했다. 금융거래는 COMPLETED였고 Outbox는 PENDING,
attempt_count 1과 next_attempt_at이 보존됐다. Kafka 재시작 후 같은 eventId로 PUBLISHED가 됐으며,
발행 시도는 4회, Asset 거래 연결은 1건이었다.

### 3. Mock 성공 후 Banking 강제 종료

Mock에서 송금이 완료됐지만 응답을 지연하는 동안 Banking을 강제 종료했다.
종료 전 중복 요청은 PROCESSING을 반환했고 Mock 추가 호출은 없었으며 대사 시도는 0회였다.
재시작 후 오래된 PROCESSING이 대사 1회로 SUCCEEDED가 됐고, Outbox 발행·Asset 거래 1건을 확인했다.
복구 후 재요청해도 Mock 송금 POST 횟수는 9회에서 늘지 않았다.

### 4. 재발행 시험의 준비 오류

처음에는 테스트용 Protobuf Python 코드의 `common` 의존 코드를 생성하지 않아 replay 구간이 중단됐다.
공통 proto까지 생성한 뒤 재실행했고 Asset·Work 중복 방지와 낮은 revision 무시를 확인했다.
이 오류는 서비스 장애가 아니라 테스트 준비 오류다.

## 남아 있는 문제와 담당 영역

| 문제 | 확인 근거 | 필요한 작업 |
|---|---|---|
| JWT 없이 잠금 해제 불가 | Gateway `/api/v1/auth/session/unlock`에 유효한 refresh와 PIN만 보내면 401, JWT 동반 시 200 | **Infra**: 자체 refresh·PIN으로 인증하는 해당 POST 경로를 공개 목록에 추가할지 결정 후 `.env.example`, Compose 기본값, Gateway 기본 설정·테스트를 함께 수정 |
| 기존 페르소나 도구의 가입 규격이 오래됨 | `test-fixture-console/app.py`와 `scripts/seed-monthly-cashflow-persona.sh`가 email+PIN만 전송 | **Infra**: 휴대폰 번호·이름·확인 PIN·필수 약관 규격으로 변경. 이번에는 소스 점검만 했으며 도구 전체 실행은 검증하지 않음 |

Auth 타인 계좌 토큰 발급과 Work의 집계 전 신규 사용자 소비 프로필 조회는 이번 재검증에서 각각 403 차단과 200 응답으로 통과했다.

## 검증하지 않은 범위

- 모든 API의 모든 입력 조합, 성능·장시간 부하, 여러 실제 서버의 동시 Worker 실행.
- Outbox 최대 재시도 소진·운영자 재발행, DLT 발행 자체 실패, Kafka ack 직후 프로세스 종료.
- DLT 시험 중 순간적인 SYNC_REQUIRED 값의 직접 관찰. 지표와 최종 SYNCED를 확인했다.
- Auth gRPC의 TLS 적용, Work 온보딩 결과가 Auth 가입 상태로 전달되는 전체 경로.
- 실제 은행·본인 인증사·SMS 연동, 보상거래 실행 정책.
- 다른 물리 PC에서의 실제 실행. [실행 안내](run-on-another-pc.md)는 현재 Compose와 Dockerfile을 기준으로 작성했다.

## 변경·정리

- `tests/full-e2e.py`: 현재 가입 요청 규격, 약관·PIN 검증, Outbox 완료 조건 대기, Timeout 재검증 키 분리.
- `tests/rerun-e2e.py`: import 시 자동 실행 방지, 신규 0원 사용자 가입 규격, Timeout 재시험 단계.
- `tests/current-auth-e2e.py`: 회원 정보·잠금 해제·PIN 변경·탈퇴 시험 추가.
- 문서: 다른 PC 실행 안내, Swagger 가입 예시, 이 결과와 원본 JSON 추가.
- 결과 JSON만 보존한다. 토큰이 있는 테스트 상태 파일은 밖으로 복사하지 않는다.
- 실행 후 해당 테스트 프로젝트의 컨테이너·볼륨 7개·테스트 인증서를 제거했다. 기존 개발 컨테이너 13개와 볼륨 7개를 보존했고, 개발 Gateway Swagger의 HTTP 200 응답도 확인했다.
