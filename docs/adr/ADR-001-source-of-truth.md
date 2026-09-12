# ADR-001: 금융 원장, 거래 상태, Asset Projection의 Source of Truth

## Status

Accepted

## Context

모아제는 Mock Banking Server, Banking, Asset으로 금융 흐름을 나눈다. 기존 문서에는 Asset Reserve와 Asset 원장 승인 흐름이 남아 있지만, 실제 코드와 최신 결정은 Banking이 Mock Banking에 동기 송금을 요청하고 Asset은 Kafka 이벤트를 소비해 조회 Projection을 갱신하는 형태다.

## Decision

실제 계좌 잔액과 최종 금융거래 결과의 Source of Truth는 Mock Banking Server다. Banking은 금융 원장을 복제하지 않고, 모아제가 시작한 송금 요청의 생명주기와 멱등성 키, 외부 거래 식별자, 상태, 대사 필요 여부를 관리한다. Asset은 승인자가 아니라 지연 가능하고 재구성 가능한 Projection이다.

Client와 Asset은 내부 계좌 식별자인 `accountId`로 Projection 계좌를 참조한다. Mock Banking 내부 계좌 식별자인 `providerAccountId`는 Banking과 Mock Banking 사이의 계약에만 사용해야 하며, Kafka 이벤트와 Asset DB에는 저장하지 않는다.

## Alternatives Considered

- Asset을 승인 원장으로 사용: Asset 잔액이 오래되면 잘못된 승인으로 이어질 수 있어 제외한다.
- Banking이 계좌 잔액을 복제: Mock Banking과 이중 원장이 되어 불일치 관리 비용이 커져 제외한다.

## Consequences

Banking 장애가 Asset 반영을 지연시킬 수는 있지만 Mock Banking의 실제 잔액과 거래 결과를 바꾸지는 않는다. Asset 불일치는 Reconciliation으로 복구한다.

## Known Limitations

Mock Banking 자체가 Redis 기반 실습용 계정계이므로 실제 은행의 모든 정합성 보장을 대체하지 않는다.

## Related Tests and Documents

- `TransferCommandServiceIdempotencyTest`
- `TransferApplicationServiceCharacterizationTest`
- `TransferApplicationServiceIdempotencyJpaTest`
- `moaje-infra/docs/phase-history-and-retrospective.md`
