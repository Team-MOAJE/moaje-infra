"""로컬 Compose에서 잔액 RPC·Gateway·Kafka 소비를 검사하고 테스트 DB/캐시를 정리한다.

예약 사용자에게 기존 데이터가 있으면 실행하지 않는다. Kafka에 발행한 테스트
레코드는 보존 기간까지 남으므로 운영 환경에서는 실행하지 않는다.
"""
import asyncio
import json
import os
import time
import urllib.request
from decimal import Decimal

import aiomysql
import grpc
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.db.session import Base, AsyncSessionLocal, engine
from app.grpc.asset_client import AssetClient, BalanceStatus, load_channel_credentials
from app.grpc import asset_service_pb2 as rpc, asset_service_pb2_grpc
from app.grpc.events import asset_events_pb2 as events
from app.grpc.common.resources_pb2 import Money
from app.models import spending, fds, onboarding  # noqa: F401
from app.redis.client import get_redis, stop_redis

USERS = [880000000000000011 + i for i in range(4)]
EMPTY, CLOSED, ZERO, SUM = USERS
ACCOUNT_IDS = [880000000000000021 + i for i in range(5)]
YEAR_MONTH = '2026-09'
work_tables = [table for table in Base.metadata.sorted_tables if 'user_id' in table.c]


async def work_count(table, session):
    return (await session.execute(
        select(func.count()).select_from(table).where(table.c.user_id.in_(USERS))
    )).scalar_one()


def money(amount):
    return Money(amount=amount, currency='KRW')


async def inspect_rpc():
    for user_id, status, amount in [
        (EMPTY, BalanceStatus.NOT_LINKED, None), (CLOSED, BalanceStatus.NOT_LINKED, None),
        (ZERO, BalanceStatus.OK, Decimal('0')), (SUM, BalanceStatus.OK, Decimal('460000')),
    ]:
        result = await AssetClient().get_current_balance(user_id)
        assert result.status == status and result.amount == amount, (user_id, result)
    print('PASS: real Work client/mTLS: no account, no ACTIVE, zero, ACTIVE sum (CLOSED excluded)')
    async with grpc.aio.secure_channel(settings.ASSET_GRPC_TARGET, load_channel_credentials()) as channel:
        stub = asset_service_pb2_grpc.AssetServiceStub(channel)
        try:
            await stub.GetCurrentBalance(rpc.GetCurrentBalanceRequest(user_id=''), timeout=5)
        except grpc.aio.AioRpcError as error:
            assert error.code() == grpc.StatusCode.INVALID_ARGUMENT, error
        else:
            raise AssertionError('Empty user ID accepted')
    unavailable = await AssetClient(target='127.0.0.1:1', timeout=0.3).get_current_balance(SUM)
    assert unavailable.status == BalanceStatus.UNAVAILABLE and unavailable.amount is None, unavailable
    print('PASS: empty ID rejected; connection failure is UNAVAILABLE, not a confirmed zero balance')


