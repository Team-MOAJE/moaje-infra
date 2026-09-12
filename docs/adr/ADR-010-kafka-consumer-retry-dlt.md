# ADR-010: Kafka Consumer Retry, DLT 및 Projection 복구 정책

## Status

Accepted and implemented through Phase 5

## Context

Kafka는 at-least-once 전달이므로 Consumer 실패와 중복 전달을 전제로 해야 한다. Outbox Publisher 실패와 Consumer 처리 실패는 다른 문제다.

## Decision

Asset Consumer에는 Retryable 오류와 Non-Retryable 오류 분류를 둔다. 제한된 retry와 backoff 이후 복구 불가능한 이벤트는 Dead Letter Topic으로 보낸다. DLT 이벤트에는 원본 topic, partition, offset, event id, aggregate id, 예외 정보를 남긴다.

DLT 적재는 장애 해결이 아니라 운영 확인 상태다. 대상 계좌 또는 Projection은 필요하면 `SYNC_REQUIRED`로 표시하고 Mock Banking 대사를 통해 복구한다.

Banking Outbox Publisher는 Protobuf 본문을 읽지 못하는 경우를 위해 `eventId`, `aggregateId`, `eventType`, `accountId`를 개인정보 없는 Kafka Header로도 전달한다. Asset은 DLT 발행 성공 뒤 Header의 `accountId`로 기존 계좌를 `SYNC_REQUIRED`로 표시한다. 식별자가 없으면 특정 계좌를 추측하지 않고 주기적인 전체 계좌 Snapshot 감사를 최후 안전망으로 사용한다.

## Alternatives Considered

- 무한 retry: 파티션 처리를 영구 정지시킬 수 있어 제외한다.
- DLT만으로 복구 완료 간주: Projection 불일치가 남을 수 있어 제외한다.
- Non-blocking retry topic 기본 선택: 순서 보장을 잃을 수 있어 계좌별 순서 요구를 먼저 확인한다.

## Consequences

DLT 재처리도 Asset 멱등성 위에서 동작해야 한다. DLT 발행 실패 시 원본 레코드를 성공 처리하지 않아야 한다.

## Known Limitations

DLT 검색·원인 수정·재투입을 수행할 백오피스와 미처리 DLT lag 알림은 아직 없다. 계좌 생성 이벤트가 손상되어 Asset 계좌 Row 자체가 없다면 Snapshot Worker가 찾을 대상도 없으므로 반드시 DLT 원본을 수정해 재처리해야 한다.

`syncRetryExhausted` 및 Banking Outbox `RETRY_EXHAUSTED`를 되돌리는 인증된 운영자 HTTP API는 만들지 않았다. 현재는 상태·Metric·Application maintenance 경계만 유지하며, 백오피스 인증과 감사 로그 정책이 확정된 뒤 내부 API를 추가한다.

## Related Tests and Documents

- ADR-005
- Phase 4 consumer tests
