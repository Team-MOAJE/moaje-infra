# Moaje Infra

Moaje 서비스 개발에 필요한 공통 인프라를 Docker Compose로 실행하는 저장소입니다.

현재 구성은 Spring Boot 기반 MSA 모듈을 로컬 IDE에서 실행하고, Redis/Kafka/Nginx/관측성 도구는 Docker Compose로 띄우는 개발 환경을 기준으로 합니다.

## 구성 요소

| Service | Container | Port | Purpose |
| --- | --- | --- | --- |
| Nginx | `moaje-nginx` | `80`, `443` | Gateway 앞단 reverse proxy, SSL termination |
| Redis | `moaje-redis` | `6379` | 캐시, 세션, 멱등성 키 저장소 |
| Kafka | `moaje-kafka` | `9092` | MSA 간 비동기 이벤트 메시징 |
| Kafka UI | `moaje-kafka-ui` | `8989` | Kafka topic/message 확인 UI |
| Prometheus | `moaje-prometheus` | `9090` | Spring Boot Actuator metrics 수집 |
| Grafana | `moaje-grafana` | `3000` | Prometheus 기반 대시보드 UI |

## 디렉터리 구조

```text
moaje-infra/
├─ docker-compose.yaml
├─ nginx/
│  └─ conf.d/
│     └─ default.conf
├─ monitoring/
│  ├─ prometheus/
│  │  └─ prometheus.yml
│  └─ grafana/
│     ├─ dashboards/
│     │  └─ moaje-gateway-overview.json
│     └─ provisioning/
│        ├─ dashboards/
│        │  └─ dashboards.yml
│        └─ datasources/
│           └─ prometheus.yml
└─ moajeGateway/
```

## 사전 준비

- Docker Desktop
- Java 17
- IntelliJ IDEA 또는 선호하는 IDE

Docker Desktop이 실행 중이어야 `docker compose up` 명령이 정상 동작합니다.

## 실행 방법

인프라 컨테이너를 실행합니다.

```powershell
cd C:\moaje\moaje-infra
docker compose up -d
```

상태를 확인합니다.

```powershell
docker compose ps
```

로그를 확인합니다.

```powershell
docker compose logs -f
```

중지합니다.

```powershell
docker compose down
```

볼륨까지 삭제하려면 아래 명령을 사용합니다. Redis/Kafka/Prometheus/Grafana 데이터와 로컬 개발용 Nginx 인증서가 삭제됩니다.

```powershell
docker compose down -v
```

## 접속 정보

| Tool | URL |
| --- | --- |
| Nginx HTTP | http://localhost |
| Nginx HTTPS | https://localhost |
| Gateway direct | http://localhost:8080 |
| Kafka UI | http://localhost:8989 |
| Prometheus | http://localhost:9090 |
| Prometheus targets | http://localhost:9090/targets |
| Grafana | http://localhost:3000 |

Grafana 초기 로그인 정보:

```text
ID: admin
PW: admin
```

Grafana에 로그인한 뒤 `Dashboards > Moaje > Moaje Gateway Overview`에서 기본 대시보드를 확인할 수 있습니다.

## 전체 요청 흐름

개발 환경의 기본 요청 흐름은 다음과 같습니다.

```text
Client
  -> http://localhost 또는 https://localhost
  -> Nginx container
  -> host.docker.internal:8080
  -> moajeGateway Spring Boot app, IDE 실행
  -> 각 MSA module
```

Nginx는 `http://localhost` 요청을 `https://localhost`로 redirect합니다.

`https://localhost`는 로컬 개발용 self-signed 인증서를 사용하므로 브라우저에서 보안 경고가 표시될 수 있습니다. 개발 환경에서는 경고를 수락하고 진행하면 됩니다.

## Spring Boot 앱 실행 방식

현재 개발 구조에서는 각 MSA 애플리케이션을 Docker 컨테이너로 띄우지 않고 IDE에서 직접 실행합니다.

예를 들어 `moajeGateway`는 IntelliJ에서 Spring Boot 애플리케이션으로 실행합니다.

```text
moajeGateway Spring Boot App -> IDE 실행
Nginx/Redis/Kafka/Prometheus/Grafana -> docker compose 실행
```

IDE에서 실행되는 Spring Boot 앱은 Docker 밖의 호스트 프로세스이므로 아래 주소를 사용합니다.

```text
Redis: localhost:6379
Kafka: localhost:9092
Gateway direct: http://localhost:8080
Gateway via Nginx: https://localhost
Gateway Actuator: http://localhost:8080/actuator
Gateway Prometheus endpoint: http://localhost:8080/actuator/prometheus
```

