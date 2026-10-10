#!/usr/bin/env bash
# Git Bash에서 실행한다. 비밀값·테스트 JWT는 파일이나 콘솔에 출력하지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."

asset_test_user=$(docker compose exec -T asset printenv SPRING_DATASOURCE_USERNAME | tr -d '\r')
asset_test_password=$(docker compose exec -T asset printenv SPRING_DATASOURCE_PASSWORD | tr -d '\r')
asset_test_tokens=$(docker compose exec -T auth python - <<'PY'
import json
from app.core.security import create_access_token
print(json.dumps({str(880000000000000011 + i): create_access_token(str(880000000000000011 + i))[0]
                  for i in range(4)}))
PY
)

# Git Bash가 /tmp 경로를 Windows 경로로 바꾸지 않도록 이 두 명령에만 적용한다.
MSYS_NO_PATHCONV=1 docker compose cp tests/work-asset-integration.py work:/tmp/work-asset-integration.py
MSYS_NO_PATHCONV=1 docker compose exec -T \
  -e PYTHONPATH=/app \
  -e "ASSET_TEST_DB_USER=$asset_test_user" \
  -e "ASSET_TEST_DB_PASSWORD=$asset_test_password" \
  -e "ASSET_TEST_TOKENS=$asset_test_tokens" \
  work python /tmp/work-asset-integration.py
