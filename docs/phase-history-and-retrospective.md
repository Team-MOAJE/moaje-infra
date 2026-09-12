# 네 프로젝트 개발 기록과 회고

기준일: 2026-09-12. **현재 코드·기존 Phase 문서·실행 결과를 대조한 기록**입니다. 구현 날짜나 성능을 추정하지 않았습니다. 회고는 코드와 검증에서 얻은 교훈이며, 사용자가 직접 겪었다고 말한 경험을 대신 작성한 것이 아닙니다.

## 1. 출발점과 목표

처음에는 Banking이 Mock 송금 후 감사 로그를 저장하고 Kafka에 직접 보냈습니다. “은행에서는 성공했는데 우리 DB나 메시지는 실패했다면?”에 대한 복구 경로가 부족했습니다.

```text
처음: Mock 성공 → Banking 로그 → Kafka 전송 (중간 실패 시 복구 기록 부족)
현재: 접수 Journal → Mock 실행 → 결과+Outbox → Kafka → Asset 중복 검사
                                  ↑                      ↑
                             원거래 결과 대사       계좌 스냅샷 대사
```

사용자가 확정한 큰 방향은 Mock이 실제 잔액의 기준, Banking이 거래 처리 상태의 기준, Asset은 재구성 가능한 조회 모델이라는 분리입니다. Asset Reserve를 승인 단계로 두지 않습니다.

## 2. Phase별 구현과 네 프로젝트의 참여

| 단계 | Banking | Asset | Mock (backing-mockup) | Infra/Gateway |
|---|---|---|---|---|
| 1 현재 동작 고정 | 중복 요청·직접 발행·오류 경로 확인 | 성공/실패 이벤트 중복 확인 | 기존 Lua 처리 경로 확인 | 멱등키 필수 설정의 실제 동작 확인 |
| 2 송금 멱등성 | Transfer Journal, Principal 범위 Unique, hash, 상태 전이 | 본격 변경 전 | clientTransferId 중복 실행 차단 계약 | 송금에만 필수 키 적용 방향 |
| 3 발송 기록 | 결과+Outbox 같은 DB 저장, eventId PK, Lease, 제한 재시도, 빠른 발행 보강 | 재전달을 견딜 필요 확인 | 새 발행 책임 없음 | DB/Kafka 연결 설정 |
| 4 소비 멱등성 | accountId 중심 이벤트 | Inbox·금융 효과 Unique·계좌 락·Retry/DLT | 외부 계좌 식별 경계 정리 대상 | 계약 공유·배포 영향 확인 |
| 5 거래 대사 | UNKNOWN·오래된 PROCESSING 조회 복구, Lease·횟수·지표, Timeout 검증 | 미확정 거래를 Banking 결과로 복구 | clientTransferId 결과 조회 | Flyway와 실행 설정 지원 |
| 5 반전 확인 | 이미 완료된 REVERSED만 발견·기록, 두 이벤트 복구 | 원 출금·반전 분리, 순서 역전 처리 | 기존 반전 결과 메타데이터 제공 | 보상 실행 정책 추가 없음 |
| 5 계좌 대사 | 계좌 매핑·스냅샷 조회, 계좌 생성 Outbox | 기준 잔액 교체·외부 이력 멱등 보충·DLT 계좌 표시 | providerAccountId·원자 스냅샷 | DB 구조 변경 관리 |
| 6 경계 정리 | ExecuteTransfer와 순환 RPC 제거, 소유권 검사, mTLS 서버 | 단일 복구 경로, mTLS 클라이언트·서버 | provider ID를 계좌번호로 내부 변환 | 인증서 설정 계약 |
| 이후 보강 | Principal 필터, 개인정보 없는 감사, 원 거래 시각 전달 | 30초 감사, cursor 분리, 이벤트/스냅샷 경합, Work 날짜·반전 제외 | Redis 반영 시각으로 이력 조회 경계 | JWT 검증·내부 헤더·선택 프로필·자동 시작 해제 |
| 이번 검증·정리 | MySQL Outbox BLOB 매핑 수정·빈 DB 검증 | 테스트 Listener 자동 시작 차단·빈 DB 검증 | 전용 Redis 유지·외부 출금 연동 확인 | 격리 Compose·Kafka 장애 검증, 승인된 개발 볼륨 초기화, Nginx 제거·선택 도구·문서 통합 |

