"""격리 Compose에서만 실행하는 저장소 초기화 실측. 개발 데이터에는 실행할 수 없다."""
import time
import reset_agent as a

containers=a.docker('GET','/containers/json?all=true')
targets={c['Labels'].get('com.docker.compose.service'):c['Id'] for c in containers if c.get('Labels',{}).get('com.docker.compose.project')=='moaje-reset-verification'}
assert set(targets)=={'mysql','redis','kafka'}, '격리 검증 프로젝트만 허용합니다.'
mysql=targets['mysql']; redis=targets['redis']; kafka=targets['kafka']
for _ in range(45):
    try:
        a.execute(mysql,['sh','-c','MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" -e "SELECT 1"'])
        a.execute(kafka,['kafka-topics','--bootstrap-server','localhost:29092','--list'])
        break
    except RuntimeError:
        time.sleep(2)
else:
    raise RuntimeError('격리 저장소 준비 실패')
seed="CREATE TABLE flyway_schema_history(id INT); INSERT INTO flyway_schema_history VALUES(1); CREATE TABLE alembic_version(id INT); INSERT INTO alembic_version VALUES(1); CREATE TABLE account(id INT PRIMARY KEY); CREATE TABLE history(id INT, account_id INT, FOREIGN KEY(account_id) REFERENCES account(id)); INSERT INTO account VALUES(1); INSERT INTO history VALUES(1,1);"
a.execute(mysql,['sh','-c','export MYSQL_PWD="$MYSQL_PASSWORD"; mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" -e '+a.shlex.quote(seed)])
a.mysql_reset(mysql)
result=a.execute(mysql,['sh','-c','MYSQL_PWD="$MYSQL_PASSWORD" mysql -N -B -u"$MYSQL_USER" "$MYSQL_DATABASE" -e "SELECT (SELECT COUNT(*) FROM account),(SELECT COUNT(*) FROM history),(SELECT COUNT(*) FROM flyway_schema_history),(SELECT COUNT(*) FROM alembic_version)"'])
assert result.strip()=='0\t0\t1\t1', result
print('PASS MySQL: 업무 0행, 외래키 처리, migration 2종 보존')
a.execute(redis,['redis-cli','SET','disposable:test','1'])
assert a.execute(redis,['redis-cli','FLUSHALL','SYNC']).strip()=='OK'
assert a.execute(redis,['redis-cli','DBSIZE']).strip()=='0'
print('PASS Redis: 동기 삭제 완료')
a.execute(kafka,['kafka-topics','--bootstrap-server','localhost:29092','--create','--topic','reset-check','--partitions','2','--replication-factor','1'])
a.execute(kafka,['sh','-c',"printf 'one\ntwo\n' | kafka-console-producer --bootstrap-server localhost:29092 --topic reset-check"])
assert a.kafka_reset(kafka)==2
end=a.execute(kafka,['kafka-get-offsets','--bootstrap-server','localhost:29092','--time','-1'])
start=a.execute(kafka,['kafka-get-offsets','--bootstrap-server','localhost:29092','--time','-2'])
assert end==start,(end,start)
assert a.kafka_reset(kafka)==2
print('PASS Kafka: 2개 파티션 시작/끝 offset 일치, 반복 삭제 성공')
