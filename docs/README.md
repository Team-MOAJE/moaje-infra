# 모아제 공개 문서

모아제의 아키텍처 결정 기록과 관련 기술 자료를 모았습니다.

| 문서 | 읽는 목적 |
|---|---|
| [로컬 실행·연동 준비](../readMe.md) | Compose 시작, 인증 설정, 팀원 합류 조건 |
| [프론트엔드 API 목록 PDF](../output/pdf/moaje-frontend-api-guide-20261011.pdf) | 2026-10-14 갱신: 계좌 목록, 은행 정보, 문자열 ID·커서 규격 포함 |
| [공통 계약](https://github.com/Team-MOAJE/moaje-grpc-contracts/tree/main/proto) | gRPC·Kafka 메시지의 Protobuf 원본 |
| [ADR](adr) | 왜 이 설계를 선택했는지와 대안·비용 |

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
