# MOAJE 통합 API 테스트 가이드

이 문서는 로컬 Docker Compose 환경에서 Auth, Banking, Mock Banking, Asset이 연결된 흐름을 직접 확인하는 절차를 설명한다.

## 1. 사전 준비

- Docker Desktop을 실행한다.
- `C:\moaje` 아래에 `moaje-auth`, `moaje-banking`, `moaje-asset`, `backing-mockup`, `moaje-grpc-contracts`, `moaje-infra`가 있어야 한다.
- 실제 개인정보, 계좌번호, 운영 비밀키를 테스트 데이터로 사용하지 않는다.
- `.env.example`을 참고하여 `moaje-infra/.env`의 JWT·암호화 키를 로컬 값으로 설정한다.

## 2. 통합 환경 실행

```powershell
cd C:\moaje\moaje-infra
docker compose --profile apps up -d --build
docker compose --profile apps ps
```

모든 애플리케이션과 MySQL, Redis, Kafka가 `Up` 또는 `healthy`인지 확인한다.

통합 Swagger 주소:

```text
http://localhost:8080/docs/swagger-ui.html
```

상단 `Select a definition`에서 Auth, Banking, Asset 문서를 전환한다. API 요청은 모두 Gateway `localhost:8080`을 통과한다.

월별 테스트 데이터까지 만들려면 `test-tools` 프로필을 함께 실행한다.

```powershell
docker compose --profile apps --profile test-tools up -d --build
```

테스트 페르소나 콘솔:

```text
http://localhost:8090
```

## 3. 테스트 사용자 준비

`Auth API`에서 송금 사용자와 수취 사용자를 각각 등록하고 로그인한다.

```json
{
  "email": "sender@moaje.test",
  "pin": "123456"
}
```

```json
{
  "email": "receiver@moaje.test",
  "pin": "123456"
}
```

`POST /api/v1/auth/login` 응답의 `data.access_token`을 사용자별로 보관한다.

```json
{
  "email": "sender@moaje.test",
  "pin": "123456",
  "device_info": "swagger-test"
}
```

## 4. 계좌 개설

`Banking API`를 선택하고 `Authorize`에 송금 사용자 JWT를 입력한다. Swagger가 `Bearer`를 붙이므로 토큰 문자열만 입력한다.

`POST /api/v1/banking/accounts`:

```json
{
  "ci": "TEST-CI-SENDER",
  "userName": "송금 테스트",
  "phoneNumber": "01000000001",
  "bankCode": "001",
  "productName": "송금 계좌",
  "initialBalance": 100000
}
```

수취 사용자 JWT로 교체한 뒤 수취 계좌도 만든다.

```json
{
  "ci": "TEST-CI-RECEIVER",
  "userName": "수취 테스트",
  "phoneNumber": "01000000002",
  "bankCode": "001",
  "productName": "수취 계좌",
  "initialBalance": 0
}
```

응답의 `accountId`는 Banking이 관리하는 계좌 ID다. 현재 Auth 개인정보 RPC가 완성되지 않아 계좌 개설 요청이 CI와 전화번호를 직접 받으므로 가짜 값만 사용한다.

## 5. Mock 수취 계좌번호 확인

실제 계좌번호는 Banking 응답에 노출하지 않는다. 로컬 테스트에서만 Mock Redis의 계좌를 확인한다.

```powershell
docker compose exec -T mock-redis redis-cli --scan --pattern "{banking}:account:*"
docker compose exec -T mock-redis redis-cli HGETALL "{banking}:account:조회된계좌번호"
```

`productName`이 `수취 계좌`인 레코드의 계좌번호를 송금 요청에 사용한다.

## 6. 송금과 멱등성 확인

송금 사용자 JWT로 다시 인증하고 `POST /api/v1/banking/transfers`를 실행한다.

헤더:

```text
Idempotency-Key: swagger-transfer-001
```

본문:

