"""로컬 시연 전용: Compose 라벨로 선택한 고정 저장소만 초기화한다."""
import http.client
import json
import os
import secrets
import shlex
import socket
import struct
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

TOKEN = os.environ['RESET_AGENT_TOKEN']
STATE_FILE = Path(os.getenv('RESET_STATE_FILE', '/data/reset.json'))
LOCK = threading.RLock()
STATE = {'status':'IDLE', 'stage':'대기'}
APP_SERVICES = {'gateway','auth','banking','asset','work','mock-banking'}
DB_SERVICES = {'auth-mysql','banking-mysql','asset-mysql','work-mysql'}
REDIS_SERVICES = {'redis','mock-redis'}
PRESERVE_TABLES = {'flyway_schema_history','alembic_version'}


class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


def docker(method, path, body=None, timeout=180):
    conn = DockerConnection('localhost', timeout=timeout)
    try:
        conn.request(method, '/v1.45'+path, body=json.dumps(body) if body is not None else None, headers={'Content-Type':'application/json'})
        response = conn.getresponse()
        data = response.read()
        if response.status >= 400:
            raise RuntimeError(f'Docker 요청 실패: {method} {path.split("?")[0]} HTTP {response.status}')
        if 'json' in response.getheader('Content-Type','') and data:
            return json.loads(data)
        return data
    finally:
        conn.close()


def unframe(data):
    output = bytearray()
    while data:
        if len(data)<8:
            raise RuntimeError('Docker 실행 결과를 읽지 못했습니다.')
        size = struct.unpack('>I', data[4:8])[0]
        output.extend(data[8:8+size])
        data=data[8+size:]
    return output.decode('utf-8',errors='replace')


def execute(container, command):
    task=docker('POST',f'/containers/{container}/exec',{'AttachStdout':True,'AttachStderr':True,'Cmd':command})
    output=unframe(docker('POST',f'/exec/{task["Id"]}/start',{'Detach':False,'Tty':False}))
    info=docker('GET',f'/exec/{task["Id"]}/json')
    if info['ExitCode'] != 0:
        # 명령 출력에는 인증정보가 있을 수 있으므로 콘솔에는 서비스와 단계만 남긴다.
        raise RuntimeError('저장소 명령 실패. 해당 컨테이너와 초기화 단계를 확인해주세요.')
    return output


def save(**values):
    with LOCK:
        STATE.update(values)
        STATE_FILE.parent.mkdir(parents=True,exist_ok=True)
        temp=STATE_FILE.with_suffix('.tmp')
        temp.write_text(json.dumps(STATE,ensure_ascii=False),encoding='utf-8')
        temp.replace(STATE_FILE)


def targets():
    own=docker('GET',f'/containers/{socket.gethostname()}/json')
    project=own['Config']['Labels']['com.docker.compose.project']
    containers=docker('GET','/containers/json?all=true')
    selected={}
    for c in containers:
        labels=c.get('Labels',{})
        if labels.get('com.docker.compose.project')==project:
            service=labels.get('com.docker.compose.service')
            if service in APP_SERVICES|DB_SERVICES|REDIS_SERVICES|{'kafka'}:
                if service in selected:
                    raise RuntimeError('서비스 복제본이 여러 개입니다. 단일 로컬 Compose만 지원합니다.')
                selected[service]=c
    required=APP_SERVICES|DB_SERVICES|REDIS_SERVICES|{'kafka'}
    if required-set(selected):
        raise RuntimeError('필수 컨테이너가 없습니다: '+', '.join(sorted(required-set(selected))))
    # 별도 Mock 프로젝트도 명시된 이름과 두 서비스 라벨이 모두 맞을 때만 포함한다.
    # 다른 프로젝트의 Redis나 사용자 PC 전체 볼륨으로 범위가 넓어지지 않게 한다.
    extra=os.getenv('RESET_EXTRA_MOCK_PROJECT','moaje-mock-banking')
    extra_containers=[c for c in containers if c.get('Labels',{}).get('com.docker.compose.project')==extra and extra!=project]
    if extra_containers:
        services={c['Labels'].get('com.docker.compose.service'):c for c in extra_containers}
        if set(services)!={'mock-banking-api','mock-banking-redis'} or len(extra_containers)!=2:
            raise RuntimeError('별도 Mock 프로젝트 구성이 예상과 달라 초기화를 거절합니다.')
        selected['extra-mock-api']=services['mock-banking-api']
        selected['extra-mock-redis']=services['mock-banking-redis']
    for name,c in selected.items():
        if name in DB_SERVICES|REDIS_SERVICES|{'kafka','extra-mock-redis'} and c['State']!='running':
            raise RuntimeError(f'{name} 저장소를 먼저 실행해주세요.')
    return project,selected


