# 모아제 공개 문서

구현 이력·검증 결과·아키텍처 결정을 모읍니다. 개인 학습 노트는 공개 문서에서 분리했습니다.

| 문서 | 읽는 목적 |
|---|---|
| [로컬 실행·연동 준비](../readMe.md) | Compose 시작, 인증 설정, 팀원 합류 조건 |
| [통합 API 테스트 가이드](integrated-api-test-guide.md) | 통합 Swagger로 Auth·Banking·Asset 흐름을 직접 검증하는 절차 |
| [Kafka Topic 정리](kafka-topics.md) | 서비스별 발행·소비 토픽과 미확정 계약 |
| [공통 계약](https://github.com/Team-MOAJE/moaje-grpc-contracts/tree/main/proto) | gRPC·Kafka 메시지의 Protobuf 원본 |
| [Phase별 기록·회고](phase-history-and-retrospective.md) | 네 모듈의 변화, 검증 결과, 남은 일, 문서 통합 내역 |
| [ADR](adr) | 왜 이 설계를 선택했는지와 대안·비용 |

## 현재 실행 상태

2026-09-18: **Auth·Gateway·Banking·Mock Banking·Asset 통합 기동과 Gateway JWT 라우팅, Asset 집계 Outbox의 Kafka 적재를 확인했습니다.** 통합 Swagger에서 Auth·Banking·Asset 문서를 전환할 수 있으며, Fixture Console로 과거 여러 달의 집계용 거래를 만들 수 있습니다. Work의 실제 소비 연동은 후속 작업입니다. [통합 API 테스트 가이드](integrated-api-test-guide.md)와 [검증·회고](phase-history-and-retrospective.md#verification)를 확인하세요.

## ADR 목록

| 번호 | 결정 |
|---|---|
| [001](adr/ADR-001-source-of-truth.md) | 실제 잔액·거래 상태·조회 데이터의 기준 |
| [002](adr/ADR-002-idempotency.md) | 송금 Idempotency-Key와 식별자 사전 |
| [003](adr/ADR-003-transactional-outbox.md) | 발송 대기함과 보장 범위 |
| [004](adr/ADR-004-timeout-unknown-reconciliation.md) | Timeout·UNKNOWN·반전·대사 |
| [005](adr/ADR-005-asset-inbox-projection-idempotency.md) | 메시지와 금융 효과의 중복 방지 |
| [006](adr/ADR-006-remove-asset-reserve.md) | Asset이 송금을 승인하지 않는 이유 |
| [007](adr/ADR-007-adapter-usecase-boundary.md) | REST/gRPC 경계·mTLS |
| [008](adr/ADR-008-auth-account-token-contract.md) | 사용자·내부 계좌·외부 계좌 식별 |
| [009](adr/ADR-009-mock-banking-as-core.md) | 실습용 계정계의 한계 |
| [010](adr/ADR-010-kafka-consumer-retry-dlt.md) | Consumer 재시도·DLT·복구 |
| [011](adr/ADR-011-projection-cursor-and-work-time.md) | 스냅샷 조회 경계와 Work 거래 시각 |

## 문서 관리 원칙

실행 안내는 저장소 README, 실제 검증·교훈은 통합 회고, 중요한 설계 선택은 ADR에 반영합니다. 회고를 사용자의 실제 경험인 것처럼 꾸미거나 실행하지 않은 성능을 쓰지 않습니다. 같은 저장소 안에서는 상대 링크, 다른 저장소는 GitHub의 main 기준 링크를 사용합니다. 공통 Proto 원본은 `moaje-grpc-contracts`에 유지합니다.