```json
{
  "withdrawalAccountId": 123456789,
  "depositBankCode": "001",
  "depositAccountNumber": "수취 계좌번호",
  "amount": 10000,
  "currency": "KRW"
}
```

`withdrawalAccountId`에는 송금 계좌 개설 응답의 `accountId`를 넣는다.

- 같은 키와 같은 본문을 다시 보내면 같은 `transferId`가 반환되어야 한다.
- 같은 키로 금액이나 수취 계좌를 바꾸면 `409 Conflict`가 반환되어야 한다.
- 정상 완료 후 Banking Outbox를 거쳐 Kafka에 성공 이벤트가 발행된다.

## 7. Asset 반영 확인

Kafka 소비 시간을 고려해 잠시 기다린 후 `Asset API`를 선택한다. 확인할 사용자의 JWT로 다시 인증한다.

```text
GET  /api/v1/assets/accounts/{accountId}/detail
GET  /api/v1/assets/accounts/{accountId}/transactions
POST /api/v1/assets/accounts/{accountId}/refresh
GET  /api/v1/assets/cashflow/monthly?yearMonth=2026-09
GET  /api/v1/assets/cashflow/category?yearMonth=2026-09
```

거래내역 최초 조회에서는 `lastTransactionId`를 비운다. 다음 페이지는 이전 응답의 `nextCursor`를 전달한다.

`refresh`는 Banking을 통해 Mock Banking Snapshot을 조회하고 Asset Projection을 갱신한다. Asset DB를 직접 수정하는 기능이 아니다.

## 8. Kafka 확인

```powershell
docker compose exec -T kafka kafka-topics --bootstrap-server localhost:29092 --list
docker compose exec -T kafka kafka-get-offsets --bootstrap-server localhost:29092 --topic moaje.banking.transfer-completed
docker compose exec -T kafka kafka-get-offsets --bootstrap-server localhost:29092 --topic moaje.asset.monthly-cashflow-aggregated
```

토픽별 발행자와 소비자는 [Kafka Topic 정리](./kafka-topics.md)를 참고한다.

## 9. 로그와 데이터 확인

```powershell
docker compose --profile apps logs --tail 100 gateway banking asset mock-banking
docker compose exec -T asset-mysql mysql -umoaje_asset -pmoaje_asset moaje_asset
docker compose exec -T banking-mysql mysql -umoaje_banking -pmoaje_banking moaje_banking
```

비밀번호가 명령 기록에 남는 방식은 로컬 테스트에서만 사용한다.

## 10. 환경 종료와 초기화

컨테이너만 종료하면 데이터는 유지된다.

```powershell
docker compose --profile apps down
```

테스트 데이터만 골라 지우는 과정은 Auth, Banking, Mock Banking, Asset, Kafka에 걸친 연관 데이터를 빠뜨리기 쉽다. 따라서 로컬 통합 환경은 모든 저장소를 한 번에 초기화한다.

```sh
cd /c/moaje/moaje-infra
sh scripts/reset-local-test-data.sh --yes
```

초기화 직후 빈 환경을 다시 실행하려면 다음 명령을 사용한다.

```sh
sh scripts/reset-local-test-data.sh --yes --restart
```

이 스크립트는 MySQL, Redis, Mock Redis, Kafka 볼륨을 모두 삭제한다. `--yes`가 없으면 실행을 거부하므로 일반 종료와 데이터 초기화를 혼동하기 어렵다. 컨테이너 종료 때 자동 삭제하지 않는 이유는 개발 중 보존해야 할 데이터까지 실수로 지울 수 있기 때문이다.

## 11. 월별 집계용 테스트 페르소나

송금 테스트만으로는 거래 카테고리가 대부분 `TRANSFER`가 되므로 월별 카테고리 집계를 충분히 확인하기 어렵다. 카페, 식비, 교통, 쇼핑 거래를 가진 테스트 페르소나가 필요하다.

Fixture Console은 `local` 환경에서만 열린 Mock Banking의 테스트 전용 API를 사용한다. Mock Banking 원장에 먼저 거래를 만들기 때문에 실제 Snapshot 수집과 Asset 분류 로직을 함께 시험한다.

