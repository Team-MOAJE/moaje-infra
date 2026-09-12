# ADR-002: 송금 Idempotency-Key 정책

## Status

Accepted

## Context

Phase 2 이전 Banking REST 요청은 `idempotencyKey`가 없으면 UUID를 생성한다. Gateway도 검증 기능은 있지만 배포 설정에서는 unsafe method에 키를 필수로 요구하지 않는다. 이 상태에서는 클라이언트 재시도가 중복 송금으로 이어질 수 있다.

## Decision

모든 송금 요청은 클라이언트가 생성한 `Idempotency-Key`를 포함해야 한다. Gateway는 우선 `POST /api/v1/banking/transfers`에만 좁게 헤더 존재와 기본 형식을 검증한다. 로그인, 프로필 조회 같은 일반 API에는 전역 적용하지 않는다. Banking Application 계층도 Gateway 검증과 별개로 키를 필수로 검증한다.

최종 멱등성 보장은 Banking DB의 `(principal_id, operation_type, idempotency_key)` Unique Constraint와 Application Service가 담당한다. `principal_id`는 클라이언트 요청 본문의 `requesterUserId`를 신뢰하지 않고 인증된 Principal에서 가져온 값을 사용한다. 현재 Gateway가 검증한 JWT sub를 내부 헤더로 전달하고 서비스 필터가 Principal로 변환한다. Auth의 issuer·audience·공개키 계약은 미정이며 빈 설정에서는 인증을 허용하지 않는다.

동일 주체가 같은 키와 같은 요청 본문으로 재요청하면 외부 계정계를 다시 호출하지 않고 기존 거래 상태를 반환한다. 같은 키에 다른 요청 본문이 오면 `409 Conflict`로 처리한다.

Request Hash는 송금의 의미를 결정하는 다음 필드만 canonical form으로 직렬화해 계산한다.

- `operationType`
- `withdrawalAccountId`
- `depositBankCode`
- 수취 계좌 식별값
- `amount`
- `currency`

`ci`, `userName`, `phoneNumber`는 개인정보이며 언제든 변경될 수 있으므로 hash 대상에서 제외한다. Canonicalization은 필드 순서를 고정하고, 숫자/통화 표현을 정규화하며, null과 빈 문자열 처리 기준을 코드와 테스트에 남긴다. 원문 요청, 평문 계좌번호, 개인정보는 로그에 남기지 않는다.

## Alternatives Considered

- 사용자, 계좌, 금액, 시간 범위로 유사 거래 차단: 정상 반복 송금까지 막을 수 있어 제외한다.
- Gateway Redis 멱등성만 사용: TTL 만료와 우회 호출에 취약해 Banking DB 보장을 추가한다.
- 일반 SHA-256 Hash: 현재 프로젝트 구현이 단순하고 새 보안 인프라가 필요 없다. 단, DB가 유출되면 제한적인 사전 대입 공격 가능성이 남는다.
- HMAC-SHA-256: 서버 secret이 있어 request hash 위변조/추측 저항성이 높다. secret 관리와 rotation 정책이 필요하므로 Phase 2에서는 사용자 승인 없이 도입하지 않는다.

## Consequences

현재 일반 SHA-256을 구현했으며 Canonicalization과 감사 로그 비노출을 테스트로 보호한다. HMAC이 필요하다고 판단되면 별도 ADR 업데이트와 사용자 승인을 받은 뒤 도입한다.

## Known Limitations

내부 헤더는 자체 서명 정보가 아니므로 서비스 HTTP 직접 접근을 제한해야 한다. Application의 허용 문자·길이 검증과 Hash 정규화 대상의 실제 외부 요청 표현 일치 여부는 추가 검증이 필요하다. Gateway 멱등성 적용 범위는 송금 API부터 시작하고, 추후 결제/출금이체 등 금융 명령 API로 확장한다.

## Identifier Dictionary

| Identifier | 생성 주체 | 유효 범위 | 변경 가능성 | 외부 노출 여부 | DB 저장 여부 |
|---|---|---|---|---|---|
| `principalId` | 인증 시스템의 검증된 JWT `sub` | 모아제 내부 사용자 식별 | 사용자 계정이 유지되는 동안 안정적이어야 함 | 필요한 내부 이벤트에만 포함, 사용자 식별정보로 보호 | `banking_transfer.principal_id` |
| `withdrawalAccountId` | Banking | 출금 계좌를 가리키는 모아제 내부 계좌 ID | 생성 후 불변 | Client 요청과 Kafka 이벤트에 내부 식별자로 노출 가능 | `banking_transfer.withdrawal_account_id` |
| `idempotencyKey` | Client | 같은 principal의 같은 operation 안에서 한 송금 의도 | Client 재시도 동안 불변 | HTTP `Idempotency-Key` 헤더로 노출 | `banking_transfer.idempotency_key` |
| `transferId` | Banking | Banking Transfer Aggregate PK | 생성 후 불변 | Mock Banking에는 `clientTransferId` 계약명으로 전달, Kafka 거래 식별자 및 Outbox `aggregateId` | `banking_transfer.transfer_id` |
| `externalTransactionId` | Mock Banking | 외부 계정계 거래 또는 거래내역 식별 | 외부 응답 전에는 없음, 응답 후 불변으로 취급 | 필요 시 내부 이벤트에 포함 | `banking_transfer.external_transaction_id` |
| `requestHash` | Banking | 같은 멱등성 키 요청 본문의 의미 비교 | 요청 의미 필드가 같으면 동일 | 외부 노출하지 않음 | `banking_transfer.request_hash` |

`transferId`, Mock Banking 요청 DTO의 `clientTransferId`, Kafka 거래 식별자 및 Outbox `aggregateId`는 같은 값을 다른 계층의 언어로 부르는 것이다. Phase 2에서는 별도 `clientTransferId` 컬럼을 만들지 않는다.

## Related Tests and Documents

- `TransferCommandServiceIdempotencyTest`
- `TransferControllerIdempotencyTest`
- `GatewayIdempotencyPolicyCharacterizationTest`
