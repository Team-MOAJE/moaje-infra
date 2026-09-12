# ADR-011: 스냅샷 조회 경계와 Work 거래 시각

## Status

2026-09-12 Implemented. 사용자 승인: 짧은 외부 거래 조회, 내부 헤더 Principal 전달, Work 반전 제외. 30초/5초 기본값과 Work 시각 확인 방식은 이번 구현의 구체화이며 운영 SLA 승인이 아니다.

## Context

이벤트 반영이 대사 cursor를 움직이면 미수집 외부 이력을 건너뛸 수 있다. 스냅샷이 먼저 저장한 거래를 늦은 Kafka 이벤트가 다시 만들 수도 있다. Work 성공 이벤트에 복구 시각을 원 거래 시각으로 넣으면 날짜별 통계가 달라진다.

## Decision

- 이벤트 수신 시각·감사 완료 시각·계정계 조회 cursor를 분리한다. 정상 이벤트로 복구 필요·소진 상태를 지우지 않는다.
- 같은 외부 거래 ID는 계좌·금액·방향을 검증한 뒤 Banking 거래 ID만 연결한다. DB Unique와 계좌 Row Lock을 유지한다.
- 계좌/시도별 lease token을 사용하고, 조회 중 이벤트가 반영되면 lease를 취소해 오래된 스냅샷을 버린다.
- Work Outbox는 계정계 원시각 확인 후 같은 Asset DB 트랜잭션에서 한 번 생성한다. 발생·완료·복구·생성 시각을 구분한다.
- 반전과 원시각 미확인 구버전 Outbox는 발행 성공으로 표시하지 않고 별도 제외한다. 이미 발행된 과거 통계는 수정하지 않는다.
- 스냅샷 잔액은 거래 직후 잔액과 다르므로 새 필드로 구분한다. 기존 protobuf 번호는 재사용하지 않는다.

## Alternatives Considered

- eventId만 중복 검사: 새 eventId로 들어온 동일 외부 거래를 막지 못한다.
- 외부 거래마다 현재 시각으로 Work 이벤트 생성: 빠르지만 과거 거래 날짜를 잘못 집계한다.
- 원시각을 Banking 이벤트·Journal 전체에 즉시 추가: 가능하지만 현재 스냅샷 경로로 확인할 수 있어 이번에는 작은 변경을 우선한다.
- 모든 조회를 DB 트랜잭션 안에서 수행: 네트워크 지연 동안 DB Lock을 점유하므로 제외한다.

## Consequences

조회 모델 정합성과 통계 시각이 개선된다. Work 전달은 다음 정기 조회까지 늦어질 수 있다. Asset V3 migration과 additive protobuf 변경이 필요하며 첫 대사는 전체 이력을 확인한다. 배포는 Mock/Banking의 스냅샷 필드 지원 후 Asset, 그 다음 Work 소비 계약 검증 순으로 진행한다. 새 optional 완료 시각을 제공하지 않는 구버전 계정계는 미확인 완료 시각으로 처리한다.

## Known Limitations

단일 Worker·배치 20개는 모든 규모에서 1분 이내를 보장하지 않는다. 지속적인 이벤트 경합은 감사 완료를 늦출 수 있다. Redis 시각 기반 cursor는 장기 시계 역행이나 이력 삭제까지 해결하지 않는다. Asset→Work Publisher의 DB 밖 발행·Lease·제한 재시도와 Work 중복 소비 구현은 별도 과제다. 2026-09-12 실제 Redis 통합 테스트 2개, 격리 Compose 29개 및 재생성한 일반 로컬 환경 23개 검사가 통과했다. 외부 출금 수집과 Kafka 복구 시 중복 반영 방지를 확인했지만 실제 Auth·Work 소비나 구 데이터를 유지한 DB 전환은 검증하지 않았다. 상세 결과는 중앙 개발 기록에 남긴다.

## Related Tests and Documents

- `AccountSnapshotBoundaryTest`
- `AssetProjectionReconciliationServiceJpaTest`
- `AssetWorkEventPolicyTest`
- `GatewayJwtRoutingTest`
- `RedisSnapshotCursorIntegrationTest` (별도 Redis 실행 필요)
- [학습 및 검증 기록](/C:/moaje/moaje-infra/docs/phase-history-and-retrospective.md)
