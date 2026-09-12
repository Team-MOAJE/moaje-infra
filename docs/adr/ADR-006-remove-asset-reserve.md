# ADR-006: Asset에서 Reserve를 제거한 이유

## Status

Accepted

## Context

기존 학습 문서에는 Asset Reserve가 남아 있다. 하지만 실제 코드에는 Reserve 구현이 없고, 최신 결정은 Asset을 승인자가 아닌 Projection으로 둔다.

## Decision

Asset Reserve는 제거된 설계로 확정한다. Asset은 잔액 부족 여부를 승인하지 않고 Mock Banking 결과 이벤트를 반영한다.

## Alternatives Considered

- Asset 선차감 Reserve: UX는 빠를 수 있지만 Asset이 금융 원장처럼 동작해 Source of Truth 경계가 흐려진다.
- Banking 내부 Reserve: Banking도 잔액 원장을 갖지 않으므로 제외한다.

## Consequences

송금 승인 결과는 Mock Banking이 결정한다. Asset 장애는 화면 최신성에 영향을 주지만 실제 송금 결과에는 영향을 주지 않는다.

## Known Limitations

사용자에게 즉시 잔액 변화를 보여주는 UX는 이벤트 지연을 고려해 별도 표시가 필요하다.

## Related Tests and Documents

- ADR-001
- Phase 6 legacy document cleanup
