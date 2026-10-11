# Moaje Infra

Gateway와 로컬 통합 실행 환경을 관리합니다. Auth·Banking·Asset·Work·Mock은 별도 저장소이며, Compose로 연결합니다.

- [공개 문서와 ADR](docs/README.md)
- [개발 기록과 검증 결과](docs/phase-history-and-retrospective.md)
- [Compose 설정](docker-compose.yaml)
- [JWT 환경변수 안내](.env.example)
- [연동 검사 스크립트](tests/compose-smoke.ps1)
- [통합 Swagger·테스트 데이터 가이드](docs/integrated-api-test-guide.md)

## 로컬 실행

같은 상위 폴더 아래에 `moaje-infra`, `moaje-auth`, `moaje-banking`, `moaje-asset`, `moaje-work`, `moaje-grpc-contracts`, `backing-mockup`을 배치합니다. 마지막 폴더는 [moaje-mockup-banking](https://github.com/Team-MOAJE/moaje-mockup-banking) 저장소를 받은 경로입니다. Docker 엔진이 실행 중이어야 합니다.

```powershell
# moaje-infra 폴더에서만 실행한다. 개별 저장소의 Compose는 함께 실행하지 않는다.
docker compose --profile apps up -d --build
```

Gateway는 `http://localhost:8080`, Mock은 `http://localhost:8081`입니다. Auth·Banking·Asset·Work HTTP는 호스트에 직접 공개하지 않고 Compose 내부에서만 연결합니다. 도구는 `tools`, 모니터링은 `monitoring` 프로필을 선택해야 실행되며 자동 재시작은 꺼져 있습니다. gRPC 개발 인증서는 최초 실행 시 생성됩니다.

월별 집계 테스트가 필요하면 테스트 도구를 함께 실행한 뒤 `http://localhost:8090`에서 페르소나 데이터를 생성합니다.

```powershell
docker compose --profile apps --profile test-tools up -d --build
```

Auth JWT의 `sub`는 숫자형 사용자 ID를 담은 문자열이며, `typ=access`, `jti`, `iat`, `exp`, `iss=moaje-auth`를 검증합니다. 현재 HS256을 사용할 때 Gateway의 `AUTH_JWT_SECRET_KEY`에는 Auth의 `SECRET_KEY`와 같은 값을 안전하게 주입해야 합니다. 비밀키·실제 토큰은 커밋하지 않으며, 설정이 없다고 인증을 우회하지 않습니다.

Auth는 시작할 때 Alembic migration을 적용하고, Banking·Asset의 새 DB는 Flyway migration과 Hibernate validate로 시작합니다. 기존 데이터를 유지해야 하는 DB는 백업·별도 전환 검증이 필요합니다. Work의 초기 SQL은 새 Work DB 볼륨에만 적용됩니다. 로컬 테스트 데이터 전체 초기화는 가이드의 확인 절차를 따릅니다.

## Work 통합 실행

[Work 저장소](https://github.com/Team-MOAJE/moaje-work)를 `../moaje-work`에 복제합니다. 현재 검증 기준은 `dev`의 `0f73ea5`입니다.
`apps` 프로필에 Work API 컨테이너와 전용 MySQL 컨테이너를 추가했습니다. DB까지 한 컨테이너에 넣지 않습니다.

| 연결 | Compose 내부 주소 |
|---|---|
| Gateway → Work | `http://work:8084` (`/api/v1/work/**`) |
| Work DB | `work-mysql:3306/work_db` (호스트 포트 없음) |
| 공용 Kafka / Redis | `kafka:29092` / `redis:6379/0` |
| Consumer Group / Redis 접두어 | `moaje-work` / `work:` |

통합 Swagger `http://localhost:8080/docs/swagger-ui.html`에서 **Work API**를 선택하면 명세가 표시됩니다.
Work 명세에는 아직 Bearer 인증 선언이 없으므로 실제 호출은 JWT를 포함한 curl/Postman을 사용합니다.
기동 후 Git Bash에서 `bash tests/work-smoke.sh`로 DB·Redis·문서·무인증 차단·사용자 불일치 차단·mTLS 연결을 확인합니다. 업무 데이터는 만들지 않습니다.
Auth 발급 함수로 테스트 JWT를 메모리에서 생성하며, 회원가입·로그인 전체 테스트는 아닙니다.
`bash tests/work-profile-smoke.sh`는 전용 테스트 사용자의 프로필을 두 번 조회한 뒤 생성된 DB 행과 캐시를 삭제합니다.

2026-10-10 Work 연동 검증 당시 기존 볼륨을 보존하고 Work·Asset을 다시 빌드하여 앱과 기반 서비스 13개를 실행했습니다. 이는 현재 컨테이너의 실행 상태를 뜻하지 않습니다.
`bash tests/work-asset-integration.sh`로 실제 잔액 RPC·Gateway 시뮬레이터·Kafka 거래 및 집계 소비를 검증했습니다. 테스트 DB 행과 캐시는 삭제하며, Kafka 메시지는 보존 기간까지 남습니다.
인증서는 `certs/work`에서 Work의 `/run/grpc`로 읽기 전용 연결됩니다. CA 개인키는 Work에 전달하지 않습니다.

이전에 발견한 계약 불일치와 잔액 조회의 일수 0 문제는 해결됐습니다. 이번 Kafka 검사는 테스트 Protobuf를 실제 Work가 소비하는 범위이며 전체 금융 흐름 검증과는 구분합니다.
성공 범위와 재현 명령은 [Work 연동 검사 결과](docs/work-integration-check.md)에 정리했습니다. 스키마 변경 때마다 볼륨을 삭제하는 운영 방식은 사용하지 않습니다.

후속 격리 통합 재시험은 159개 검증 중 157개가 통과했습니다. Auth의 타인 계좌 토큰 발급과 Work의 집계 전 신규 사용자 프로필 조회는 실패하여 후속 수정이 필요합니다. 테스트 컨테이너·볼륨은 제거했고 기존 개발 볼륨은 보존했습니다. [시험 계획과 최신 결과](docs/full-integration-test-plan.md)를 참고하세요.
