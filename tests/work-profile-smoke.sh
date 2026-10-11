#!/usr/bin/env bash
# 생성 직후 응답 직렬화와 Redis 재조회가 같은 규격인지 검사한다.
# 예약된 테스트 ID만 사용하고, 기존 데이터가 있으면 시작하지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose --profile apps exec -T work python - <<'PY'
import asyncio
from sqlalchemy import text
from app.db.session import AsyncSessionLocal, engine
from app.redis.client import get_redis, KEY_PREFIX

async def main():
    async with AsyncSessionLocal() as session:
        count = await session.scalar(text('SELECT COUNT(*) FROM ai_spending_profile WHERE user_id=:uid'), {'uid': 880000000000000001})
        assert count == 0, 'Reserved test ID already exists; no data will be removed'
    redis = await get_redis()
    assert not await redis.exists(f'{KEY_PREFIX}spending_profile:880000000000000001'), 'Reserved cache already exists'
    await redis.aclose()
    await engine.dispose()
asyncio.run(main())
PY

cleanup() {
  docker compose --profile apps exec -T work python - <<'PY'
import asyncio
from sqlalchemy import text
from app.db.session import AsyncSessionLocal, engine
from app.redis.client import get_redis, KEY_PREFIX

async def main():
    async with AsyncSessionLocal() as session:
        await session.execute(text('DELETE FROM ai_spending_profile WHERE user_id=:uid'), {'uid': 880000000000000001})
        await session.commit()
        assert await session.scalar(text('SELECT COUNT(*) FROM ai_spending_profile WHERE user_id=:uid'), {'uid': 880000000000000001}) == 0
    redis = await get_redis()
    await redis.delete(f'{KEY_PREFIX}spending_profile:880000000000000001')
    await redis.aclose()
    await engine.dispose()
    print('PASS: Test profile and cache removed')
asyncio.run(main())
PY
}
trap cleanup EXIT

docker compose --profile apps exec -T auth python - <<'PY'
import json
import urllib.request
from app.core.security import create_access_token
token, _ = create_access_token('880000000000000001')
responses = []
for _ in range(2):
    req = urllib.request.Request(
        'http://gateway:8080/api/v1/work/spending/880000000000000001/profile',
        headers={'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(req, timeout=15) as response:
        assert response.status == 200
        result = json.load(response)
        assert str(result['user_id']) == '880000000000000001'
        responses.append(result)
assert responses[0] == responses[1], 'DB creation response and cache response differ'
print('PASS: Profile creation and cached response both 200 with matching payload')
PY
