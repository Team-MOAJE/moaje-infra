# ADR-007: REST·gRPC Adapter와 Application Use Case 경계

## Status

Accepted and implemented in Phase 6

## Context

Phase 6 이전 REST 송금은 `TransferCommandService`를 호출했지만 gRPC `ExecuteTransfer`는 `MockBankingApiClient`를 직접 호출했다. 또한 Asset 수동 새로고침 경로가 Banking을 호출한 뒤 Banking이 다시 Asset의 `ApplyExternalTransaction`을 호출해 순환 동기 의존과 별도 반영 경로를 만들었다.

## Decision

사용처가 없는 `ExecuteTransfer`, `SyncExternalAccountTransactions`, `ApplyExternalTransaction` RPC와 구현을 제거한다. Asset Projection 자동 대사는 Asset이 Banking의 `GetTransferProjectionStates`, `GetAccountProjectionSnapshot` 읽기 Use Case만 호출하며, Banking이 Asset으로 되돌아가는 동기 호출은 두지 않는다.

송금 명령의 현재 Inbound Adapter는 REST 하나이며 반드시 `TransferCommandService`를 호출한다. 향후 gRPC 송금 Adapter가 필요하면 같은 Use Case를 호출해야 한다. `withdrawalAccountId`는 Banking Application에서 소유권과 상태를 검증한 후 `providerAccountId`로 변환하고, 실제 계좌번호 해석은 Mock Banking 내부에서만 수행한다.

Banking gRPC 서버와 Asset의 Banking Client는 mTLS를 기본으로 사용한다. 서버는 `ClientAuth.REQUIRE`로 신뢰한 클라이언트 인증서를 요구하고, 클라이언트도 Banking 서버 인증서를 검증한다. 인증서 설정이 빠졌을 때 plaintext로 자동 전환하지 않으며 시작 또는 첫 채널 생성이 실패한다. 테스트에서만 `tls.enabled=false`를 명시할 수 있다.

## Alternatives Considered

- gRPC 우회 경로 유지: 상태 저장과 이벤트 발행 누락 위험이 있어 제외한다.
- gRPC 전체 제거: 동기 동기화 유스케이스까지 삭제될 수 있어 제외한다.
- 애플리케이션 토큰만 Metadata에 전달: 전송 계층의 서버 신원 검증과 인증서 기반 클라이언트 인증을 함께 제공하지 못해 제외한다.
- 공용 CA를 모든 내부 서비스가 공유: 인증서 하나가 유출되면 불필요한 서비스까지 접근할 수 있어 Banking↔Asset 전용 Trust Bundle을 우선한다.

## Consequences

REST와 gRPC의 요청 모델은 다를 수 있지만 도메인 상태 전이는 하나의 Application Service에 모인다. 순환 호출과 수동 refresh 경로가 사라져 Asset 복구는 Scheduler와 동일한 Snapshot Use Case를 사용한다.

mTLS 인증서 발급, 갱신, 폐기와 Secret 배포는 운영 책임이 추가된다. Trust Bundle에 어떤 인증서를 넣는지가 실제 서비스 권한 범위를 결정하므로 Asset 전용 클라이언트 인증서 또는 전용 CA만 신뢰해야 한다.

## Known Limitations

저장소 밖에 구 RPC를 호출하는 배포 클라이언트가 있다면 계약 삭제 전에 별도 전환이 필요하다. 저장소 검색에서는 사용처가 확인되지 않았다.

Auth·Work를 포함한 공통 서비스 인증/인가 규격은 아직 확정되지 않았다. 현재 구현은 Banking↔Asset 인증서 신뢰 경계만 보장하며 사용자 권한을 대신하지 않는다.

## Related Tests and Documents

- `TransferCommandServiceIdempotencyTest`
- `BankingGrpcServerMutualTlsTest`
- `BankingTransferProjectionClientMutualTlsTest`
- `TransferServiceProviderAccountTest`
- `moaje-grpc-contracts/proto/grpc/banking_service.proto`