Auth·Work의 자체 구현까지 이 표의 완료 범위에 들어가지는 않습니다. Phase 6까지 코드가 있다는 것과 기존 DB 전환·운영 도구까지 완성됐다는 것은 다릅니다.

## 3. 단계별 회고

### Phase 1: 개선 목표와 현재 동작을 구분해야 했습니다

현재 동작을 기록하는 Characterization Test를 먼저 두었습니다. 아직 없는 멱등성을 있다고 가정한 테스트를 만들면 출발점을 설명할 수 없습니다. 이후 변경된 정책은 해당 Phase의 회귀 테스트로 바꿨으며, 실패 테스트를 임의로 Disabled 처리해 완료로 보지 않았습니다.

### Phase 2: 조회만으로 중복을 막을 수 없습니다

두 요청이 동시에 “없음”을 읽을 수 있습니다. Unique 제약과 저장 충돌 후 기존 거래 반환이 함께 있어야 한 건으로 수렴합니다. 개인정보는 송금의 의미를 바꾸지 않으므로 hash에서 제외했습니다. 단순 SHA-256을 선택해 별도 키 관리 비용은 줄였지만 해시는 계좌번호 암호화가 아닙니다.

### Phase 3: Outbox의 보장 범위를 좁고 정확하게 설명해야 합니다

Outbox는 **Banking DB에서 Kafka로 가는 발송 의도**를 남깁니다. Mock 성공 후 Banking 저장 전 중단을 해결하지 않습니다. Kafka ack 이후 DB 반영 전 중단은 중복을 만들 수 있어 eventId 유지와 Asset 멱등성이 필요합니다. Producer 실패는 DLT가 아니라 DB의 PENDING/RETRY_EXHAUSTED로 보존합니다.

### Phase 4: 메시지와 금융 효과는 같은 개념이 아닙니다

새 eventId로 같은 송금을 보내도 새 출금이 아닙니다. 반대로 같은 transferId에는 출금과 입금이라는 서로 다른 효과가 있을 수 있습니다. 그래서 eventId와 transferId+accountId+방향을 나눴습니다. 계좌 락은 구현을 단순하게 하지만 같은 계좌의 처리를 직렬화하므로 처리량 비용이 있습니다.

### Phase 5: 재시도보다 먼저 확인할 것은 원거래 결과입니다

Timeout에 곧바로 재송금·반전을 실행하면 이미 성공한 거래를 더 복잡하게 만듭니다. 원 거래 ID 조회를 먼저 하도록 바꿨습니다. 오래된 PROCESSING만 대상으로 삼고 Lease·횟수 제한·지표를 넣은 이유는 정상 처리와 복구 작업의 충돌, 종료된 Worker의 영구 점유, 무한 재시도를 줄이기 위해서입니다.

스냅샷에서는 잔액 절대값과 상세 이력을 구분해야 했습니다. 이미 반영된 잔액에 상세 금액을 다시 계산하면 중복 오차가 납니다. 나중에는 이벤트 시각과 조회 cursor를 분리하고, 조회 도중 새 이벤트가 오면 오래된 응답을 버리도록 보강했습니다. Work에는 대사한 오늘이 아니라 원 거래 날짜를 전달합니다.

### Phase 6: 새 경로만 안전해도 이전 우회 경로가 남으면 부족합니다

Application Service를 건너뛰던 ExecuteTransfer와 양방향 동기 갱신을 정리했습니다. Asset은 Banking의 읽기 API를 호출하고 자기 DB만 수정합니다. gRPC mTLS는 서비스 연결을 검증하지만 사용자별 인가를 대신하지 않으므로 Auth·Work와의 추가 계약은 분리해 남겼습니다.

### 이번 Docker 검증: 테스트 DB 성공과 기존 DB 업그레이드는 다릅니다

