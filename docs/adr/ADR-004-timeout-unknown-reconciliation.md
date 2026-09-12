# ADR-004: Timeout, UNKNOWN, Reversal, Reconciliation 정책

## Status

Accepted and partially implemented

## Context

Timeout은 원거래 실패가 아니라 응답을 받지 못한 상태다. Banking은 Timeout을 `UNKNOWN`으로 기록하고, Mock Banking의 `clientTransferId` 강한 일관성 조회를 통해 나중에 성공 또는 실패를 확정해야 한다.

`markProcessing` 이후 Mock Banking 호출이 실행된 뒤 Banking 서버가 중단되면 DB에는 `PROCESSING` 거래가 남을 수 있다. 반대로 정상 처리 중인 요청도 짧은 시간 동안 `PROCESSING`이므로, 대사 Worker는 일정 시간 이상 오래된 `PROCESSING`만 가져가야 한다.

예외 처리만으로는 정상 처리와 오래된 처리를 나누는 시간 경계를 알 수 없다. `ResourceAccessException`은 연결 또는 응답 대기가 끝났다는 결과이고, `connectTimeout`과 `readTimeout`은 각각 언제 그 대기를 끝낼지 정하는 입력이다. 이 시간이 명시되지 않으면 `PROCESSING` stale 기준을 안전하게 계산할 수 없다.

## Decision

Timeout, 연결 종료, 응답 유실은 `UNKNOWN` 거래 상태로 기록하고 대사 대상으로 관리한다. Banking은 `transferId`를 Mock Banking 요청 DTO의 `clientTransferId` 필드로 전달한다. Mock Banking은 같은 `clientTransferId` 송금을 중복 실행하지 않아야 하며, 같은 키로 강한 일관성 결과 조회를 제공한다.

Reconciliation 대상은 `UNKNOWN`과 일정 시간 이상 지난 `PROCESSING`이다. Mock Banking 조회 결과가 `SUCCEEDED`이면 Banking 거래를 `SUCCEEDED`로 복구하고 Outbox 이벤트를 생성한다. 강한 일관성 조회가 `NOT_FOUND`를 반환하면 송금 요청이 처리되지 않은 것으로 보고 `FAILED`로 확정한다. 조회 timeout, 5xx, 연결 오류는 실패 확정이 아니라 조회 실패로 기록하고 `UNKNOWN` 또는 대사 필요 상태를 유지한다.

Mock Banking `RestClient`에는 `connect-timeout-ms=3000`, `read-timeout-ms=30000`을 명시한다. `processing-stale-after-ms`는 다음 식을 반드시 만족해야 하며, 애플리케이션 시작 시 `TransferProcessingTimingPolicy`가 검증한다.

```text
processingStaleAfterMs > connectTimeoutMs + readTimeoutMs + processingStaleSafetyMarginMs
120000 > 3000 + 30000 + 30000
```

안전 여유는 외부 응답 이후 Banking 결과 저장, 스케줄러 실행 편차, 짧은 JVM 정지와 CPU 지연을 흡수한다. 합계와 같은 값도 원 요청과 Worker가 같은 시각에 경쟁할 수 있으므로 허용하지 않는다.

여러 Banking 인스턴스가 같은 거래를 동시에 대사하지 않도록 `reconciliation_locked_at`, `reconciliation_locked_until`, `reconciliation_lock_owner`를 사용하는 lease를 둔다. Worker가 선점 후 종료되어도 `locked_until`이 지나면 다른 Worker가 다시 처리할 수 있다.

조회 장애가 반복되는 거래는 `reconciliation_attempt_count`와 `next_reconciliation_at`으로 제한된 backoff 재시도를 수행한다. `max-attempts`를 모두 소진하면 `reconciliation_retry_exhausted=true`로 남기고 자동 대사 대상에서 제외해 운영 확인 대상으로 보존한다.

운영 관찰을 위해 pending, locked, retry exhausted gauge와 claimed, resolved, lookup failed, retry exhausted total counter를 노출한다. Metric tag에는 `transferId`나 사용자 ID처럼 값 종류가 계속 늘어나는 식별자를 사용하지 않는다.

Reverse는 원거래 성공이 확인되고 업무상 보상 거래가 필요한 경우에만 수행한다. `CANCELED`는 최종 완료 전 취소, `REVERSED`는 이미 성공한 금융거래의 반전 효과로 정의한다.

