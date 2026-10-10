"""Work 이미지 안에서 공통 Proto와 실제 Python 생성 코드의 호환성을 검사한다.

DB·Kafka 데이터는 생성하지 않는다. 실패한 계약은 exit 1로 보고하며
컨테이너 기동 성공을 업무 연동 성공으로 오해하지 않도록 별도 실행한다.
"""
import sys
import tempfile
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from grpc_tools import protoc

from app.grpc import asset_service_pb2
from app.grpc.events import asset_events_pb2
from app.kafka.consumer import PROTOBUF_TOPICS
from app.core.config import settings

root = Path(sys.argv[1] if len(sys.argv) > 1 else '/contracts')
with tempfile.TemporaryDirectory() as directory:
    target = Path(directory) / 'contract.pb'
    assert protoc.main([
        'protoc', f'-I{root}', '--include_imports', f'--descriptor_set_out={target}',
        str(root / 'grpc/asset_service.proto'), str(root / 'events/asset_events.proto'),
    ]) == 0
    file_set = descriptor_pb2.FileDescriptorSet.FromString(target.read_bytes())

pool = descriptor_pool.DescriptorPool()
for item in file_set.file:
    pool.Add(item)

failures = []
def check(label, expected, actual):
    if expected != actual:
        failures.append(label)
        print(f'FAIL: {label}: expected={expected!r}, Work={actual!r}')
    else:
        print(f'PASS: {label}')

for local in [asset_service_pb2.GetCurrentBalanceRequest,
              asset_service_pb2.GetCurrentBalanceResponse,
              asset_service_pb2.GetDailyCashflowRequest,
              asset_service_pb2.GetDailyCashflowResponse,
              asset_events_pb2.TransactionSucceededEvent,
              asset_events_pb2.MonthlyCashflowAggregatedEvent,
              asset_events_pb2.CategoryCashflowAggregatedEvent,
              asset_events_pb2.CategoryCashflowAmount]:
    canonical = pool.FindMessageTypeByName(local.DESCRIPTOR.full_name)
    for field in canonical.fields:
        actual = local.DESCRIPTOR.fields_by_number.get(field.number)
        # 메시지 이름이 같아도 필드 번호와 wire 타입이 다르면 역직렬화 결과가 달라진다.
        check(f'{canonical.name}.{field.name} #{field.number}',
              (field.name, field.type), (actual.name, actual.type) if actual else None)

for name, topic in [
    ('MonthlyCashflowAggregatedEvent', settings.KAFKA_TOPIC_MONTHLY_CASHFLOW),
    ('CategoryCashflowAggregatedEvent', settings.KAFKA_TOPIC_CATEGORY_CASHFLOW),
]:
    check(f'{topic} Protobuf dispatch', True, topic in PROTOBUF_TOPICS)
    check(f'{name} generated binding exists', True, hasattr(asset_events_pb2, name))

# 최신 계약으로 쓴 사용자 ID가 Work에서 그대로 읽히는지 실제 바이트로 확인한다.
canonical_type = message_factory.GetMessageClass(
    pool.FindMessageTypeByName('moaje.grpc.asset.GetCurrentBalanceRequest'))
wire = canonical_type(user_id='123').SerializeToString()
decoded = asset_service_pb2.GetCurrentBalanceRequest.FromString(wire)
check('RPC user_id wire round trip', '123', str(decoded.user_id))

print(f'Contract check: {len(failures)} failure(s); no DB/Kafka writes')
sys.exit(1 if failures else 0)