H2의 빈 DB에서는 V1부터 실행됐지만 기존 Docker MySQL에는 옛 테이블이 있었습니다. baseline은 옛 구조를 자동 수정하지 않습니다. Banking은 V2에서 없는 banking_transfer를 변경하려다, Asset은 없는 sync_status에 인덱스를 만들려다 실패했습니다.

Asset V2는 앞선 컬럼 추가가 일부 적용됐습니다. 따라서 단순 재실행이나 Flyway 이력 repair만으로 고치면 안 됩니다. **앞으로는 빈 MySQL migration 테스트와 구 스키마→새 스키마 전환 테스트를 별도로 준비**해야 합니다. 기존 데이터 보존·매핑 정책 없이 초기화해서 “기동 성공”으로 처리하지 않습니다.

후속으로 사용자가 격리 검증 성공 후 로컬 데이터 초기화를 승인했습니다. 별도 프로젝트·볼륨에서 먼저 검증한 뒤 기존 서비스 중지 → 다섯 볼륨 파일 백업 → 해당 볼륨만 삭제 → 일반 이미지 재빌드 순서로 실행했습니다. 이것은 **승인된 개발 환경 재생성**이지 기존 데이터를 유지한 업그레이드가 아닙니다.

빈 MySQL에서도 H2가 드러내지 못한 Outbox `BLOB`/`TINYBLOB` 매핑 차이가 발견됐습니다. Entity를 기존 SQL에 맞추고 검증을 유지했습니다. Asset의 수동 Kafka Factory에는 테스트 auto-startup 설정 전달이 빠져 있어 보완했습니다. “테스트가 통과함”과 “실제 DB·브로커에서 동작함”을 나눠 확인해야 했던 이유입니다.

## 4. 검증 기록

<a id="verification"></a>

2026-09-12 실행 근거를 구분합니다. 같은 날짜의 과거 실행 결과를 이번 재실행 결과로 둔갑시키지 않습니다.

| 검증 | 결과 |
|---|---|
| 이전 보강 후 일반 테스트 | Banking 70, Asset 46, Mock 14, Gateway 10: 총 140 성공, 실패/오류/스킵 0 |
| 문서 통합 시 일반 테스트 재실행 | Banking 70, Asset 46, Mock 14, Gateway 10: 총 140 성공, 실패/오류/스킵 0 |
| 이번 런타임 보완 후 재실행 | Banking 71, Asset 47: 118 성공, 실패/오류/스킵 0. `test --rerun --no-daemon --max-workers=1`. Mock 14·Gateway 10은 바로 앞 실행 결과이며 이번 소스 보완 대상이 아님. 최신 XML 합계 142 |
| 실제 Mock Redis Lua | `MOCK_REDIS_TEST_PORT=6380 ./gradlew.bat redisIntegrationTest --rerun` 성공. 2개: 늦게 처리된 송금/출금의 cursor·원시각 보존 |
| 네 앱 Linux 이미지 | Banking·Asset·Gateway·Mock 모두 Docker build 성공 |
| 기반 서비스 | MySQL 2개, Kafka, infra Redis, Mock Redis 기동·healthcheck 성공 |
| 최초 기존 볼륨 앱 기동 | Mock·Gateway 시작. Banking·Asset은 옛 스키마의 Flyway V2 실패로 종료. 이 실패를 삭제해 숨기지 않음 |
| 격리 MySQL 8.4 | Banking V1~V5, Asset V1~V3의 success=1 확인. Hibernate validate를 켠 상태에서 양쪽 시작 성공 |
| 개발 인증서·실제 mTLS | 별도 인증서 생성, Asset → Banking → Mock 스냅샷 호출과 SYNCED 전환 성공 |
| 격리 연동 | `compose-smoke.ps1 -Verify -KafkaOutage`: 최종 29개 assertion 성공. `.local/verify-smoke/result.json` |
| 재생성한 일반 로컬 환경 | `compose-smoke.ps1`: 23개 assertion 성공. `.local/smoke/result.json`. Banking V1~V5·Asset V1~V3 적용, 네 앱 실행 확인. 무작위 시험 계좌·송금·외부 출금 이력이 남아 있음 |
| 테스트 인증 설정 제거 후 | Gateway health 200, 토큰 누락 401, JWT 계약 미설정+토큰 제시 503, Mock 토큰 누락 401. JWKS fixture 제거 확인 |
| 실제 HTTP·금융 흐름 | JWT 누락/만료 거부, 위조 사용자 헤더/본문 무시, 계좌 생성·송금·키 충돌·출금 1회·ATM형 외부 출금 수집 확인 |
| 실제 Kafka 장애·복구 | 브로커 중지 중 송금 성공·Outbox PENDING, 실패 횟수/사유/다음 시각 기록. 복구 후 같은 eventId로 PUBLISHED, Asset 금액·내역 1회 반영 |

