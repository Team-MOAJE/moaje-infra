# 📚 moaje-infra 기술 가이드 및 컨벤션

본 문서는 `moaje` 프로젝트의 공통 인프라(Kafka, Redis) 구성 설명과 도메인 간 통신을 위한 Protobuf(`.proto`) 작성 가이드라인을 담고 있습니다.

---

## 1. docker-compose.yaml 상세 가이드

이 파일은 프로젝트 실행에 필요한 인프라 서버들을 한 번에 실행하는 설계도입니다. 각 설정의 핵심 의미는 다음과 같습니다.

### 🔹 공통 설정

- **`version: '3.8'`**: 도커 컴포즈 파일 규격 버전입니다.
- **`services:`**: 실행할 컨테이너(소프트웨어) 목록을 정의합니다.

### 🔹 [Redis] - 고속 데이터 캐시 및 세션 관리

- **`image: redis:latest`**: 최신 버전의 Redis 이미지를 사용합니다.
- **`container_name: moaje-redis`**: 컨테이너 식별 이름입니다.
- **`platform: linux/amd64`**: Mac(Apple Silicon) 사용자와 Windows 사용자 간의 이미지 호환성을 보장합니다.
- **`ports: - "6379:6379"`**: 로컬 PC의 6379 포트를 컨테이너 내부 6379 포트와 연결합니다.
- **`restart: always`**: 에러로 인해 꺼질 경우 도커가 자동으로 다시 살려내도록 설정합니다.

### 🔹 [Kafka] - 비동기 메시지 큐 (KRaft 방식)

주키퍼(Zookeeper) 없이 카프카 자체가 클러스터를 관리하는 최신 **KRaft** 방식을 채택했습니다. `KAFKA_CFG_`에서 **CFG**는 설정(Configuration)을 의미합니다.

- **`KAFKA_CFG_NODE_ID=1`**: 이 카프카 노드의 고유 번호입니다.
- **`KAFKA_CFG_PROCESS_ROLES=controller,broker`**: 이 노드가 관리자(Controller)와 일꾼(Broker) 역할을 동시에 수행함을 선언합니다.
- **`KAFKA_CFG_LISTENERS`**: 데이터 통신용(9092)과 내부 관리용(9093) 통로를 개방합니다.
- **`KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP`**: 현재 개발 환경은 암호화 없는 `PLAINTEXT`를 사용하지만, 실 서비스 도입 시에는 보안을 위해 `SSL` 적용이 필요합니다.
- **`KAFKA_CFG_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092`**: 외부 서비스(Spring Boot/FastAPI)가 접속할 때 사용하는 공식 주소(명함)입니다.
- **`KAFKA_CFG_CONTROLLER_QUORUM_VOTERS=1@127.0.0.1:9093`**: KRaft 모드에서 의사결정을 내릴 투표권자 명단입니다.
- **`KAFKA_CFG_CONTROLLER_LISTENER_NAMES=CONTROLLER`**: 관리용 통로의 이름을 지정합니다.

### 🔹 [Kafka-UI] - 메시지 모니터링 도구

- **`ports: - "8989:8080"`**: Spring Boot 기본 포트(8080)와의 충돌을 피하기 위해 외부 접속 포트를 **8989**로 변경했습니다. 웹 브라우저에서 `http://localhost:8989`로 접속하세요.
- **`KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS=kafka:9092`**: UI가 정보를 가져올 대상 카프카 서버 주소입니다.

---

## 2. 디렉터리 구조 및 용도 설명

`moaje-infra/proto` 내의 디렉터리는 통신 성격에 따라 엄격히 구분합니다.

| 디렉터리      | 용도                           | 통신 방식 | 예시                      |
| :------------ | :----------------------------- | :-------- | :------------------------ |
| **`common/`** | 공용 데이터 구조               | -         | `Money`, `IdempotencyKey` |
| **`grpc/`**   | 서비스 간 동기 통신 인터페이스 | **gRPC**  | 잔액 조회, 복호화 요청    |
| **`events/`** | 비동기 이벤트 메시지 규격      | **Kafka** | 송금 완료, AI 분석 요청   |

- **`common/`**: 모든 도메인에서 재사용되는 데이터 구조를 정의하여 일관성을 유지합니다.
- **`grpc/`**: "지금 당장 데이터를 줘"와 같은 실시간 요청/응답 시나리오에 사용합니다.
- **`events/`**: "이런 일이 발생했어"라고 알리는 공고 형태이며, 발행자는 수신자를 기다리지 않습니다.

---

## 3. 팀원을 위한 .proto 작성 가이드라인

폴리글랏(Kotlin, Python) 환경에서의 원활한 통신을 위해 아래 규칙을 반드시 준수해야 합니다.

1.  **네이밍 컨벤션 (Naming Convention)**
    - **필드명**: 반드시 **`snake_case`**를 사용합니다. (예: `user_id`, `amount_value`)
    - **메시지명**: **`PascalCase`**를 사용합니다. (예: `TransferRequest`)
2.  **필드 태그 번호 고정**
    - 필드 옆의 숫자(`= 1;`)는 데이터의 고유 주소입니다. 한 번 부여된 번호는 **절대 수정하거나 삭제하지 마세요.** 번호를 바꾸면 구버전과 신버전 서비스 간에 데이터가 깨집니다.
3.  **필수 메타데이터 포함**
    - 모든 메시지에는 로그 추적용 `transaction_id`와 생성 시각인 `timestamp`를 포함할 것을 강력히 권장합니다.
4.  **하위 호환성 유지 (Backward Compatibility)**
    - 기존 필드가 더 이상 필요 없어져도 삭제하지 마세요. 삭제가 필요하다면 `reserved` 키워드를 사용하여 번호를 예약해야 통신 에러를 방지할 수 있습니다.
5.  **공통 타입 재사용**
    - 금액(Money)이나 공통 헤더는 `common/` 디렉터리에 정의된 규격을 `import`하여 사용함으로써 중복 정의를 방지합니다.

---

---

## 4. 팀원을 위한 PR 가이드라인

핀테크 협업 관계에서는 Branch와 각 소스코드들의 오염과 혼선을 방지하고자 무조건 PR을 해야합니다.

1.  **최신코드 가져오기**
    - **dev에서 가져오기**: 작업을 시작하기 전에 항상 dev의 최신 상태를 유지하기 위해, dev에서 소스코드를 내려받습니다.
    ```bash
    git checkout dev
    git pull origin dev
    ```
2.  **작업 브랜치 생성**
    - 기능 단위로 브랜치를 만듭니다.
    - 네이밍규칙: `feat/기능이름` 또는 `fix/버그이름`
    ```bash
    git checkout -b feat/add-banking-proto
    ```
3.  **작업완료 이후 푸시**
    - 작업완료 혹은 코드 수정이후 본인의 브랜치에 올립니다.
    ```bash
    git add .
    git commit -m "feat: Banking 도메인 Kafka 이벤트 규격 추가"
    git push origin feat/add-banking-proto
    ```
4.  ** PR 생성 **
    - 깃허브에서 `feat/add-banking-proto` → `dev` 방향으로 Pull Request를 생성합니다.

5.  ** PR 리뷰 및 병합(merge) **
    - 팀원들의 리뷰를 거쳐 `dev`에 합쳐집니다.

---

**위 가이드라인에 따라 작성된 `.proto` 파일은 `moaje-infra` 레포지토리에 반영해 주시기 바랍니다.**