def inspect_http():
    tokens = json.loads(os.environ['ASSET_TEST_TOKENS'])
    for user_id, source, amount in [
        (EMPTY, 'NOT_LINKED', Decimal('0')), (CLOSED, 'NOT_LINKED', Decimal('0')),
        (ZERO, 'ASSET_SERVICE', Decimal('0')), (SUM, 'ASSET_SERVICE', Decimal('460000')),
    ]:
        request = urllib.request.Request(
            f'http://gateway:8080/api/v1/work/simulator/{user_id}/simulate',
            data=b'{}', method='POST', headers={
                'Authorization': 'Bearer ' + tokens[str(user_id)], 'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.load(response)
            assert response.status == 200
        assert body['asset_source'] == source and Decimal(body['current_asset']) == amount, body
    print('PASS: Auth-signed JWT -> Gateway -> Work simulator -> Asset RPC -> HTTP result, all 4 cases')


async def inspect_kafka():
    producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    monitor = AIOKafkaConsumer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                              group_id=settings.KAFKA_CONSUMER_GROUP, enable_auto_commit=False)
    await producer.start()
    offsets = {}

    async def send(topic, event):
        record = await producer.send_and_wait(topic, key=str(SUM).encode(), value=event.SerializeToString())
        offsets[TopicPartition(topic, record.partition)] = record.offset + 1

    try:
        # 같은 거래를 새 event_id로 다시 보내도 거래 식별자로 한 번만 저장해야 한다.
        event = events.TransactionSucceededEvent(
            event_id='infra-work-smoke-transfer-1', transaction_id=880000000000000031,
            public_transaction_id='infra-work-smoke-public-1', user_id=str(SUM),
            account_id=ACCOUNT_IDS[2], external_transaction_id='infra-work-smoke-external-1',
            transaction_type='WITHDRAWAL', amount=money(12000), snapshot_balance=money(460000),
            snapshot_as_of='2026-10-10T00:00:00Z', succeeded_at='2026-09-20T05:00:00Z',
            occurred_at='2026-09-20T05:00:00Z', recovered_at='2026-10-10T00:00:00Z',
            recorded_at='2026-10-10T00:00:00Z', external_type='CARD', timestamp_source='CORE_BANKING',
        )
        await send(settings.KAFKA_TOPIC_TRANSACTION_SUCCEEDED, event)
        event.event_id = 'infra-work-smoke-transfer-2'
        await send(settings.KAFKA_TOPIC_TRANSACTION_SUCCEEDED, event)
        for revision, income in [(1, 100000), (1, 999), (2, 120000), (1, 999)]:
            await send(settings.KAFKA_TOPIC_MONTHLY_CASHFLOW, events.MonthlyCashflowAggregatedEvent(
                event_id=f'infra-work-smoke-monthly-{revision}', user_id=str(SUM),
                year_month=YEAR_MONTH, revision=revision, income_amount=money(income),
                expense_amount=money(12000), transfer_amount=money(5000), calculated_at='2026-10-10T00:00:00Z'))
        for revision, amount in [(1, 10000), (2, 12000), (1, 1)]:
            await send(settings.KAFKA_TOPIC_CATEGORY_CASHFLOW, events.CategoryCashflowAggregatedEvent(
                event_id=f'infra-work-smoke-category-{revision}', user_id=str(SUM),
                year_month=YEAR_MONTH, revision=revision, calculated_at='2026-10-10T00:00:00Z',
                categories=[events.CategoryCashflowAmount(category='FOOD', amount=money(amount))]))

        await monitor.start()
        # 해당 그룹의 처리 offset을 확인해 마지막 역순 이벤트까지 기다린다.
        # 구독 없이 committed만 조회하므로 Work의 partition을 가져가지 않는다.
        deadline = time.monotonic() + 40
        while True:
            completed = [await monitor.committed(partition) for partition in offsets]
            if all(actual is not None and actual >= wanted
                   for actual, wanted in zip(completed, offsets.values())):
                break
            assert time.monotonic() < deadline, ('Work consumer did not commit all test messages', offsets, completed)
            await asyncio.sleep(0.25)

        async with AsyncSessionLocal() as session:
            logs = (await session.execute(select(fds.FdsInferenceLog).where(
                fds.FdsInferenceLog.user_id == SUM))).scalars().all()
            assert len(logs) == 1 and logs[0].amount == Decimal('12000'), logs
            assert logs[0].occurred_at.strftime('%Y-%m') == YEAR_MONTH, logs[0].occurred_at
            monthly = (await session.execute(select(spending.MonthlyCashflow).where(
                spending.MonthlyCashflow.user_id == SUM))).scalars().all()
            assert len(monthly) == 1 and monthly[0].revision == 2, monthly
            assert (monthly[0].total_income, monthly[0].total_expense, monthly[0].total_transfer) == (
                Decimal('120000'), Decimal('12000'), Decimal('5000'))
            categories = (await session.execute(select(spending.CategoryCashflow).where(
                spending.CategoryCashflow.user_id == SUM))).scalars().all()
            assert len(categories) == 1 and categories[0].revision == 2 and categories[0].amount == Decimal('12000')
        print('PASS: real Kafka Protobuf transaction/monthly/category consumption; duplicate/new event ID; revision rollback ignored; original month preserved')
    finally:
        await monitor.stop()
        await producer.stop()


async def main():
    assert settings.APP_ENV in {'development', 'local', 'test'}, 'Local development only'
    redis = await get_redis()
    asset = await aiomysql.connect(host='asset-mysql', db='moaje_asset',
                                  user=os.environ['ASSET_TEST_DB_USER'], password=os.environ['ASSET_TEST_DB_PASSWORD'],
                                  autocommit=True)
    placeholders = ','.join(['%s'] * len(USERS))
    owns_data = False
    try:
        async with asset.cursor() as cursor:
            await cursor.execute(f'SELECT COUNT(*) FROM account WHERE user_id IN ({placeholders}) OR id IN ({",".join(["%s"] * len(ACCOUNT_IDS))})',
                                 [str(uid) for uid in USERS] + ACCOUNT_IDS)
            assert (await cursor.fetchone())[0] == 0, 'Reserved Asset fixture IDs already exist; refusing to overwrite'
            await cursor.execute(f'SELECT COUNT(*) FROM daily_cashflow_snapshot WHERE user_id IN ({placeholders})', [str(uid) for uid in USERS])
            assert (await cursor.fetchone())[0] == 0, 'Existing fixture cashflow snapshots'
        async with AsyncSessionLocal() as session:
            for table in work_tables:
                assert await work_count(table, session) == 0, f'Reserved Work user already exists in {table.name}'
        for user_id in USERS:
            assert not [key async for key in redis.scan_iter(match=f'work:*{user_id}*')], 'Existing fixture cache'
        owns_data = True
        async with asset.cursor() as cursor:
            for account_id, user_id, balance, status in [
                (ACCOUNT_IDS[0], CLOSED, 999999, 'CLOSED'), (ACCOUNT_IDS[1], ZERO, 0, 'ACTIVE'),
                (ACCOUNT_IDS[2], SUM, 120000, 'ACTIVE'), (ACCOUNT_IDS[3], SUM, 340000, 'ACTIVE'),
                (ACCOUNT_IDS[4], SUM, 999999, 'CLOSED'),
            ]:
                # 가상 계좌가 정기 대사에 잡히지 않도록 테스트 중에는 자동 동기화 대상에서 제외한다.
                await cursor.execute('INSERT INTO account (id,user_id,balance,status,sync_status,sync_retry_exhausted,created_at,updated_at) '
                                     "VALUES (%s,%s,%s,%s,'SYNCED',1,NOW(),NOW())", (account_id, str(user_id), balance, status))
        await inspect_rpc()
        inspect_http()
        await inspect_kafka()
        async with asset.cursor() as cursor:
            await cursor.execute(f'SELECT COUNT(*) FROM daily_cashflow_snapshot WHERE user_id IN ({placeholders})', [str(uid) for uid in USERS])
            assert (await cursor.fetchone())[0] == 0, 'Balance-only RPC unexpectedly wrote cashflow snapshots'
        print('PASS: balance-only RPC did not create DailyCashflow DB results')
    finally:
        if owns_data:
            async with AsyncSessionLocal() as session:
                for table in reversed(work_tables):
                    await session.execute(delete(table).where(table.c.user_id.in_(USERS)))
                await session.commit()
                for table in work_tables:
                    assert await work_count(table, session) == 0, table.name
            for user_id in USERS:
                keys = [key async for key in redis.scan_iter(match=f'work:*{user_id}*')]
                if keys:
                    await redis.delete(*keys)
                assert not [key async for key in redis.scan_iter(match=f'work:*{user_id}*')]
            async with asset.cursor() as cursor:
                await cursor.execute(f'DELETE FROM account WHERE user_id IN ({placeholders})', [str(uid) for uid in USERS])
                await cursor.execute(f'SELECT COUNT(*) FROM account WHERE user_id IN ({placeholders})', [str(uid) for uid in USERS])
                assert (await cursor.fetchone())[0] == 0
            print('PASS: reserved fixture Asset/Work DB rows and Work caches removed; Kafka records remain until retention')
        asset.close()
        await stop_redis()
        await engine.dispose()


asyncio.run(main())
