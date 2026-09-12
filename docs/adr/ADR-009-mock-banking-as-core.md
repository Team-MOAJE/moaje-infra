# ADR-009: Mock Banking을 실습용 계정계로 사용하는 이유와 한계

## Status

Accepted

## Context

모아제는 실제 은행 연동 전 Mock Banking Server를 계정계로 사용한다. Mock은 Redis Lua로 계좌 잔액 차감과 입금을 원자 처리한다.

## Decision

Mock Banking은 실습 환경의 계정계이자 실제 잔액 Source of Truth다. Banking은 Mock의 잔액을 복제하지 않고 거래 요청 상태만 저장한다.

최종 계좌 식별 계약에서는 Mock Banking이 `providerAccountId`를 발급하고 실제 계좌번호와의 매핑을 내부에서 관리한다. Banking은 `accountId -> providerAccountId` 매핑을 저장해 금융 처리 때 사용하고, Asset과 Kafka에는 `providerAccountId`를 노출하지 않는다.

## Alternatives Considered

- Banking MySQL을 계정계로 사용: 실제 은행 Adapter 교체 목적과 어긋나 제외한다.
- Asset DB를 계정계로 사용: 조회 Projection 책임과 충돌해 제외한다.

## Consequences

실제 은행 Adapter로 교체할 때는 Mock REST client 뒤의 Port 계약을 유지하고 Adapter만 바꾼다.

## Known Limitations

Redis 기반 Mock은 실은행의 정산, 전문, 지연 응답, 취소 정책을 단순화한다. 이 한계는 포트폴리오에서 명확히 설명한다.

Phase 5에서 Mock Banking은 불투명 `providerAccountId`와 원자적 Account Snapshot 조회를 제공한다. Redis Lua 한 번으로 잔액, 상태, 조회 기준시각, cursor 이후 거래를 읽어 서로 다른 시점의 결과가 섞이지 않게 한다. Banking은 provider 식별자를 내부 매핑으로만 사용하고 Asset에는 전달하지 않는다.

현재 Snapshot은 Redis 거래 이력을 한 응답에 모두 담으므로 장기 운영의 페이지 크기·보존기간·continuation token 정책은 구현하지 않았다. 현재 거래 score와 완료 시각은 Redis TIME으로 통일했으며 최초 발생 시각은 거래 데이터에 별도로 보존한다. 장기 Redis 시계 역행과 과거 score로 저장된 기존 이력의 정정 정책은 남아 있다. 포함형 cursor와 `externalTransactionId` 멱등성은 같은 밀리초 경계의 누락을 막지만 큰 시계 역행이나 보존기간 이후 누락까지 해결하지는 않는다.

## Related Tests and Documents

- `RedisTransferRepository`
- ADR-001
