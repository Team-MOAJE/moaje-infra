# MOAJE 통합 API 테스트 가이드

이 문서는 로컬 Docker Compose 환경에서 Auth, Banking, Mock Banking, Asset, Work가 연결된 흐름을 직접 확인하는 절차를 설명한다.
새 PC의 설치·키 설정·기동·초기화는 [다른 PC 실행 안내](run-on-another-pc.md)를 먼저 확인한다.

## 계좌 은행 정보 변경 (2026-10-14)

- 계좌 생성 `POST /api/v1/banking/accounts`의 본문에 `bankCode`와 `bankName`을 필수로 보낸다.
- 예: `"bankCode": "088", "bankName": "테스트 은행"`. 코드는 앞자리 0이 유지되는 문자열이다.
- `bankCode`는 최대 20자, `bankName`은 최대 100자이며 공백만 보낸 요청은 400으로 거절한다. 양끝 공백은 제거한다.
- `GET /api/v1/assets/accounts`는 JWT 소유자의 계좌 목록을 반환한다. 미연동 사용자는 빈 배열을 받는다.
- 목록 항목은 `accountId`, `bankCode`, `bankName`, `maskedAccountNumber`, `balance`, `status`이다. 닫힌 계좌도 상태와 함께 반환한다.
- 상세 조회와 Refresh 응답에도 같은 은행 정보를 포함한다. 계좌 생성 직후에는 Kafka 소비까지 잠시 기다려야 목록에 나타날 수 있다.
- Banking V7, Asset V6 마이그레이션이 기존 볼륨에 컬럼을 추가한다. 볼륨 삭제는 필요 없다.
- 기존 계좌의 알 수 없는 은행명은 `null`이다. 기존 Asset 은행 코드는 Refresh 또는 정기 스냅샷 조회로 보충된다.
- Protobuf는 기존 번호를 유지하고 `AccountCreatedEvent.bank_name=10`, 스냅샷 응답 `bank_code=7`, `bank_name=8`만 추가한다.
- Auth·Work 소스는 변경하지 않는다. 생성 요청의 은행 코드와 은행명이 실제로 일치하는지 검증하는 은행 목록 기능은 이번 범위가 아니다.

목록 응답 예:

```json
[{"accountId": "123456789", "bankCode": "088", "bankName": "테스트 은행", "maskedAccountNumber": "**********1234", "balance": 100000, "status": "ACTIVE"}]
```

검증 기록 (2026-10-14): Banking 93건, Asset 43건, Mock Banking 일반 테스트 24건, Infra 도구 테스트 1건 통과.
H2 마이그레이션 검증을 포함한다. 이후 별도 Compose 프로젝트 `moaje-bankinfo-20261014`에서 최신 Banking·Asset·Mock 이미지를 빌드하여 Gateway 경유 연동 25개 항목도 모두 통과했다.
은행 코드 088·004의 본인 계좌 두 개와 090의 타인 계좌를 만들고, 이벤트 소비·실제 Redis 저장·스냅샷 gRPC·목록·상세·거래내역·소유권 차단을 검증했다.
JWT 없는 요청은 401, 타인 계좌의 상세·거래목록·Refresh는 403, 타인 거래 단건은 404였다. 위조 사용자 헤더도 다른 사용자 계좌를 노출하지 않았다.
결과는 [은행 정보 연동 검증 결과](bank-information-test-20261014.json)에 기록한다. 테스트는 Work를 기동하지 않은 관련 서비스 검증이며 전체 앱의 종합 회귀 테스트는 아니다.
이전 API PDF는 이번 수정에 포함하지 않았다.

### 계좌 선택 후 무한 스크롤 검증 (2026-10-14)

