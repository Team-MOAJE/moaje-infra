# 모아제 공개 문서

구현 이력·검증 결과·아키텍처 결정을 모읍니다. 개인 학습 노트는 공개 문서에서 분리했습니다.

| 문서 | 읽는 목적 |
|---|---|
| [로컬 실행·연동 준비](../readMe.md) | Compose 시작, 인증 설정, 팀원 합류 조건 |
| [공통 계약](https://github.com/Team-MOAJE/moaje-grpc-contracts/tree/main/proto) | gRPC·Kafka 메시지의 Protobuf 원본 |
| [Phase별 기록·회고](phase-history-and-retrospective.md) | 네 모듈의 변화, 검증 결과, 남은 일, 문서 통합 내역 |
| [ADR](adr) | 왜 이 설계를 선택했는지와 대안·비용 |

## 현재 실행 상태

2026-09-12: **격리 Compose의 Kafka 장애 포함 29개 검사와 재생성한 일반 환경의 23개 연동 검사가 통과했습니다.** 기존 MySQL 실패 원인을 확인하고, 별도 검증 성공 후 사용자 승인 범위의 개발 볼륨 5개를 백업·초기화했습니다. 당시 네 앱의 기동을 확인했으며 선택 도구와 자동 재시작은 꺼 두었습니다. Auth·Work 실제 연동과 Swagger는 아직 미완료입니다. [검증·회고](phase-history-and-retrospective.md#verification), [Auth·Work 연결 준비](../readMe.md#authwork-합류-준비)를 확인하세요.

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
