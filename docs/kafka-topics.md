# Kafka Topic 정리

## Banking

### 발행

| Topic | 내용 | 소비 예정 서비스 |
|---|---|---|
| `account_created_events` | 계좌 연결 완료 | Asset |
| `moaje.banking.transfer-completed` | 송금 성공 | Asset |
| `moaje.banking.transfer-failed` | 송금 실패 또는 결과 불명확 | Asset |
| `moaje.banking.transfer-reversed` | 계정계에서 확인된 반전 결과 | Asset |

### 소비

현재 Banking이 소비하는 Kafka Topic은 없다.

## Asset

### 소비

| Topic | 내용 | Consumer Group |
|---|---|---|
| `account_created_events` | 계좌 Projection 생성 | `moaje-asset` |
| `moaje.banking.transfer-completed` | 성공 거래와 잔액 반영 | `moaje-asset` |
| `moaje.banking.transfer-failed` | 실패·대사 필요 상태 반영 | `moaje-asset` |
| `moaje.banking.transfer-reversed` | 이미 확정된 반전 결과 반영 | `moaje-asset` |

소비에 반복 실패한 레코드는 원본 Topic 이름 뒤에 `.DLT`가 붙은 Dead Letter Topic으로 이동한다.

### 발행

| Topic | 내용 | 소비 예정 서비스 |
|---|---|---|
| `transaction_succeeded_events` | 거래 성공 원시 데이터 | Work |
| `moaje.asset.monthly-cashflow-aggregated` | 사용자·월별 수입/지출/자금이동 집계 | Work |
| `moaje.asset.category-cashflow-aggregated` | 사용자·월별 카테고리 집계 | Work |

월 집계 이벤트에는 `yearMonth`와 `revision`이 포함된다. Work는 `(userId, yearMonth)`별로 가장 큰 revision만 최종 결과로 사용해야 한다.

## Work (검증 기준 0f73ea5, 2026-10-10)

Consumer Group은 `moaje-work`이며 Asset과 분리한다. 공용 Kafka `kafka:29092`에 연결한다.

| 방향 | Topic | 규격 |
|---|---|---|
| 소비 | `transaction_succeeded_events` | Protobuf. 실제 소비·거래 중복 방지 검사 통과 |
| 소비 | `moaje.asset.monthly-cashflow-aggregated` | Protobuf. 실제 소비·최신 revision 유지 검사 통과 |
| 소비 | `moaje.asset.category-cashflow-aggregated` | Protobuf. 실제 소비·최신 revision 유지 검사 통과 |
| 소비 | `auth.user.registered` | JSON, Auth의 실제 발행은 미확정 |
| 발행·자기 소비 | `work.fds.alert` | JSON |
| 발행 | `work.spending.analyzed` | JSON |
| 발행 | `work.schedule.updated` | JSON |

로컬 Kafka의 기존 자동 토픽 생성 설정을 유지한다. 구독·발행 시 필요한 토픽이 생성되며, 아직 발행하지 않은 토픽은 목록에 없을 수 있다.
Consumer 연결 성공과 실제 이벤트 처리 성공은 별도 검증 대상이다.
현재 계약 검사에서 불일치 0건이다. 위 3종은 테스트 Protobuf를 발행해 실제 Work DB 결과까지 확인했다. Asset Outbox를 거친 전체 흐름 검증과는 구분한다. [검사 결과와 재현 방법](work-integration-check.md)을 참고한다.

## 아직 확정되지 않은 부분

- Work의 실패 이벤트 재처리·DLT 정책과 전체 메시지 호환성 검증
- Auth가 Kafka를 사용할지 여부 및 Topic 계약
- Work 발행 Topic을 소비할 다른 서비스와 처리 계약

위 항목은 각 모듈 담당자와 계약을 확정한 뒤 추가한다.
