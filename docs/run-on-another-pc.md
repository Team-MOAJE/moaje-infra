# 다른 PC에서 MOAJE 실행하기

## 1. 준비

필수: **Git, Docker Desktop(Linux 컨테이너), GitHub 저장소 접근 권한**.
Java·Gradle·Python·MySQL·Kafka를 PC에 따로 설치할 필요는 없다. Docker가 이미지 안에서 빌드하고 실행한다.
최초 빌드는 인터넷 연결이 필요하며, 여러 JVM과 DB가 함께 실행되므로 Docker 메모리를 넉넉히 배정한다.

아래는 PowerShell 기준이다. 다른 PC의 기존 DB를 가져오는 절차가 아니라 **빈 DB로 새 개발 환경을 만드는 절차**다.

## 2. 일곱 저장소 받기

```powershell
New-Item -ItemType Directory -Force C:\moaje
cd C:\moaje
git clone --branch main https://github.com/Team-MOAJE/moaje-infra.git
git clone --branch main https://github.com/Team-MOAJE/moaje-banking.git
git clone --branch main https://github.com/Team-MOAJE/moaje-asset.git
git clone --branch main https://github.com/Team-MOAJE/moaje-mockup-banking.git backing-mockup
git clone --branch main https://github.com/Team-MOAJE/moaje-grpc-contracts.git
git clone --branch dev https://github.com/Team-MOAJE/moaje-auth.git
git clone --branch dev https://github.com/Team-MOAJE/moaje-work.git
```