- 별도 Compose 환경에서 Mock API로 거래를 생성하고 Refresh로 Asset에 반영했다. 애플리케이션 코드는 추가 수정하지 않았다.
- 0건 → `[0]`, 50건 → `[50]`, 51건 → `[50, 1]`, 100건 → `[50, 50]`, 123건 → `[50, 50, 23]`으로 조회됐다.
- 상세의 `transactionHistory`와 커서 없는 `/transactions`의 첫 페이지·커서·`hasNext`가 일치했다.
- `nextCursor`는 반환한 마지막 `transactionId`와 같았다. 마지막 페이지는 `hasNext=false`, `nextCursor=null`이다.
- 123개 ID를 MySQL 공개 거래 원본과 전부 비교해 누락·중복이 없음을 확인했다. 다른 본인 계좌의 7건도 섞이지 않았다.
- 같은 커서 재요청, 스크롤 중 신규 거래 추가, 타인 JWT로 다음 페이지 요청도 검증했다. 타인 요청은 403이었다.
- 결과: [검증 기록](account-pagination-test-20261014.json) 59개 항목 통과, JavaScript 숫자 정밀도 경고 1개. 테스트 데이터와 볼륨은 삭제했다.
- 주의: 현재 큰 정수 ID가 JSON 숫자로 반환된다. JavaScript Number와 동일한 IEEE 754 변환으로 `accountId`가 반올림됐고, 그 ID의 상세 조회는 404였다. 커서도 값이 변했지만 이번 표본의 두 번째 페이지 결과는 같았다.
- 위 경고는 변경 전 검증 결과이다. 이후 Banking의 `accountId`·`transferId`, Asset의 `accountId`·`transactionId`·`nextCursor` 응답을 문자열로 변경했다. 금액은 숫자, 마지막 커서는 null을 유지하며 DB·gRPC·Kafka 내부 타입은 바꾸지 않았다.
- 앱은 응답 문자열을 그대로 저장하고 URL·쿼리·송금 본문의 `withdrawalAccountId`에 그대로 넣는다. `Number()`로 변환하지 않는다. 서버는 문자열 ID를 내부 Long으로 해석한다.
- 새 검증 결과는 [문자열 ID 무한 스크롤 검증](account-pagination-string-ids-test-20261014.json)에 남긴다.
- 변경 후 검증은 67개 항목 모두 통과했다. 실제 JavaScript `JSON.parse`에서 문자열 ID가 유지되고, 그 계좌 ID·커서로 상세 및 다음 페이지를 다시 조회했다. 배포된 Swagger 응답 스키마 7개 ID 필드도 string으로 확인했다.
- 최종 일반 테스트는 Banking 95건, Asset 44건, Mock Banking 24건 통과했다. Infra 도구 테스트 1건도 통과했다. 이전 경고 결과는 변경 이력으로 보존한다.

재검증은 `tests/docker-compose.bank-information.yaml`을 기본 Compose에 덧붙여 별도 프로젝트로 실행한다. 프로젝트 이름과 `MOAJE_STACK_PREFIX`는 모두 `moaje-bankinfo-20261014`로 지정하며, `MOAJE_GRPC_CERTS_DIR`도 별도 테스트 디렉터리로 지정한다. Gateway·Mock은 각각 19080·19081 포트를 사용한다.
`tests/account-pagination-e2e.py`에는 Python과 JavaScript 검증용 Node.js가 필요하다. `MOAJE_TEST_NODE`에 Node 실행 경로, `MOCK_HMAC`에 로컬 Mock HMAC 키를 지정한다. 인증 키는 문서나 결과 파일에 기록하지 않는다.
검증 후에는 반드시 같은 `-p`와 Compose 파일 조합으로 `down --volumes`를 실행해 해당 테스트 볼륨만 정리한다.

## 1. 사전 준비

- Docker Desktop을 실행한다.
- `C:\moaje` 아래에 `moaje-auth`, `moaje-work`, `moaje-banking`, `moaje-asset`, `backing-mockup`, `moaje-grpc-contracts`, `moaje-infra`가 있어야 한다.
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