def mysql_reset(container):
    # 스키마를 버리면 Flyway/Alembic 및 Work 초기 테이블 복원이 필요하다.
    # 기존 스키마와 버전 이력은 보존하고 모든 업무 테이블의 행만 비운다.
    script = r'''set -eu
export MYSQL_PWD="$MYSQL_PASSWORD"
tables=$(mysql -N -B -u"$MYSQL_USER" "$MYSQL_DATABASE" -e "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' AND TABLE_NAME NOT IN ('flyway_schema_history','alembic_version')")
sql='SET FOREIGN_KEY_CHECKS=0;'
for table in $tables; do
  case "$table" in *[!a-zA-Z0-9_]*) exit 12;; esac
  sql="$sql TRUNCATE TABLE \`$table\`;"
done
sql="$sql SET FOREIGN_KEY_CHECKS=1;"
mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" -e "$sql"
for table in $tables; do
  count=$(mysql -N -B -u"$MYSQL_USER" "$MYSQL_DATABASE" -e "SELECT COUNT(*) FROM \`$table\`;")
  [ "$count" = 0 ] || exit 13
done
'''
    execute(container,['sh','-c',script])


def kafka_reset(container):
    # Producer와 Consumer를 먼저 중지한 뒤 모든 업무 토픽의 현재 끝까지 삭제한다.
    # 토픽·파티션은 유지하므로 재기동 시 계약을 다시 만들 필요가 없고 과거 이벤트도 재생되지 않는다.
    output=execute(container,['kafka-get-offsets','--bootstrap-server','localhost:29092','--time','-1'])
    partitions=[]
    for line in output.splitlines():
        fields=line.rsplit(':',2)
        if len(fields)==3 and fields[1].isdigit() and fields[2].isdigit() and not fields[0].startswith('__'):
            partitions.append(dict(topic=fields[0],partition=int(fields[1]),offset=int(fields[2])))
    if not partitions:
        topics=execute(container,['kafka-topics','--bootstrap-server','localhost:29092','--list'])
        if any(t.strip() and not t.startswith('__') for t in topics.splitlines()):
            raise RuntimeError('업무 토픽이 있으나 Kafka offset을 확인하지 못했습니다.')
        return 0
    payload=json.dumps({'partitions':partitions,'version':1})
    execute(container,['sh','-c',"printf %s "+shlex.quote(payload)+" > /tmp/moaje-reset-offsets.json && kafka-delete-records --bootstrap-server localhost:29092 --offset-json-file /tmp/moaje-reset-offsets.json"])
    after=execute(container,['kafka-get-offsets','--bootstrap-server','localhost:29092','--time','-2'])
    starts={}
    for line in after.splitlines():
        f=line.rsplit(':',2)
        if len(f)==3 and f[1].isdigit() and f[2].isdigit():
            starts[(f[0],int(f[1]))]=int(f[2])
    if any(starts.get((p['topic'],p['partition']),-1)<p['offset'] for p in partitions):
        raise RuntimeError('Kafka 메시지 삭제 확인 실패. 서버를 중지 상태로 유지합니다.')
    return len(partitions)


