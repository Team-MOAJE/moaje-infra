# Gateway 재배포·페르소나 도구 후속 검증

## 변경

- Gateway 이미지 재빌드·컨테이너 재생성. Compose와 `.env.example`에 `POST /api/v1/auth/session/unlock`을 JWT 검사 제외 경로로 추가했다.
- 기존 `.env`에는 `AUTH_PUBLIC_ENDPOINTS`가 없어서 비밀키 등 다른 값은 변경하지 않았다.
- `test-fixture-console/app.py`: 합성 휴대폰 번호·이름·PIN 확인·필수 동의·약관 버전으로 가입하고 같은 번호로 로그인·계좌 개설한다.
- `test-fixture-console/static/index.html`: 로그인에 사용할 휴대폰 번호를 표시한다.
- `scripts/seed-monthly-cashflow-persona.sh`: 동일한 가입 규격을 사용하고 휴대폰 번호로 로그인한다. `PERSONA_PHONE`을 지정하거나 번호를 자동 생성할 수 있다.
- Auth·Banking·Asset·Work 업무 소스는 변경하지 않았다. 기존 개발 볼륨도 삭제하지 않았다.

## 실제 검증

테스트 데이터는 별도 Compose 프로젝트 `moaje-persona-verify-20261011`의 새 볼륨 7개에만 생성했다.
개발 Gateway와 페르소나 콘솔은 새 이미지로 배포하되, 검증용 회원·거래는 개발 DB에 넣지 않았다.

| 시험 | 결과 |
|---|---|
| Python 도구 계약 테스트 | 1건 통과. 가입 필수값, 휴대폰 로그인, 계좌 개설에 같은 번호 사용, JWT 미반환 확인 |
| Gateway 회귀 테스트 | `gradlew.bat test --offline --rerun-tasks`: 16건 통과 |
| Auth·Gateway HTTP 검증 | 17건 모두 통과. [원본 JSON](gateway-persona-retest-20261011.json) |
| JWT 없는 잠금 해제 | 정상 Refresh Token + PIN으로 200 |
| 잘못된 PIN | JWT 없이 호출해도 Auth에서 401 거절 |
| 잠금 해제 후 이전 Refresh Token | 재사용 시 401 거절. 새 토큰으로 후속 요청 |
| 콘솔 `POST /api/personas` | BALANCED_STUDENT, 3개월 요청: HTTP 201, 24건 생성, 월별 집계 3개 |
| 콘솔 생성 데이터 | 2026-08·09·10 각각 지출 153,500원, 휴대폰·PIN 반환 형식 확인 |
| 실제 `.sh` 실행 | Git Bash에서 7단계 모두 완료, 현재 월 거래 8건·지출 153,500원 |
| 카테고리 | FOOD 18,000 / CAFE 5,500 / TRANSPORT 12,000 / CULTURE 15,000 / SHOPPING 23,000 / STUDY 28,000 / HOUSING 45,000 / UNCATEGORIZED 7,000원 |

콘솔은 생성 HTTP API와 HTML 제공을 검사했다. 브라우저에서 버튼을 누르는 자동 UI 시험은 수행하지 않았다.
번호와 PIN은 로컬 합성 데이터다. SMS는 발송하지 않으며 `local-test-v1` 동의 값은 실제 사용자 동의의 증거가 아니다.

## 사용

- 페르소나 화면: http://localhost:8090
- 통합 Swagger: http://localhost:8080/docs/swagger-ui.html
- 콘솔 결과의 휴대폰 번호·PIN으로 Auth 로그인 후, JWT를 이용해 Asset 집계를 조회한다.
- 스크립트: Git Bash에서 `sh scripts/seed-monthly-cashflow-persona.sh`.

Gateway와 콘솔만 다시 배포하는 명령:

```powershell
docker compose --profile apps --profile test-tools build gateway test-fixture-console
docker compose --profile apps --profile test-tools up -d --no-deps --force-recreate gateway test-fixture-console
```

컨테이너 재배포는 데이터를 초기화하지 않는다. 콘솔에서 직접 생성한 데이터도 자동 삭제되지 않는다.
전체 로컬 DB를 지워도 되는 경우에만 기존 `scripts/reset-local-test-data.sh --yes`를 사용한다.
다른 개발 데이터를 보존해야 한다면 [별도 테스트 환경](run-on-another-pc.md#7-격리-통합테스트-실행-기준)을 사용한다.

검증 프로젝트의 컨테이너·볼륨 7개·인증서를 제거했다. 개발 환경의 새 Gateway·콘솔과 기존 데이터는 유지했다.