현재 모아제에는 보상 실행을 허용할 업무 사유와 승인 정책이 없으므로 Banking은 reverse 요청 기능을 제공하지 않는다. Reconciliation이 `UNKNOWN` 또는 오래된 `PROCESSING`을 조회하다 이미 `REVERSED`인 결과를 확인한 경우에만 Banking을 `REVERSED`로 확정하고 Asset용 Completed와 Reversed Outbox를 함께 생성한다.

Asset은 원 `TRANSFER_OUT` 이력을 유지한 채 `REVERSAL_IN`을 별도 금융 효과로 추가한다. Reversed가 Completed보다 먼저 도착하면 잔액을 즉시 증가시키지 않고 `PENDING REVERSAL_IN`과 `SYNC_REQUIRED`를 남긴 뒤 Completed 처리 시 같은 계좌 Lock과 DB 트랜잭션 안에서 두 효과를 완결한다.

## Alternatives Considered

- Timeout 즉시 실패 처리: 실제 성공 거래를 실패로 오판할 수 있어 제외한다.
- Timeout 즉시 reverse: 원거래 성공 여부를 모르는 상태에서 보상 거래를 시작하므로 후속 검토로 미룬다.
- `UNKNOWN`만 대사: `PROCESSING` 저장 후 서버가 종료되는 장애를 복구할 수 없어 제외한다.
- 모든 `PROCESSING` 대사: 정상 처리 중인 요청을 Worker가 가져갈 수 있어 오래된 시간 조건을 둔다.
- Timeout을 HTTP 클라이언트 기본값에 위임: 환경마다 대기 시간이 달라져 stale 기준의 근거가 사라지므로 제외한다.
- `readTimeout`만 stale 계산에 반영: 연결 수립도 정상 요청이 소비할 수 있는 시간이므로 최악의 정상 처리 구간을 보호하기 위해 `connectTimeout`도 포함한다.

## Consequences

Mock Banking은 `GET /api/transfers/{clientTransferId}` 조회 API를 제공한다. Banking은 `processingStartedAt`, `reconciliationAttemptCount`, `lastReconciliationFailureReason`, `lastReconciledAt`, lease 필드, 다음 재시도 시각, 재시도 소진 여부를 기록한다. 대사로 확정된 성공/실패 결과와 Outbox 생성은 하나의 DB 트랜잭션 안에서 수행한다.

## Known Limitations

2026-09-12 코드 재확인: Mock 조회는 필수 필드가 빠진 레코드도 null로 반환할 수 있다. 손상 데이터를 NOT_FOUND로 숨기지 않도록 보강해야 한다. 강한 일관성 조회는 그 시점의 부재를 뜻할 뿐 아직 실행 가능한 지연 요청의 종료나 삭제된 과거 성공까지 증명하지 않는다. 따라서 NOT_FOUND→FAILED의 보존·최종성 전제는 운영 수준에서 미완료다.

REQUESTED 저장 직후 중단은 현재 Worker가 조회하지 않는다. 송금 요청 자체의 5xx/일부 RestClientException은 FAILED로 매핑하는 잔재가 있어 UNKNOWN 분류 보강이 필요하다. 조회 API의 5xx 처리와 구분한다.

보상 실행 API, `REVERSAL_PENDING`, 승인 권한과 사유 코드, 부분 보상은 구현하지 않는다. 현재 대사는 `UNKNOWN`과 오래된 `PROCESSING`만 조회하므로 이미 `SUCCEEDED`로 끝난 뒤 외부에서 독립적으로 반전된 거래는 자동 발견하지 못한다. 이를 지원하려면 외부 상태 변경 알림 또는 성공 거래 감사 대사 정책이 필요하다.

Lease는 중복 처리를 줄이지만, lease 만료 뒤 늦은 응답이 돌아오는 경우를 완전히 없애지는 못한다. 그래서 결과 반영 시점에 lease owner를 다시 확인한다.

현재 시간 정책은 한 번의 작은 JSON 응답을 전제로 한 보수적인 상한이다. 운영 지연 분포를 측정한 값은 아니므로, 실제 배포 후 외부 호출 latency와 `PROCESSING` 체류 시간을 측정해 Timeout과 안전 여유를 조정해야 한다.

## Related Tests and Documents

- `TransferCommandServiceIdempotencyTest`
- `TransferReconciliationServiceTest`
- `TransferProcessingTimingPolicyTest`
- `RestClientConfigTest`
- `TransferControllerLookupTest`
- `BankingTransferReversedStateTest`
- `TransferApplicationServiceIdempotencyJpaTest`
- `moaje-infra/docs/learning/asset.md`
