# Moaje Infra

Gateway와 로컬 통합 실행 환경을 관리합니다. Banking·Asset·Mock은 별도 저장소이며, Compose로 연결합니다.

- [공개 문서와 ADR](docs/README.md)
- [개발 기록과 검증 결과](docs/phase-history-and-retrospective.md)
- [Compose 설정](docker-compose.yaml)
- [JWT 환경변수 안내](.env.example)
- [연동 검사 스크립트](tests/compose-smoke.ps1)
- [통합 Swagger·테스트 데이터 가이드](docs/integrated-api-test-guide.md)

## 로컬 실행

같은 상위 폴더 아래에 `moaje-infra`, `moaje-auth`, `moaje-banking`, `moaje-asset`, `moaje-grpc-contracts`, `backing-mockup`을 배치합니다. 마지막 폴더는 [moaje-mockup-banking](https://github.com/Team-MOAJE/moaje-mockup-banking) 저장소를 받은 경로입니다. Docker 엔진이 실행 중이어야 합니다.

```powershell
# backing-mockup 폴더에서
docker compose up -d --build
# moaje-infra 폴더에서
docker compose --profile apps up -d --build
```

Gateway는 `http://localhost:8080`, Mock은 `http://localhost:8081`입니다. Auth·Banking·Asset HTTP는 호스트에 직접 공개하지 않고 Compose 내부에서만 연결합니다. 도구는 `tools`, 모니터링은 `monitoring` 프로필을 선택해야 실행되며 자동 재시작은 꺼져 있습니다. gRPC 개발 인증서는 최초 실행 시 생성됩니다.

월별 집계 테스트가 필요하면 테스트 도구를 함께 실행한 뒤 `http://localhost:8090`에서 페르소나 데이터를 생성합니다.

```powershell
docker compose --profile apps --profile test-tools up -d --build
```

Auth JWT의 `sub`는 숫자형 사용자 ID를 담은 문자열이며, `typ=access`, `jti`, `iat`, `exp`, `iss=moaje-auth`를 검증합니다. 현재 HS256을 사용할 때 Gateway의 `AUTH_JWT_SECRET_KEY`에는 Auth의 `SECRET_KEY`와 같은 값을 안전하게 주입해야 합니다. 비밀키·실제 토큰은 커밋하지 않으며, 설정이 없다고 인증을 우회하지 않습니다.

Auth는 시작할 때 Alembic migration을 적용하고, Banking·Asset의 새 DB는 Flyway migration과 Hibernate validate로 시작합니다. 기존 데이터를 유지해야 하는 DB는 백업·별도 전환 검증이 필요합니다. 통합 Swagger는 구성되었고 Work 통합은 아직 미완료입니다. 로컬 테스트 데이터 전체 초기화는 가이드의 확인 절차를 따른다.

## Work 합류 준비

Work의 실행 가능한 커밋, Dockerfile 또는 시작 명령, Python 버전·의존성, 내부 포트·health 경로·환경변수, Redis 키 접두어·TTL, Kafka 토픽·Consumer Group·메시지 규격을 담당자와 확정해야 합니다. 현재 Gateway의 Work 목적지는 자리만 마련한 설정이며, 실제 서비스 등록을 의미하지 않습니다.

같은 PC의 로컬 Python은 Kafka `localhost:9092`, Redis `localhost:6379`로 접속합니다. 추후 같은 Compose 네트워크에서는 `kafka:29092`, `redis:6379`를 사용합니다. Mock 원장 Redis는 별도이며 공유 대상이 아닙니다. 서로 다른 도메인이 같은 이벤트를 모두 받아야 한다면 Consumer Group을 구분합니다.
