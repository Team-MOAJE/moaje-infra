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

## 아직 확정되지 않은 부분

- Work의 Consumer Group 이름과 재처리 정책
- Auth가 Kafka를 사용할지 여부 및 Topic 계약
- Work가 만든 분석 결과를 다른 서비스로 전달할 Topic

위 항목은 각 모듈 담당자와 계약을 확정한 뒤 추가한다.