**폴더 이름과 형제 관계를 유지한다.** Compose 빌드가 `../moaje-work`, `../backing-mockup` 등의 경로를 사용한다.
Auth·Work는 이번 검증 기준 `dev`, 나머지는 `main`이다. 브랜치 최신 코드는 바뀔 수 있으므로 정확한 재현에는 [검증 결과의 커밋](integration-test-results-20261011.md#검증-기준)을 사용한다.
기존 폴더가 있다면 다시 clone하지 않고 각 저장소의 변경사항을 확인한 후 해당 브랜치를 업데이트한다.

## 3. 로컬 비밀키 설정

```powershell
cd C:\moaje\moaje-infra
Copy-Item .env.example .env
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_hex(32))"
docker run --rm python:3.12-slim python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

`.env`에 첫 번째 출력은 `AUTH_JWT_SECRET_KEY`, 두 번째 출력은 `AUTH_AES_MASTER_KEY`로 입력한다.
`AUTH_JWT_ALGORITHM=HS256`, `AUTH_JWT_ISSUER=moaje-auth`를 유지한다. Compose가 동일한 JWT 설정을 Auth와 Gateway에 전달한다.

- `.env`와 `certs/`는 Git에 올리지 않는다. 기존 PC의 개인키를 복사하지 않는다.
- gRPC 인증서는 첫 실행 때 `grpc-cert-init`이 자동 생성한다. 이 컨테이너의 정상 종료는 오류가 아니다.
- Work 운영자 API까지 시험할 때만 `WORK_INTERNAL_TOKEN`을 별도로 생성한다. 비어 있으면 운영 API는 503으로 차단된다.
- 환경변수만 바꿔도 기존 DB 비밀번호나 저장된 암호문이 자동 변환되는 것은 아니다. 실행 후 키·DB 비밀번호를 임의 변경하지 않는다.

## 4. 빌드하고 실행

```powershell
docker compose --profile apps config --quiet
docker compose --profile apps up -d --build --wait --wait-timeout 300
docker compose --profile apps ps -a
```

컨테이너가 모두 실행돼도 Gateway API 준비에 잠시 더 걸릴 수 있다. 아래 주소가 열리는지 확인한다.

| 확인 대상 | 주소 / 명령 |
|---|---|
| 통합 Swagger | http://localhost:8080/docs/swagger-ui.html |
| Auth 명세 | http://localhost:8080/docs/auth/openapi.json |
| Banking 명세 | http://localhost:8080/docs/banking/v3/api-docs |
| Asset 명세 | http://localhost:8080/docs/asset/v3/api-docs |
| Work 명세 | http://localhost:8080/docs/work/openapi.json |
| 실패 원인 확인 | `docker compose --profile apps logs --tail 100 auth work banking asset gateway` |

MySQL 스키마는 Auth의 Alembic, Banking·Asset의 Flyway, Work의 초기 SQL로 준비된다.
처음에는 사용자와 계좌가 없다. [Swagger 테스트 가이드](integrated-api-test-guide.md)의 가입 → 로그인 → 계좌 개설 → 송금 순서로 진행한다.
현재 가입은 **휴대폰 번호·이름·6자리 PIN과 확인 PIN·필수 약관 동의 및 버전**을 받으며 SMS 인증은 사용하지 않는다.

## 5. 선택 도구와 종료

```powershell
# Kafka UI·RedisInsight가 필요할 때만 실행
docker compose --profile apps --profile tools up -d
# Prometheus·Grafana가 필요할 때만 실행
docker compose --profile apps --profile monitoring up -d
# 테스트 데이터 생성 콘솔: http://localhost:8090
docker compose --profile apps --profile test-tools up -d --build
```

일반 실행에는 모니터링 도구가 필요 없다. 컨테이너의 `restart: "no"` 설정으로 Docker 엔진 재시작 시 자동 기동하지 않는다.
페르소나 콘솔·seed 스크립트는 휴대폰 가입 규격을 사용한다. 생성 결과의 휴대폰 번호와 PIN으로 로그인할 수 있다.
Docker Desktop 프로그램 자체의 로그인 시 자동 실행은 각 PC의 Docker Desktop 설정에서 별도로 끈다.

```powershell
# 종료: DB·Redis·Kafka 데이터 보존
docker compose --profile apps --profile tools --profile monitoring --profile test-tools down
```

완전히 초기화할 때만 위 `down`에 `--volumes`를 추가한다. **회원·계좌·거래·Kafka 데이터가 모두 삭제된다.**
인증서 폴더는 Docker 볼륨이 아니라 PC 폴더라 이 명령으로 삭제되지 않는다.

## 6. 다른 PC에서 주의할 점

- 현재 포트는 `127.0.0.1`에만 열려 있다. 새 PC의 브라우저에서는 `localhost`로 접속하지만, 휴대폰이나 다른 PC에서는 접속할 수 없다. 외부 공개는 별도 보안 설정이 필요하다.
- 포트 충돌 시 `.env`의 `GATEWAY_PORT`, `AUTH_MYSQL_PORT`, `ASSET_MYSQL_PORT`, `BANKING_MYSQL_PORT`, `REDIS_PORT`, `KAFKA_PORT`, `MOCK_BANKING_PORT`를 조정한다.
- Linux에서 셸 파일 실행 오류가 나면 `grpc/init-certs.sh`가 CRLF가 아닌 LF인지 확인한다.
- `/api/v1/auth/session/unlock`은 Refresh Token과 PIN으로 인증하며 Gateway JWT 검사를 생략한다. 예전 `.env`에 `AUTH_PUBLIC_ENDPOINTS`를 직접 지정했다면 `POST /api/v1/auth/session/unlock`도 추가해야 한다. 그 뒤 Gateway를 재생성한다.
- 이 Compose는 개발용이다. 개발 DB 비밀번호, 테스트 데이터 API, 로컬 인증서 설정을 그대로 운영에 사용하지 않는다.

## 7. 격리 통합테스트 실행 기준

기존 개발 환경과 데이터를 섞지 않으려면 `tests/docker-compose.e2e.yaml`을 함께 사용한다.
**프로젝트 이름뿐 아니라 컨테이너 접두어와 인증서 폴더도 분리**해야 한다.

```powershell
$env:MOAJE_STACK_PREFIX='moaje-e2e-local'
$env:MOAJE_GRPC_CERTS_DIR='./.local/e2e-local-certs'
docker compose -p moaje-e2e-local -f docker-compose.yaml -f tests/docker-compose.e2e.yaml --profile apps up -d --build --wait --wait-timeout 300
docker cp tests moaje-e2e-local-work:/tests
docker cp ../moaje-grpc-contracts/proto moaje-e2e-local-work:/contracts
docker exec moaje-e2e-local-work sh -c 'mkdir -p /tmp/e2e-gen && python -m grpc_tools.protoc -I/contracts --python_out=/tmp/e2e-gen /contracts/common/*.proto /contracts/events/banking_events.proto'
docker exec moaje-e2e-local-work python /tests/rerun-e2e.py core
```

`core`는 빈 DB에서 한 번 실행한다. 같은 DB에서 다시 실행하면 중복 가입에 걸린다.
그 뒤 `timeout`, `multimonth`, `replay`, `dlt`, `audit`, `fixes`, `fresh-profile`을 **한 번에 하나씩** 실행한다.
회원 관리 시험은 `python /tests/current-auth-e2e.py`, 마지막 계좌 폐쇄·세션 시험은 `python /tests/rerun-e2e.py final`이다.
Kafka 중단·Banking 강제 종료 시험은 컨테이너 조작이 추가로 필요하며 단순 단계 실행만으로 재현되지 않는다.

결과 JSON은 Work 컨테이너의 `/tmp/moaje-e2e-results.json`에 있다. 토큰을 포함한 `moaje-e2e-state.json`은 공유하지 않는다.
종료 전 결과만 내보내고, 아래 명령으로 **해당 테스트 프로젝트만** 제거한다.

```powershell
docker cp moaje-e2e-local-work:/tmp/moaje-e2e-results.json ./e2e-results.json
docker compose -p moaje-e2e-local -f docker-compose.yaml -f tests/docker-compose.e2e.yaml --profile apps down --volumes
Remove-Item Env:MOAJE_STACK_PREFIX
Remove-Item Env:MOAJE_GRPC_CERTS_DIR
```

테스트 인증서 폴더는 `.local/e2e-local-certs`에 남는다. 이는 일반 실행의 `certs/`와 별개다.