Prometheus는 Docker 컨테이너 안에서 호스트의 Gateway 앱을 바라봐야 하므로 `host.docker.internal:8080`을 scrape target으로 사용합니다.

```yaml
scrape_configs:
  - job_name: moaje-gateway
    metrics_path: /actuator/prometheus
    static_configs:
      - targets:
          - host.docker.internal:8080
```

Gateway 포트를 변경하면 아래 파일의 target도 같이 수정해야 합니다.

```text
monitoring/prometheus/prometheus.yml
nginx/conf.d/default.conf
```

## Nginx

Nginx는 Gateway 앞단 reverse proxy와 SSL termination 용도로 사용합니다.

현재 설정 파일:

```text
nginx/conf.d/default.conf
```

기본 proxy target:

```nginx
upstream moaje_gateway {
    server host.docker.internal:8080;
}
```

즉, Docker Compose로 실행되는 Nginx가 IDE에서 실행 중인 Gateway 앱으로 요청을 전달합니다.

### 로컬 SSL 인증서

`nginx-cert-init` 컨테이너가 최초 실행 시 named volume `nginx-certs`에 로컬 개발용 self-signed 인증서를 자동 생성합니다.

생성되는 인증서 경로는 컨테이너 내부 기준입니다.

```text
/etc/nginx/certs/local.crt
/etc/nginx/certs/local.key
```

이 인증서는 로컬 개발용입니다. 운영 또는 외부 공개 환경에서는 실제 도메인 인증서로 교체해야 합니다.

운영 인증서를 사용할 때는 다음 중 하나를 선택할 수 있습니다.

1. `nginx-certs` volume에 운영 인증서를 배치
2. 호스트의 인증서 디렉터리를 `/etc/nginx/certs`로 bind mount
3. Let's Encrypt/Certbot 또는 별도 인증서 자동화 도구 사용

운영 인증서 파일명은 현재 Nginx 설정 기준으로 아래 이름을 맞추면 됩니다.

```text
local.crt
local.key
```

파일명을 다르게 쓰려면 `nginx/conf.d/default.conf`의 `ssl_certificate`, `ssl_certificate_key` 값을 수정하세요.

## Kafka 접속 주소

Kafka는 호스트 애플리케이션과 Docker 내부 컨테이너에서 사용하는 주소가 다릅니다.

| Client | Bootstrap Server |
| --- | --- |
| IDE에서 실행하는 Spring Boot 앱 | `localhost:9092` |
| Docker Compose 내부 컨테이너 | `kafka:29092` |

Kafka UI는 Compose 내부 컨테이너이므로 `kafka:29092`로 Kafka에 접속합니다.

## Redis 접속 주소

| Client | Redis Host |
| --- | --- |
| IDE에서 실행하는 Spring Boot 앱 | `localhost:6379` |
| Docker Compose 내부 컨테이너 | `redis:6379` |

`moajeGateway`는 기본 설정에서 Redis를 `localhost:6379`로 바라봅니다.

## 모니터링

`moajeGateway`는 Spring Boot Actuator와 Micrometer Prometheus registry를 통해 metrics를 노출합니다.

주요 endpoint:

```text
http://localhost:8080/actuator/health
http://localhost:8080/actuator/metrics
http://localhost:8080/actuator/prometheus
```

Prometheus는 `/actuator/prometheus`를 수집하고, Grafana는 Prometheus datasource를 자동으로 등록합니다.

기본 대시보드에는 다음 항목이 포함됩니다.

- Request rate
- 5xx error rate
- HTTP request rate by status
- HTTP latency p95
- JVM memory used
- JVM threads

## 운영 전 주의사항

현재 compose 구성은 로컬 개발 편의를 위한 설정입니다.

운영 또는 외부 공개 환경에서는 최소한 아래 항목을 별도로 검토해야 합니다.

- Redis/Kafka 인증 및 네트워크 접근 제한
- Kafka PLAINTEXT 대신 SSL/SASL 적용
- Grafana 기본 비밀번호 변경
- Nginx 운영 도메인과 실제 TLS 인증서 적용
- Nginx SSL cipher/HSTS 정책 검토
- Actuator endpoint 외부 노출 제한
- Prometheus/Grafana 데이터 보존 정책
- Docker volume 백업 정책

## 자주 쓰는 명령어

```powershell
# 인프라 실행
cd C:\moaje\moaje-infra
docker compose up -d

# 컨테이너 상태 확인
docker compose ps

# 전체 로그 확인
docker compose logs -f

# 특정 서비스 로그 확인
docker compose logs -f nginx
docker compose logs -f kafka

# Nginx 설정만 재시작
docker compose restart nginx

# 인프라 중지
docker compose down

# 인프라 중지 및 볼륨 삭제
docker compose down -v
```