```text
테스트 페르소나 생성
→ Mock Banking에 계좌와 가맹점 거래 생성
→ Asset refresh 실행
→ Banking Snapshot을 통해 거래 수집
→ Asset 분류기와 월 집계 실행
```

Asset DB에 거래를 직접 INSERT하면 Snapshot 수집, 거래 분류, 중복 방지 로직을 건너뛰므로 사용하지 않는다. Fixture API는 `local/test` 프로필, 활성화 설정, 전용 토큰이 모두 있어야 열리며 Gateway의 운영 API로 라우팅하지 않는다.

### 화면에서 생성

1. `http://localhost:8090`에 접속한다.
2. 소비 성향과 생성할 개월 수를 선택한다.
3. `테스트 데이터 생성`을 누른다.
4. 화면에서 사용자·계좌 ID, 월별 총지출, 카테고리별 금액을 확인한다.

지원 페르소나:

| 페르소나 | 특징 |
|---|---|
| 균형형 대학생 | 모든 카테고리의 기본 금액 사용 |
| 카페·외식형 | 식비와 카페 금액을 크게 생성 |
| 통학형 | 교통비를 크게 생성 |
| 자기계발형 | 교육비와 카페 금액을 크게 생성 |

한 달마다 식비, 카페, 교통, 문화, 쇼핑, 교육, 주거, 미분류 거래 8건을 만든다. 같은 실행 ID가 다시 전달되면 Mock Banking은 기존 거래를 건너뛰어 중복 생성하지 않는다.

### 명령줄에서 현재 월 생성

현재 월의 카테고리 집계를 빠르게 확인하려면 다음 스크립트를 실행한다.

```sh
cd /c/moaje/moaje-infra
sh scripts/seed-monthly-cashflow-persona.sh
```

스크립트는 가짜 사용자를 등록하고 Mock Banking에 `FOOD`, `CAFE`, `TRANSPORT`, `CULTURE`, `SHOPPING`, `STUDY`, `HOUSING`, `UNCATEGORIZED`로 분류될 거래를 만든다. 이후 Asset refresh와 월 집계 조회까지 실행한다.

정상 실행 시 총지출은 `153,500원`이며 다음 금액이 조회되어야 한다.

| 카테고리 | 금액 |
|---|---:|
| FOOD | 18,000원 |
| CAFE | 5,500원 |
| TRANSPORT | 12,000원 |
| CULTURE | 15,000원 |
| SHOPPING | 23,000원 |
| STUDY | 28,000원 |
| HOUSING | 45,000원 |
| UNCATEGORIZED | 7,000원 |

필수 명령은 `docker`, `curl`, `jq`, `openssl`이다. 기본 URL이나 HMAC 비밀값이 다르면 환경변수로 전달한다.

```sh
GATEWAY_URL=http://localhost:8080 \
MOCK_BANKING_URL=http://localhost:8081 \
MOAJE_BANKING_HMAC_SECRET='local-secret' \
sh scripts/seed-monthly-cashflow-persona.sh
```

이 스크립트는 공개된 Mock Banking 출금 API만 사용하므로 실행한 달의 데이터만 만든다. 과거 여러 달의 데이터가 필요하면 Fixture Console을 사용한다.

## 12. 현재 한계

- Auth에서 계좌 개설용 CI·전화번호를 제공하는 RPC는 아직 확정되지 않았다.
- Work는 현재 Compose와 통합되지 않아 Asset 집계 이벤트를 소비하지 않는다.
- 통합 Swagger는 여러 API를 한 화면에서 호출하게 해주지만 전체 시나리오를 한 번에 자동 실행하지는 않는다.
- Fixture Console은 로컬 수동 검증 도구이며 운영자용 백오피스가 아니다.
- 반복 가능한 회귀 검증은 Swagger 수동 테스트와 별도의 자동 통합 테스트가 함께 필요하다.