def run_reset():
    try:
        project,selected=targets()
        writers=APP_SERVICES|{'extra-mock-api'}
        # 실패 후 재시도에서도 원래 켜져 있던 앱 목록을 유지한다.
        # 중간 실패 시 자동으로 앱을 켜면 일부만 비워진 저장소에 거래가 다시 들어올 수 있다.
        original=STATE.get('resumeServices')
        if original is None:
            original=[s for s in writers if s in selected and selected[s]['State']=='running']
        save(stage='API·Worker 중지', project=project, resumeServices=original, targets=sorted(selected))
        for name in sorted(writers & selected.keys(),key=lambda n:n!='gateway'):
            docker('POST',f'/containers/{selected[name]["Id"]}/stop?t=30')
        save(stage='Kafka 업무 메시지 제거')
        partition_count=kafka_reset(selected['kafka']['Id'])
        for name in sorted(DB_SERVICES):
            save(stage=f'{name} 업무 데이터 삭제·검증')
            mysql_reset(selected[name]['Id'])
        for name in sorted((REDIS_SERVICES|{'extra-mock-redis'}) & selected.keys()):
            save(stage=f'{name} 캐시·세션·Mock 원장 삭제')
            if execute(selected[name]['Id'],['redis-cli','FLUSHALL','SYNC']).strip()!='OK':
                raise RuntimeError('Redis 초기화 실패')
            if execute(selected[name]['Id'],['redis-cli','DBSIZE']).strip()!='0':
                raise RuntimeError('Redis 초기화 검증 실패')
        save(stage='서버 재시작', deletedPartitions=partition_count)
        for name in sorted(original,key=lambda n:n=='gateway'):
            docker('POST',f'/containers/{selected[name]["Id"]}/start')
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            ready=True
            for name in original:
                state=docker('GET',f'/containers/{selected[name]["Id"]}/json')['State']
                if not state.get('Running') or state.get('Health',{}).get('Status','healthy')!='healthy':
                    ready=False
            if ready:
                # HTTP 서비스의 시작 완료까지 확인한다. 컨테이너 Running만으로 완료 처리하지 않는다.
                try:
                    import urllib.request
                    for path in ('banking/v3/api-docs','asset/v3/api-docs','auth/openapi.json'):
                        with urllib.request.urlopen('http://gateway:8080/docs/'+path,timeout=3) as response:
                            if response.status!=200:
                                raise RuntimeError('HTTP 기동 대기')
                    save(status='SUCCEEDED',stage='초기화 완료 · 앱에서 로그아웃 후 새로 가입해주세요',resumeServices=None)
                    return
                except Exception:
                    pass
            time.sleep(2)
        raise RuntimeError('데이터 초기화 후 일부 서버의 기동 확인이 지연됩니다. 컨테이너 로그를 확인해주세요.')
    except Exception as error:
        save(status='FAILED',stage='초기화 중단 · 부분 삭제 가능, 원인 확인 후 재시도',error=str(error))


class Handler(BaseHTTPRequestHandler):
    def respond(self,status,value):
        data=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        return secrets.compare_digest(self.headers.get('X-Reset-Token',''),TOKEN)

    def do_GET(self):
        if not self.allowed():
            return self.respond(403,{'message':'Forbidden'})
        with LOCK:
            self.respond(200,STATE)

    def do_POST(self):
        if not self.allowed() or self.path!='/reset':
            return self.respond(403,{'message':'Forbidden'})
        with LOCK:
            if STATE['status']=='RUNNING':
                return self.respond(409,{'message':'초기화가 이미 진행 중입니다.'})
            save(status='RUNNING',stage='대상 확인',error=None,id=uuid.uuid4().hex)
            threading.Thread(target=run_reset,daemon=True).start()
            self.respond(202,STATE)

    def log_message(self,*args):
        pass


if __name__=='__main__':
    if STATE_FILE.exists():
        STATE=json.loads(STATE_FILE.read_text(encoding='utf-8'))
        if STATE['status']=='RUNNING':
            save(status='FAILED',stage='초기화 도중 에이전트가 재시작됨 · 재시도 필요')
    ThreadingHTTPServer(('0.0.0.0',8091),Handler).serve_forever()