처음에는 기존 데이터와 실패 이력을 그대로 보존했습니다. 격리 검증 성공 후 사용자 승인에 따라 `moaje-infra_asset-mysql-data`, `moaje-infra_banking-mysql-data`, `moaje-infra_redis-data`, `moaje-infra_kafka-data`, `moaje-mock-banking_mock-banking-redis-data`만 삭제·재생성했습니다. 중지된 볼륨의 tar.gz 백업은 `.local/backups/20260912-before-reset`에 있으며 압축 파일 읽기는 확인했고 복원 실행은 하지 않았습니다. 백업은 Git에서 제외되며 외부 공유하지 않습니다. Flyway repair·수동 history 수정은 하지 않았고 coupon·다른 프로젝트·모니터링 볼륨과 gRPC 인증서는 보존했습니다.

이전 Asset 일반 테스트에는 실제 localhost Kafka 그룹 연결이 있었습니다. `AssetKafkaConsumerConfig`가 auto-startup 값을 Factory에 전달하도록 보완하고 비시작 상태 회귀 테스트를 추가했습니다. 과거 실행의 offset 영향은 소급 검증하지 않았습니다.

기존 Nginx 컨테이너 2개와 전용 인증서 볼륨을 제거했습니다. gRPC 초기화 컨테이너는 mTLS에 필요하므로 유지합니다. 도구 4개는 선택 프로필·restart=no로 재생성만 했으며 시작하지 않았습니다. 별도 검증 스택은 검증 후 종료했습니다. 이후 사용자의 삭제 요청에 따라 검증용 컨테이너와 데이터 볼륨 5개 및 검증 Kafka 전용 익명 볼륨을 제거했습니다. 로컬 결과 파일과 기존 개발 데이터 백업은 보존했습니다.

이번에 수정한 업무 Kotlin은 `BankingOutboxEvent.payload` 타입 선언과 `AssetKafkaConsumerConfig`의 auto-startup 전달입니다. 각각 `BankingOutboxPayloadJpaTest`, `AssetKafkaConsumerConfigTest.respectsDisabledAutoStartup`을 추가했습니다. 두 서비스의 baseline 기본값을 false로 변경했으며 migration SQL은 수정하지 않았습니다.

**중간 실패도 구분합니다.** Banking의 첫 테스트 시도는 재사용 Gradle daemon의 설정 단계에서 실패했고, 새 daemon 재실행은 71개 모두 통과했습니다. 스모크 추가 검사는 처음에 `created_at(LocalDateTime)`과 `next_attempt_at(Instant)`를 비교해 시간대 차이로 실패했습니다. 실제 실패 기록은 있었으며, 같은 next_attempt_at의 이전/이후 값 비교로 고친 최종 29개 검사는 통과했습니다. 시간 타입 통일은 후속 검토 항목입니다.

최종 Compose 검사는 선택 프로필·restart=no·Nginx 부재·baseline=false·Banking/Asset 비공개 포트를 확인했습니다. 중앙 문서와 README 21개의 로컬 링크·문자 깨짐 검사도 통과했습니다. `git diff --check`는 Banking·Infra·Mock에서 통과했고, Asset에서는 이번 수정 대상이 아닌 기존 Application·ID·Redis 및 ApplicationTests 파일 7개의 EOF 빈 줄 경고가 남았습니다. 무관한 포맷 변경은 하지 않았습니다.

## 5. 지금 주장할 수 있는 것과 없는 것

