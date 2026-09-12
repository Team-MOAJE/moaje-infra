# ADR-003: Banking Transactional Outbox와 보장 범위

## Status

Accepted and implemented in Phase 3

## Context

Phase 2까지 Banking은 Mock Banking 결과를 받은 뒤 `banking_transfer`, `kftc_api_log`를 저장하고 송금 결과 Kafka 이벤트를 직접 발행했다. DB commit과 Kafka broker ack는 하나의 원자적 작업으로 묶을 수 없으므로, Banking 상태는 성공인데 Asset Projection 이벤트가 유실될 수 있었다.

## Decision

송금 결과 저장과 Integration Event 생성을 하나의 Banking DB 트랜잭션에 묶기 위해 `banking_outbox`를 도입한다. `event_id`를 Outbox의 단일 PK로 사용하고 별도 `outboxId`는 만들지 않는다. 재발행할 때도 같은 `event_id`와 payload를 유지한다.

`TransferCommandServiceImpl`은 Mock Banking 응답 이후 새 DB 트랜잭션에서 `banking_transfer`, `kftc_api_log`, `banking_outbox`를 함께 저장한다. `BankingTransferEventPublisher`는 더 이상 KafkaTemplate을 직접 호출하지 않고 protobuf payload를 만들어 Outbox에 저장한다. Kafka 발행은 `BankingOutboxPublisher`만 담당한다.

별도 Publisher가 `PENDING` Outbox를 읽어 Kafka broker ack를 확인한 뒤 `PUBLISHED`로 변경한다. Kafka 발행은 DB 트랜잭션 밖에서 수행한다.

Outbox 상태는 거래 상태와 분리한다. 영속 상태는 `PENDING`, `PUBLISHED`, `RETRY_EXHAUSTED`를 사용하고, `PROCESSING` 점유 상태는 Lease 필드(`locked_at`, `locked_until`, `lock_owner`)로 표현한다. `RETRY_EXHAUSTED`는 단일 전송 실패가 아니라 설정된 자동 재시도를 모두 소진해 운영자 확인 또는 수동 재발행이 필요한 상태다. 운영자 재발행이 승인되면 같은 eventId를 유지한 채 `PENDING`으로 되돌릴 수 있다.

여러 Publisher 인스턴스가 같은 이벤트를 동시에 발행하지 않도록 `locked_at`, `locked_until`, `lock_owner` 기반 Lease를 사용한다. Publisher가 Lease를 잡은 뒤 종료되면 `locked_until` 만료 후 다른 Publisher가 다시 claim할 수 있다.

Producer 측 Kafka 전송 실패는 Kafka DLT로 보내지 않는다. 아직 Kafka에 적재되기 전의 Banking DB 레코드 문제이므로, 실패 횟수와 다음 재시도 시각을 DB에 기록하고 최대 시도 초과 시 `RETRY_EXHAUSTED`로 보존한다. Consumer Retry와 DLT는 Phase 4에서 별도로 설계한다.

## Alternatives Considered

- DB 트랜잭션 안에서 Kafka send 대기: Kafka 장애가 API 트랜잭션과 DB connection 점유를 길게 만들 수 있어 제외한다.
- Kafka DLT로 producer 실패 해결: Kafka 적재 전 실패이므로 DLT도 사용할 수 없어 제외한다.
- `FAILED` 상태명 사용: 짧고 익숙하지만 단일 실패와 최종 재시도 소진을 혼동할 수 있어 Phase 3 기본 이름으로는 `RETRY_EXHAUSTED`를 선호한다.
- 별도 `outboxId` PK 사용: 일반적인 설계지만 이 프로젝트에서는 재발행 단위가 Integration Event 자체이므로 `event_id` 단일 PK로 충분하다고 판단했다.
- DB `PROCESSING` 상태 사용: Publisher 종료 시 영구 점유 위험이 있어 제외하고 Lease 만료 정책을 선택했다.

## Consequences

Kafka ack 후 `PUBLISHED` 변경 전 프로세스가 종료되면 Outbox는 여전히 `PENDING`으로 남을 수 있다. 이 경우 같은 `event_id`가 재발행될 수 있으며, Phase 4 Asset Consumer 멱등성이 반드시 필요하다.

성공/명확 실패 이벤트만 Outbox에 기록한다. Timeout은 실패가 아니라 `UNKNOWN` 거래 상태와 대사 대상으로 남기며, Phase 5 Reconciliation에서 원거래 결과가 확정된 뒤 필요한 이벤트를 생성한다.

## Known Limitations

Outbox는 `Banking DB -> Kafka` 구간만 다룬다. `Mock Banking 성공 -> Banking DB 저장 전 종료`는 Reconciliation으로 복구해야 한다.

운영자 수동 재발행은 현재 Application Service 메서드(`BankingOutboxMaintenanceService.resetRetryExhausted`)까지만 제공한다. 관리자 API, 권한, 감사 로그는 별도 운영 경계가 필요하므로 후속 작업으로 남긴다.

Kafka producer 설정은 Kafka Client 3.7.1 기준으로 확인했고, Phase 3에서는 기존 serializer 설정에 `acks=all`, `enable.idempotence=true`를 명시했다. `delivery.timeout.ms`, `request.timeout.ms`, producer 내부 `retries`, `max.in.flight.requests.per.connection` 튜닝은 부하와 장애 주입 측정 후 조정한다.

## Related Tests and Documents

- `TransferCommandServiceIdempotencyTest`
- `BankingOutboxPublisherTest`
- `moaje-infra/docs/learning/banking.md`
- ADR-005
- ADR-004
