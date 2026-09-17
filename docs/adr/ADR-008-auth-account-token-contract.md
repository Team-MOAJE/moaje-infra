# ADR-008: principalId, accountId, providerAccountId 식별 경계

## Status

Accepted and implemented for Banking transfer boundaries through Phase 6

## Context

초기에는 Auth 연동과 Banking 계좌 연결 Aggregate가 없었다. 현재 계좌 연결은 구현됐고 실제 Auth 규격 연동은 남아 있다. Phase 3까지는 `accountToken`이 내부 계좌 참조, Auth 토큰, 외부 계좌 참조의 의미를 섞어 사용했다. 이 상태로 Kafka와 Asset Projection을 확장하면 계좌 식별 책임이 불명확해지고 민감한 외부 계좌 식별자가 조회 모델로 번질 수 있다.

## Decision

식별자를 다음처럼 분리한다.

| 식별자 | 생성/관리 주체 | 사용 범위 | Kafka/Asset 노출 |
|---|---|---|---|
| `principalId` | Auth | 인증된 사용자 식별 | 사용자 식별이 필요한 이벤트에만 가능 |
| `accountId` | Banking | Client, Banking, Asset의 내부 계좌 참조 | 가능 |
| `providerAccountId` | Mock Banking 또는 외부 금융기관 | Banking과 Mock Banking 사이 | 불가 |
| `transferId` | Banking | 송금 거래 식별 | 가능 |
| `eventId` | Banking Outbox | Kafka 메시지/Outbox 식별 | 가능 |

`accountToken`은 더 이상 Asset Projection 계좌 식별자로 사용하지 않는다. 기존 `accountToken` 사용처는 실제 의미를 확인해 내부 계좌 참조이면 `accountId`, 외부 금융기관 참조이면 `providerAccountId`, 인증 권한 증명이면 Auth 경계로 분리한다.

Phase 4에서 Banking 송금 이벤트와 Asset TransactionSucceeded 이벤트에서는 `accountToken`, 실제 계좌번호, `providerAccountId`를 제거하고 `accountId`만 포함한다.

## Alternatives Considered

- Banking 이벤트에 실제 계좌번호 포함: 개인정보와 계좌정보 노출 위험이 있어 제외한다.
- Auth가 금융거래 규칙까지 판단: 인증/식별 책임을 넘어가므로 제외한다.
- `accountToken`을 `providerAccountId`로 일괄 rename: 기존 사용처의 의미가 섞여 있어 제외한다.

## Consequences

Banking은 `banking_account` Aggregate에 `accountId -> providerAccountId` 매핑을 저장한다. AccountCreated 이벤트는 Banking `accountId`를 전달하고 Asset은 같은 값을 Projection PK로 사용한다. Snapshot gRPC는 Asset의 `accountId`를 Banking 내부에서만 `providerAccountId`로 해석하며 외부 계좌번호는 응답에 포함하지 않는다.

Asset 자동 대사는 `accountId`로 Banking을 호출한다. Banking은 `banking_account`에서 `providerAccountId`를 찾아 Mock Banking Snapshot을 조회하고, Asset 응답에는 다시 `accountId`만 제공한다.

송금도 같은 경계를 따른다. Banking REST 요청의 `withdrawalAccountId`로 소유권과 활성 상태를 검증한 후 Mock Banking 요청의 `fromProviderAccountId`로 변환한다. Mock Banking만 이 값을 실제 원장 계좌번호로 해석한다.

## Known Limitations

2026-09-12 승인 반영: Auth가 발급한 JWT를 Gateway에서 검증하고, 검증된 `sub`를 `X-Authenticated-User-Id`로 전달한다. Banking·Asset의 공통 필터가 Principal로 변환한다. Body·Query의 사용자 ID로 fallback하지 않는다. Compose는 서비스 HTTP 직접 노출을 제거한다. 내부 네트워크 전체를 신뢰하지 않는 배포에서는 추가 인증이 필요하다.

2026-09-14 Auth 구현을 기준으로 `iss=moaje-auth`, 숫자형 사용자 ID 문자열 `sub`, `typ=access`, `jti`, `iat`, `exp`를 검증한다. 현재 HS256은 Auth와 Gateway가 같은 비밀키를 환경변수로 주입하고, 향후 RS/ES 전환 시에는 JWKS를 사용한다. `aud`는 Auth의 `JWT_AUDIENCE`가 설정된 경우 Gateway에도 같은 값을 설정한다. 값이 없으면 검증을 우회하지 않는다.

계좌 개설 API의 Auth 개인정보 조회 및 서비스 간 인증 계약은 여전히 별도 합의가 필요하다. 송금 경로는 Request Body의 사용자 값을 인증 근거로 사용하지 않지만, 전체 Auth·Work gRPC 인증 규격까지 확정한 것은 아니다.

수취 계좌는 외부 송금 목적지이므로 현재 요청과 Transaction Journal에 식별값이 남는다. 암호화·토큰화·보존 기간은 실제 외부기관 계약과 개인정보 정책이 정해질 때 후속 결정해야 한다.

## Related Tests and Documents

- `BankingAccount.providerAccountIdForTransfer`
- `TransferCommandServiceIdempotencyTest`
- `TransferServiceProviderAccountTest`
- `BankingTransferEventPublisher`
- `TransferApplicationServiceIdempotencyJpaTest`
