# Work 연동 검사 결과

검사일: 2026-10-10. Work `dev`: `75051b6` → `0f73ea5` fast-forward.
Work 업무 코드는 직접 수정하지 않았다. 기존 Compose 설정을 사용하고 Work·Asset 이미지를 다시 빌드했다.

## 1. 재구성한 환경

- 기존 DB·Redis·Kafka 볼륨을 보존했다. 이번 작업에서 볼륨은 삭제하지 않았다.
- Work·Asset 이미지를 빌드하고 나머지는 기존 이미지로 실행했다. Work 시작 시 자체 스키마 보정으로 컬럼 1개와 인덱스 2개를 추가했다.
- 이 검사 당시 앱·기반 서비스 13개를 실행했다. 현재 실행 상태를 뜻하지 않는다. 인증서 초기화 컨테이너는 성공 종료가 정상이다.
- `tools`, `monitoring`, `test-tools`는 실행하지 않았다. 다른 Compose 프로젝트의 볼륨은 삭제하지 않았다.
- Swagger: <http://localhost:8080/docs/swagger-ui.html> → Work API.

## 2. 검증 결과

| 항목 | 결과와 검증 범위 |
|---|---|
| Work·Asset 빌드·Compose 기동 | 성공. 빌드에서 단위 테스트는 실행하지 않음 |
| Gateway 문서 | 통합 Swagger 및 Work 명세 조회 성공 |
| Work DB·Redis | health 정상 |
| Work→Asset mTLS 잔액 RPC | 계좌 없음·비활성 계좌만 있음은 NOT_LINKED, ACTIVE 잔액 0원은 OK, ACTIVE 두 계좌 합계는 460,000원. CLOSED 계좌는 합산 제외 |
| 빈 사용자 ID·연결 장애 | 각각 INVALID_ARGUMENT·UNAVAILABLE. 확인된 0원과 구분 |
| Gateway 시뮬레이터 | 위 4가지 계좌 조건에서 HTTP 200. asset_source 및 금액 일치 |
| Gateway→Work 인증·소유권 | 무인증 401, 정상 JWT 학교 조회 200, 다른 사용자 경로·위조 헤더 요청 403 |
| 프로필 DB 조회·캐시 재조회 | 둘 다 200, 응답 동일. 테스트 행과 캐시 삭제 완료 |
| 공통 계약 호환성 | 불일치 0건. 잔액 RPC·거래·집계 이벤트 검사 통과 |
| Kafka 거래 성공 소비 | 같은 거래를 다른 eventId로 보내도 거래 기록 1건. 10월 복구한 거래의 원래 발생월인 9월 유지 |
| Kafka 월별·카테고리 집계 소비 | revision 2 유지. 중복 revision 및 뒤늦은 revision 1이 최신 값을 덮어쓰지 않음 |
| 테스트 데이터 정리 | 전용 사용자의 Asset·Work DB 행과 Work 캐시 삭제 확인. 잔액 RPC가 DailyCashflow 계산 결과를 생성하지 않는 것도 확인 |

JWT는 Auth 발급 함수로 만들었으며 회원가입·로그인 전체 흐름은 검사하지 않았다.
Kafka 검사는 테스트 코드가 공통 규격의 Protobuf를 발행하고 실제 Work Consumer의 DB 결과를 확인했다. Mock → Banking → Asset Outbox → Work 전체 금융 흐름을 실행한 검사는 아니다.

## 3. 해결된 사항과 남은 범위

- 이전 검사에서 발견한 Protobuf 불일치·집계 JSON 해석 문제는 위 검사 범위에서 해결됐다.
- Work는 이제 `GetCurrentBalance`를 호출한다. 잔액 조회에 남은 일수를 전달하지 않는다.
- Work는 미연동 상태에서 시뮬레이터에 0원을 사용하되 `asset_source=NOT_LINKED`로 구분한다. 정상 잔액 0원의 `ASSET_SERVICE`와 화면에서도 구분해야 한다.
- Work가 발행하는 JSON 이벤트의 공통 Protobuf 전환과 Consumer 장애 재처리·DLT 정책은 별도 합의 대상이다.
- XGBoost 모델 로딩에 버전 호환 경고가 있다. 이번 검사는 AI 예측 품질을 검증하지 않았다.

Infra는 `ASSET_GRPC_TARGET=asset:9090`, CA `/run/grpc/ca.crt`, 인증서 `/run/grpc/work.crt`, 개인키 `/run/grpc/work.key`를 제공한다. Work는 이 경로를 사용하며 평문 호출로 우회하지 않는다.
`WORK_INTERNAL_TOKEN`을 별도로 설정하지 않으면 운영용 API가 503으로 닫히는 것은 의도한 동작이다.

## 4. 재현 명령

`C:\moaje\moaje-infra`에서 실행한다. Git Bash:

```bash
bash tests/work-smoke.sh
bash tests/work-profile-smoke.sh
bash tests/work-asset-integration.sh
```

두 번째 검사는 전용 사용자 `880000000000000001`의 행·캐시가 이미 있으면 중단한다. 비어 있을 때만 생성하고 종료 시 삭제한다. 실제 사용자 데이터로 바꾸지 않는다.

세 번째 검사는 예약 사용자 `880000000000000011`~`880000000000000014`와 계좌 5개로 RPC·Gateway·Kafka를 검사한다. 기존 예약 데이터가 있으면 중단하며 종료 시 테스트 DB 행·캐시를 삭제한다. **Kafka 테스트 메시지는 보존 기간까지 남으므로 로컬 개발 환경에서만 실행한다.** 강제 종료 시 정리 코드가 실행되지 않을 수 있으므로 예약 ID의 잔여 데이터를 확인한다.

계약 검사, PowerShell:

```powershell
docker compose --profile apps run --rm --no-deps `
  -v C:/moaje/moaje-grpc-contracts/proto:/contracts:ro `
  -v C:/moaje/moaje-infra/tests/work-contract-check.py:/tmp/work-contract-check.py:ro `
  -e PYTHONPATH=/app work python /tmp/work-contract-check.py /contracts
```

현재 계약 검사 결과는 **0 failures, 종료 코드 0**이다. 이 계약 검사 자체는 DB·Kafka에 데이터를 기록하지 않는다.

## 5. 관련 Infra 파일

| 파일 | 역할 |
|---|---|
| `grpc/init-certs.sh` | 기존 CA를 유지하며 누락된 Work 인증서만 발급 |
| `docker-compose.yaml` | 인증서 읽기 전용 마운트, 환경변수·기동 의존 조건·health 검사 |
| `.env.example` | 운영 API 토큰 설정 안내 |
| `tests/work-smoke.sh` | 문서·인증·사용자 불일치 차단·mTLS 연결 검사 |
| `tests/work-profile-smoke.sh` | 프로필 조회·캐시 재조회와 테스트 데이터 정리 |
| `tests/work-contract-check.py` | 공통 Proto와 Work 생성 코드·소비 분기 비교 |
| `tests/work-asset-integration.sh` | 실행 중인 Compose에서 설정과 테스트 JWT를 읽어 검사 실행 |
| `tests/work-asset-integration.py` | 계좌별 잔액·시뮬레이터·Kafka 중복·revision 검사 및 데이터 정리 |
| README·테스트 가이드·토픽 문서 | 현재 성공 범위와 남은 계약 문제 반영 |

이 문서는 Work 연동 검사 당시의 기록이다. 후속 격리 통합 시험에서 발견한 문제와 최신 결과는 [종합 통합 테스트 기록](full-integration-test-plan.md)을 참고한다.