**구현·테스트 근거가 있는 것:** 송금 접수 멱등성, DB 결과+Outbox 원자 저장, 재발행 상태, Asset 메시지/금융 효과 멱등성, 대사 Worker와 시간 경계, 이미 발생한 반전 반영, 스냅샷 기반 외부 이력 수집, mTLS·Gateway JWT 테스트.

**아직 주장하면 안 되는 것:** 구 데이터를 유지한 DB 업그레이드, 실제 Auth·Work까지 포함한 통합 완료, 모든 계좌 1분 이내 반영 SLA, 실은행 수준 원장 내구성, Work 중복 소비, 운영자 재처리와 DLT 운영 완성, 모아제 보상 실행 정책, 무조건 안전한 NOT_FOUND 실패 확정. 격리 테스트의 금융 기록은 무작위 합성 데이터입니다.

| 다음 작업 | 이유·결정 주체 |
|---|---|
| 데이터 보존이 필요한 DB의 전환 | 이번에는 개발 초기화를 승인받음. 실제 유지가 필요하면 구 식별자 매핑·전환·복원 검증 별도 구현 |
| Banking REQUESTED·5xx·Mock 손상 조회 보강 | 현재 자동 복구의 빈 구간. 먼저 실패 재현 테스트 필요 |
| Auth JWT 규격·개설 개인정보 공급 | Auth 회의 후 설정/계약 구현 |
| Work 시간대·중복 소비·RPC 인가 | Work 회의 후 개발 |
| Auth·Work Compose 등록 | 실행 가능한 최소 커밋과 시작 명령·포트·환경변수를 받은 후 추가. 임의 토픽/가짜 서비스는 만들지 않음. [팀원 체크리스트](learning/infra.md#7-아직-공유되지-않은-authwork-연결-준비) |
| 시간 타입·DB 시간대 통일 | LocalDateTime과 Instant의 저장 표현이 달라 직접 비교하지 않도록 검토 |
| Asset→Work Publisher·운영자 API | Lease·제한 재시도·인증·감사 필요 |
| Swagger | 네 모듈 기동·연동 확인 이후 별도 진행. 이번에는 추가하지 않음 |

## 6. 문서 정리 기록

학습문서는 [Banking](learning/banking.md), [Asset](learning/asset.md), [Mock](learning/mock-banking.md), [Infra](learning/infra.md) 각각 하나만 유지합니다. ADR은 [adr](adr)에 모으며 각 저장소 README는 진입 링크만 남깁니다.

| 이전 문서 묶음 | 보존한 위치 |
|---|---|
| Banking phase-01~03 학습·포트폴리오 | 이 문서의 Phase 기록/회고 + Banking 학습 |
| phase-04, phase-05의 대사·반전·스냅샷 문서 | Phase 기록 + Banking/Asset/Mock 기능별 학습 |
| phase-06 경계 정리 | Phase 기록 + Banking/Infra의 RPC·mTLS 설명 |
| 통합 implementation-guide, 2026-09-12 hardening | 기능별 학습 4개 + 이 문서의 검증/한계 |
| flyway-schema-management, LOCAL-DEVELOPMENT, Infra readMe 상세 | Infra 학습의 실행·JWT·Flyway 절 |
| Mock API_SPEC/JSON_SPEC/USAGE_GUIDE와 중복 README | Mock 학습의 현재 API·토큰·장애·실행 규격 |
| consistency-review | 책임 결정은 ADR-001/006, 현재 상태는 기능별 학습. 잘못된 UNKNOWN/REVERSED 실패 이벤트 설명은 제거 |
| ADR-001~011 | 같은 번호로 중앙 adr 디렉터리 이동. 현재 코드와 다른 진행 상태·링크만 정정 |
| Gateway HELP.md | 프레임워크 생성 안내로 프로젝트 고유 내용이 없어 제거 |

삭제 전 핵심 계약·제약·미완료 항목을 위 위치로 옮겼습니다. 자동 생성된 Gradle 보고서와 타 프로젝트 문서는 정리 대상이 아닙니다. 원래 문서와 코드의 불일치는 코드 기준으로 고쳤으며, 오래된 설명을 현행 보장처럼 보존하지 않습니다.