상단 `Select a definition`에서 Auth, Banking, Asset, Work 문서를 전환한다. API 요청은 모두 Gateway `localhost:8080`을 통과한다.

월별 테스트 데이터까지 만들려면 `test-tools` 프로필을 함께 실행한다.

> 2026-10-11 후속 검증: Fixture Console·seed 스크립트를 현재 휴대폰 가입 규격으로 수정했다.
> 화면의 생성 API는 3개월 24건, `.sh`는 현재 월 8건 생성과 집계까지 확인했다. [검증 결과](gateway-persona-retest-20261011.md).

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
  "phone_number": "01090000001",
  "name": "송금 테스트",
  "pin": "123456",
  "pin_confirm": "123456",
  "terms_agreed": true,
  "privacy_agreed": true,
  "terms_version": "test-v1",
  "privacy_version": "test-v1"
}
```

```json
{
  "phone_number": "01090000002",
  "name": "수취 테스트",
  "pin": "123456",
  "pin_confirm": "123456",
  "terms_agreed": true,
  "privacy_agreed": true,
  "terms_version": "test-v1",
  "privacy_version": "test-v1"
}
```

위 값은 SMS를 보내지 않는 개발용 예시다. 이메일은 선택이며, 휴대폰 번호와 6자리 PIN으로 로그인한다.
`POST /api/v1/auth/login` 응답의 `data.access_token`을 사용자별로 보관한다.

```json
{
  "phone_number": "01090000001",
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
  "bankName": "테스트 은행",
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
  "bankName": "테스트 은행",
  "productName": "수취 계좌",
  "initialBalance": 0
}
```

응답의 `accountId`는 Banking이 관리하는 계좌 ID다. 현재 Auth 개인정보 RPC가 완성되지 않아 계좌 개설 요청이 CI와 전화번호를 직접 받으므로 가짜 값만 사용한다.

## 5. 수취 계좌번호 확인

개설 응답의 `accountNumber`가 실제 수취 계좌번호이다. Redis에 직접 접속할 필요가 없다.

```json
{"accountId":"123456789012345679","accountNumber":"12345678901234","maskedAccountNumber":"**********1234"}
```

예시는 가상 값이다. `accountId`는 앱의 계좌 선택·상세·거래내역·Refresh 및 송금의 출금 계좌(`withdrawalAccountId`)에 사용한다.
`accountNumber`는 표시·복사 및 수취 계좌(`depositAccountNumber`) 지정에 사용한다. 요청에서 두 값을 서로 바꾸지 않는다.
목록은 마스킹 값만 반환한다. 상세·Refresh는 본인 소유권 확인 후 14자리 `accountNumber`를 반환하며, `displayAccountNumber`·`maskedAccountNumber` 필드는 제외한다. 복사 버튼은 클라이언트에서 구현한다.
상세·Refresh의 소유권 불일치는 400, JWT 누락·변조·만료는 Gateway에서 401로 거절한다. 원번호 조회 장애는 잘못된 사용자 요청이 아니므로 502로 처리한다.
원번호는 Asset 장부·Redis 캐시·Kafka·정기 스냅샷에 저장하거나 포함하지 않는다. DB 트랜잭션 밖에서 Asset 전용 mTLS RPC로 조회해 응답 직전에 붙이고 `Cache-Control: no-store`를 적용한다.
Banking은 원번호 RPC의 principalId와 실제 소유자를 다시 비교한다. 같은 CA의 Work 인증서는 해당 RPC를 사용할 수 없으며, Infra의 CN=asset 인증서만 허용한다. 로컬 TLS 비활성 연결도 원번호 RPC에는 허용하지 않는다.
Kafka 계좌 생성 이벤트와 gRPC 스냅샷도 마스킹 값만 포함한다. 기존 Asset 계좌는 V7 마이그레이션 후 Refresh 또는 정기 스냅샷으로 보충되고, 확인 전에는 null이다.

검증 기록: [개설 응답 기반 송금 검증](account-number-transfer-test-20261014.json) 33개 항목 통과. 개설 응답만으로 실제 송금하고 상세·새로고침의 전체 번호, 목록의 마스킹 번호를 확인했다. 타인 상세 400, JWT 누락·위조 401, 타인 출금 403도 확인했다. Redis 상세 캐시에는 전체 번호가 없으며, 상세 응답에는 `Cache-Control: no-store`가 있다. Outbox와 실제 Kafka 원본 바이트에도 전체 번호가 없다.
이 변경 이후 무한 스크롤·문자열 ID 왕복 검증 67개 항목을 재실행하여 통과했다. 일반 테스트는 Banking 102건·Asset 46건·Mock 24건 통과했다. 실제 Work 인증서로 새 번호 조회 RPC를 호출하면 `PERMISSION_DENIED`로 차단되는 것도 별도로 확인했다. 기존 볼륨은 유지하고 검증용 볼륨만 정리했다.
테스트 도구의 첫 실행은 HTTP 헤더 이름의 대소문자 비교 때문에 실패했다. 헤더 이름을 대소문자 구분 없이 비교하도록 수정하고 같은 검증을 다시 통과했다. 페이지 테스트의 첫 재실행은 `MOCK_HMAC` 환경변수 누락으로 중단됐으며, 값을 제공한 재실행은 통과했다. 두 건 모두 애플리케이션 실패가 아니다.

## 6. 송금과 멱등성 확인

송금 사용자 JWT로 다시 인증하고 `POST /api/v1/banking/transfers`를 실행한다.

헤더:

```text
Idempotency-Key: swagger-transfer-001
```

본문:

```json
{
  "withdrawalAccountId": "123456789012345679",
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

결과에 표시되는 **휴대폰 번호와 PIN**으로 Swagger의 Auth 로그인 API를 호출한다.
번호는 자동 생성한 테스트 입력이며 SMS는 발송하지 않는다. 이메일은 선택 정보로만 저장한다.
도구가 보내는 `local-test-v1` 약관 버전과 동의 값은 합성 테스트 데이터이며 실제 사용자의 동의 기록이 아니다.

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
`PERSONA_PHONE=01090000009`처럼 번호를 지정할 수도 있다. 같은 번호를 재사용하면 Auth의 중복 가입 검증으로 거절되므로 새 번호를 사용한다.

```sh
GATEWAY_URL=http://localhost:8080 \
MOCK_BANKING_URL=http://localhost:8081 \
MOAJE_BANKING_HMAC_SECRET='local-secret' \
sh scripts/seed-monthly-cashflow-persona.sh
```

이 스크립트는 공개된 Mock Banking 출금 API만 사용하므로 실행한 달의 데이터만 만든다. 과거 여러 달의 데이터가 필요하면 Fixture Console을 사용한다.

## 12. 현재 한계

- Auth에서 계좌 개설용 CI·전화번호를 제공하는 RPC는 아직 확정되지 않았다.
- Work는 `apps` 프로필로 함께 실행되며 통합 Swagger에서 명세를 볼 수 있다. 2026-10-10에 잔액 RPC·Gateway 시뮬레이터·거래 및 집계 Protobuf 소비를 검증했다. Git Bash에서 `bash tests/work-asset-integration.sh`로 재현한다. 전용 DB 행·캐시는 정리하지만 Kafka 테스트 메시지는 보존 기간까지 남는다. 전체 금융 흐름·회원가입 검증과는 구분하며 [검사 결과와 재현 명령](work-integration-check.md)을 참고한다.
- 통합 Swagger는 여러 API를 한 화면에서 호출하게 해주지만 전체 시나리오를 한 번에 자동 실행하지는 않는다.
- Fixture Console은 로컬 수동 검증 도구이며 운영자용 백오피스가 아니다.
- 반복 가능한 회귀 검증은 Swagger 수동 테스트와 별도의 자동 통합 테스트가 함께 필요하다.
