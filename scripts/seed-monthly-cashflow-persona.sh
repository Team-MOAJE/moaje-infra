#!/usr/bin/env sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "${0%/*}" && pwd)
INFRA_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

GATEWAY_URL=${GATEWAY_URL:-http://localhost:8080}
MOCK_BANKING_URL=${MOCK_BANKING_URL:-http://localhost:8081}
HMAC_SECRET=${MOAJE_BANKING_HMAC_SECRET:-Moaje-banking-secret}
PERSONA_SUFFIX=${PERSONA_SUFFIX:-"$(date +%s)-$$"}
PERSONA_EMAIL=${PERSONA_EMAIL:-"cashflow-${PERSONA_SUFFIX}@moaje.test"}
PERSONA_PIN=${PERSONA_PIN:-123456}
PERSONA_CI=${PERSONA_CI:-"TEST-CI-CASHFLOW-${PERSONA_SUFFIX}"}
PERSONA_PRODUCT=${PERSONA_PRODUCT:-"월간 소비 테스트 계좌 ${PERSONA_SUFFIX}"}
TARGET_MONTH=$(date +%Y-%m)

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "필수 명령을 찾을 수 없습니다: $1" >&2
        exit 1
    fi
}

require_command curl
require_command jq
require_command openssl
require_command docker

cd "$INFRA_DIR"

echo "[1/7] 통합 환경 확인"
for service in gateway auth banking asset mock-banking mock-redis kafka; do
    if ! docker compose --profile apps ps --status running --services | grep -Fx "$service" >/dev/null 2>&1; then
        echo "실행 중이 아닌 서비스가 있습니다: $service" >&2
        echo "먼저 docker compose --profile apps up -d --build 를 실행하세요." >&2
        exit 1
    fi
done

echo "[2/7] 테스트 사용자 등록 및 로그인"
REGISTER_BODY=$(jq -anc --arg email "$PERSONA_EMAIL" --arg pin "$PERSONA_PIN" '{email:$email,pin:$pin}')
REGISTER_RESPONSE=$(curl --fail-with-body -sS -X POST "$GATEWAY_URL/api/v1/auth/register" \
    -H 'Content-Type: application/json' \
    --data "$REGISTER_BODY")
USER_ID=$(printf '%s' "$REGISTER_RESPONSE" | jq -er '.data.user_id | tostring')

LOGIN_BODY=$(jq -anc --arg email "$PERSONA_EMAIL" --arg pin "$PERSONA_PIN" \
    '{email:$email,pin:$pin,device_info:"cashflow-persona-seed"}')
LOGIN_RESPONSE=$(curl --fail-with-body -sS -X POST "$GATEWAY_URL/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    --data "$LOGIN_BODY")
JWT=$(printf '%s' "$LOGIN_RESPONSE" | jq -er '.data.access_token')

echo "[3/7] Banking 계좌 개설"
ACCOUNT_BODY=$(jq -anc \
    --arg ci "$PERSONA_CI" \
    --arg productName "$PERSONA_PRODUCT" \
    '{ci:$ci,userName:"월간 집계 테스트",phoneNumber:"01000000003",bankCode:"001",productName:$productName,initialBalance:500000}')
ACCOUNT_RESPONSE=$(curl --fail-with-body -sS -X POST "$GATEWAY_URL/api/v1/banking/accounts" \
    -H "Authorization: Bearer $JWT" \
    -H 'Content-Type: application/json' \
    --data "$ACCOUNT_BODY")
ACCOUNT_ID=$(printf '%s' "$ACCOUNT_RESPONSE" | jq -er '.accountId | tostring')

find_mock_account_number() {
    docker compose exec -T mock-redis redis-cli --raw --scan --pattern '{banking}:account:*' | while IFS= read -r key; do
        owner_ci=$(docker compose exec -T mock-redis redis-cli --raw HGET "$key" ownerCi | tr -d '\r')
        product_name=$(docker compose exec -T mock-redis redis-cli --raw HGET "$key" productName | tr -d '\r')
        if [ "$owner_ci" = "$PERSONA_CI" ] && [ "$product_name" = "$PERSONA_PRODUCT" ]; then
            printf '%s\n' "${key##*:}"
            break
        fi
    done
}

ACCOUNT_NUMBER=$(find_mock_account_number)
if [ -z "$ACCOUNT_NUMBER" ]; then
    echo "Mock Banking에서 방금 만든 계좌를 찾지 못했습니다." >&2
    exit 1
fi

echo "[4/7] Mock Banking 접근 토큰 발급"
MOCK_TOKEN_BODY=$(jq -anc \
    --arg ci "$PERSONA_CI" \
    '{ci:$ci,userName:"월간 집계 테스트",phoneNumber:"01000000003"}')
MOCK_TOKEN_RESPONSE=$(curl --fail-with-body -sS -X POST "$MOCK_BANKING_URL/oauth/2.0/token" \
    -H 'Content-Type: application/json' \
    --data "$MOCK_TOKEN_BODY")
MOCK_TOKEN=$(printf '%s' "$MOCK_TOKEN_RESPONSE" | jq -er '.accessToken')

hmac_sha256() {
    printf '%s' "$1" | openssl dgst -sha256 -hmac "$HMAC_SECRET" | sed 's/^.*= //'
}

seed_withdrawal() {
    amount=$1
    merchant_name=$2
    memo=$3
    body=$(jq -anc \
        --argjson amount "$amount" \
        --arg merchantName "$merchant_name" \
        --arg memo "$memo" \
        '{amount:$amount,merchantName:$merchantName,memo:$memo}')
    signature=$(hmac_sha256 "$body")

    curl --fail-with-body -sS -X POST "$MOCK_BANKING_URL/api/accounts/$ACCOUNT_NUMBER/withdrawals" \
        -H "Authorization: Bearer $MOCK_TOKEN" \
        -H "X-Signature: $signature" \
        -H 'Content-Type: application/json' \
        --data "$body" >/dev/null
}

echo "[5/7] 현재 월의 카테고리별 가맹점 거래 생성"
seed_withdrawal 18000 '배달의민족' 'FOOD 분류 확인'
seed_withdrawal 5500 '스타벅스 강남점' 'CAFE 분류 확인'
seed_withdrawal 12000 '카카오T 택시' 'TRANSPORT 분류 확인'
seed_withdrawal 15000 'CGV 대학로' 'CULTURE 분류 확인'
seed_withdrawal 23000 '올리브영 신촌점' 'SHOPPING 분류 확인'
seed_withdrawal 28000 '교보문고 광화문점' 'STUDY 분류 확인'
seed_withdrawal 45000 'KT 통신요금' 'HOUSING 분류 확인'
seed_withdrawal 7000 'MOAJE TEST STORE' 'UNCATEGORIZED 분류 확인'

echo "[6/7] Asset 계좌 생성 이벤트 도착 대기 및 Snapshot refresh"
attempt=1
while [ "$attempt" -le 20 ]; do
    status=$(curl -sS -o /dev/null -w '%{http_code}' \
        -H "Authorization: Bearer $JWT" \
        "$GATEWAY_URL/api/v1/assets/accounts/$ACCOUNT_ID/detail")
    if [ "$status" = "200" ]; then
        break
    fi
    sleep 1
    attempt=$((attempt + 1))
done

if [ "$attempt" -gt 20 ]; then
    echo "Asset 계좌 Projection이 제한 시간 안에 생성되지 않았습니다." >&2
    exit 1
fi

curl --fail-with-body -sS -X POST "$GATEWAY_URL/api/v1/assets/accounts/$ACCOUNT_ID/refresh" \
    -H "Authorization: Bearer $JWT" >/dev/null

echo "[7/7] 월별·카테고리별 집계 조회"
MONTHLY_RESULT=$(curl --fail-with-body -sS \
    -H "Authorization: Bearer $JWT" \
    "$GATEWAY_URL/api/v1/assets/cashflow/monthly?yearMonth=$TARGET_MONTH")
CATEGORY_RESULT=$(curl --fail-with-body -sS \
    -H "Authorization: Bearer $JWT" \
    "$GATEWAY_URL/api/v1/assets/cashflow/category?yearMonth=$TARGET_MONTH")

echo
echo "테스트 페르소나 생성 완료"
echo "userId: $USER_ID"
echo "email: $PERSONA_EMAIL"
echo "PIN: $PERSONA_PIN"
echo "accountId: $ACCOUNT_ID"
echo "targetMonth: $TARGET_MONTH"
echo
echo "월 집계"
printf '%s\n' "$MONTHLY_RESULT" | jq
echo
echo "카테고리 집계"
printf '%s\n' "$CATEGORY_RESULT" | jq
echo
echo "JWT는 출력하지 않았습니다. Swagger에서 확인하려면 위 이메일과 PIN으로 다시 로그인하세요."
