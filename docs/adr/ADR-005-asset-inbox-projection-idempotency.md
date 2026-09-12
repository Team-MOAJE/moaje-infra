# ADR-005: Asset Projection 멱등성 키와 Inbox 정책

## Status

Accepted and implemented in Phase 4

## Context

Asset은 Banking Kafka 이벤트를 at-least-once로 받는다. Phase 3 Outbox는 Kafka ack 후 `PUBLISHED` 저장 전 장애가 발생하면 같은 `eventId`를 재발행할 수 있다. 또한 Reconciliation이나 운영 재처리에서 같은 금융 효과가 새로운 `eventId`로 다시 발행될 수 있다.

## Decision

기술적 메시지 중복과 비즈니스 금융 효과 중복을 분리한다.

기술적 멱등성은 `processed_event.event_id` PK로 처리한다. 같은 Outbox Row가 같은 `eventId`로 재전달되면 이미 처리된 이벤트로 보고 잔액과 거래내역을 다시 변경하지 않는다.

비즈니스 멱등성은 `transaction_history`의 `(banking_transfer_id, account_id, balance_change_type)` Unique Constraint로 처리한다. 같은 송금이 다른 `eventId`로 재발행되어도 동일 계좌에 동일 `balanceChangeType`을 한 번만 반영한다.

현재 Banking 송금 성공 이벤트는 출금 계좌 하나에 대한 Projection 효과만 제공하므로 Asset은 `TRANSFER_OUT`만 반영한다. `TRANSFER_IN`은 같은 `transferId`라도 다른 계좌와 다른 `balanceChangeType`이면 정상 금융 효과로 저장할 수 있도록 모델에 포함했다.

## Alternatives Considered

- `eventId`만 사용: 재발행 시 eventId가 바뀌면 중복 반영될 수 있어 제외한다.
- 기존 `transaction_history` unique만 사용: 성공은 가능하지만 실패 이벤트에는 외부 거래 ID가 없을 수 있어 보완이 필요하다.
- 단순 `transferId` unique 사용: 하나의 송금에서 출금 효과와 입금 효과가 공존할 수 있어 제외한다.

## Consequences

Asset Projection 갱신, 거래내역 저장, 처리 이벤트 기록은 하나의 DB 트랜잭션에서 수행한다. DLT 재처리도 중복 반영 없이 가능해야 한다.

대사에서 확인된 보상은 원 `TRANSFER_OUT`을 삭제하지 않고 `(transferId, accountId, REVERSAL_IN)` 금융 효과로 추가한다. Reversed 이벤트가 Completed보다 먼저 도착하면 `PENDING` 거래내역과 `SYNC_REQUIRED`를 남기고 잔액 증가는 보류하며, Completed 도착 시 같은 계좌 Lock과 DB 트랜잭션 안에서 두 효과를 완결한다.

`SYNC_REQUIRED` 자동 복구는 우선 `accountId + transferId`로 Banking Transaction Journal을 조회하는 표적 재구성을 사용한다. Account lease를 짧은 트랜잭션에서 선점하고 원격 조회는 트랜잭션 밖에서 수행하며, 결과 반영 시 계좌 비관적 Lock과 lease owner를 다시 확인한다. 확정되지 않은 상태나 금액·소유자 불일치는 잔액에 반영하지 않는다.

Kafka Consumer에는 Spring Kafka `DefaultErrorHandler`와 `DeadLetterPublishingRecoverer`를 적용한다. 역직렬화 실패는 non-retryable로 분류하고, 그 외 실패는 제한 재시도 후 원본 topic의 `.DLT`로 이동한다. 중복 이벤트는 실패가 아니라 정상 소비로 종료한다.

## Known Limitations

현재 정상 이벤트는 SYNC_REQUIRED·재시도 소진 상태를 해제하지 않고 이벤트 반영 시각만 갱신한다. 대사 완료 때 미확정 거래를 확인해 상태를 결정한다. 원인별 상세 동기화 작업 모델은 아직 없다.

Phase 5에서 표적 transfer 복구에 더해 Mock Banking의 기준 잔액과 cursor 이후 외부 거래를 조회하는 Account Snapshot 대사를 구현했다. 외부 거래는 `externalTransactionId`로 멱등 저장하고 잔액은 거래 증감을 다시 합산하지 않고 Snapshot 절대값으로 교체한다. 오래된 `SYNCED` 계좌도 기본 30초 감사 간격(Worker 5초·배치 20개, 완료 SLA 아님)로 다시 확인한다.

Kafka DLT에 적재된 이벤트의 운영자 재처리 도구와 알림은 아직 없다. DLT 발행 성공 후 `moaje-account-id` Header로 기존 계좌를 `SYNC_REQUIRED`로 표시하지만, 계좌 생성 이벤트 자체가 손상되어 Asset Row가 없다면 표시할 수 없어 원본 수정·재처리가 필요하다.

Banking 이벤트는 현재 출금 계좌 효과만 포함한다. 입금 Projection은 스냅샷으로 자동 반영한다. 입금도 즉시 Kafka로 반영하려면 Banking 이벤트 계약에 destination `accountId`를 추가하거나 계좌별 balance-changed 이벤트로 확장해야 한다.

## Related Tests and Documents

- `TransferApplicationServiceCharacterizationTest`
- `TransferApplicationServiceIdempotencyJpaTest`
- ADR-010
