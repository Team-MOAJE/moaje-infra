# 모아제 개발 문서

**처음에는 자신의 모듈 학습문서 하나를 읽고, 협력 구간에서 상대 문서를 참고하세요.** 같은 설명을 Phase마다 반복하지 않고 현재 기능 설명과 변경 이력을 분리했습니다.

| 문서 | 읽는 목적 |
|---|---|
| [Banking 학습](learning/banking.md) | 계좌 연결, 송금 멱등성, 상태, Outbox, 결과 대사, REST/gRPC |
| [Asset 학습](learning/asset.md) | 계좌 화면, 중복 이벤트, 스냅샷 복구, 생활비 계산, Work 이벤트 |
| [Mock 학습](learning/mock-banking.md) | 실제 잔액 처리, Redis Lua, 토큰/HMAC, REST 규격, 외부 거래 조회 |
| [Infra 학습](learning/infra.md) | Docker 실행, Gateway JWT, mTLS, Flyway, 테스트 방법 |
| [Phase별 기록·회고](phase-history-and-retrospective.md) | 네 모듈의 변화, 검증 결과, 남은 일, 문서 통합 내역 |
| [ADR](adr) | 왜 이 설계를 선택했는지와 대안·비용 |

## 현재 실행 상태

2026-09-12: **격리 Compose의 Kafka 장애 포함 29개 검사와 재생성한 일반 환경의 23개 연동 검사가 통과했습니다.** 기존 MySQL 실패 원인을 확인하고, 별도 검증 성공 후 사용자 승인 범위의 개발 볼륨 5개를 백업·초기화했습니다. 네 앱은 실행 중이며 선택 도구와 자동 재시작은 꺼져 있습니다. Auth·Work 실제 연동과 Swagger는 아직 미완료입니다. [검증·회고](phase-history-and-retrospective.md#verification), [Auth·Work 연결 준비](learning/infra.md#7-아직-공유되지-않은-authwork-연결-준비)를 확인하세요.

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

API·로직 변경은 해당 학습문서, 실제 검증·교훈은 통합 회고, 중요한 설계 선택은 해당 ADR에 반영합니다. 회고를 사용자의 실제 경험인 것처럼 꾸미거나 실행하지 않은 성능을 쓰지 않습니다. 새로운 임시 가이드·날짜별 보고서를 계속 늘리지 않습니다. 각 모듈 README는 이곳으로 연결하는 입구만 유지합니다. 공통 Proto 원본은 `moaje-grpc-contracts`에 계속 둡니다.
