"""실행 JSON과 명세 목록으로 한글 PDF를 만든다. 결과를 실행 성공으로 추정하지 않는다."""
import json
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf/moaje-integration-test-report-20261010.pdf'
OUT.parent.mkdir(parents=True, exist_ok=True)
raw = json.loads((ROOT / '.local/e2e-20261010-results.json').read_text(encoding='utf-8'))
catalog = json.loads((ROOT / '.local/e2e-20261010-catalog.json').read_text(encoding='utf-8'))
pdfmetrics.registerFont(TTFont('KR', 'C:/Windows/Fonts/malgun.ttf'))
pdfmetrics.registerFont(TTFont('KRB', 'C:/Windows/Fonts/malgunbd.ttf'))
pdfmetrics.registerFontFamily('KR', normal='KR', bold='KRB', italic='KR', boldItalic='KRB')
BODY = ParagraphStyle('body', fontName='KR', fontSize=9.4, leading=15, spaceAfter=7, wordWrap='CJK')
SMALL = ParagraphStyle('small', parent=BODY, fontSize=8, leading=12, spaceAfter=3)
TITLE = ParagraphStyle('title', parent=BODY, fontName='KRB', fontSize=23, leading=32, spaceAfter=16)
H1 = ParagraphStyle('h1', parent=BODY, fontName='KRB', fontSize=15, leading=22, spaceBefore=5, spaceAfter=13)
H2 = ParagraphStyle('h2', parent=BODY, fontName='KRB', fontSize=11, leading=17, spaceBefore=10, spaceAfter=8)
STORY = []


def para(text, style=BODY):
    return Paragraph(escape(str(text)).replace('\n', '<br/>'), style)


def p(text):
    STORY.append(para(text))


def h(text, anchor):
    STORY.append(Paragraph(f'<a name="{anchor}"/>' + escape(text), H1))


def table(headers, rows, widths):
    data = [[para(v, SMALL) for v in headers]] + [[para(v, SMALL) for v in row] for row in rows]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E8EEF2')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), .7, colors.HexColor('#93A3AE')),
        ('LINEBELOW', (0, 1), (-1, -1), .25, colors.HexColor('#DCE3E7')),
        ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    STORY.append(t)
    STORY.append(Spacer(1, 10))


test_errors = {'잘못된 PIN 길이', '실제 Asset 월 집계 Outbox → Work', '실제 Asset 카테고리 Outbox → Work',
               'Mock 다개월 페르소나 API', '전월 늦은 거래 자동 revision 증가',
               '시험 단계 중단 extended', '시험 단계 중단 multimonth'}
rows = []
for original in raw:
    row = dict(original)
    if row['name'] in test_errors:
        row['status'] = 'TEST_ERROR'
    if row['name'] == '시험 단계 중단 normal':
        row['status'] = 'BLOCKED'
    rows.append(row)
counts = Counter(r['status'] for r in rows)

STORY += [para('MOAJE 종합 통합 테스트', TITLE), para('실제 실행 결과와 수정 우선순위', H1)]
p('2026년 10월 10일 | 로컬 Docker Compose 격리 환경')
p('회원가입 기준: email + 6자리 PIN. SMS 발송·인증은 폐기된 요구사항으로 제외했다. 휴대폰 가입 규격은 향후 Auth 업데이트 후 별도 검증한다.')
p('결론: 전체 송금 흐름은 미통과다. Banking 송금 진입점의 HTTP 500으로 금융 후속 시험이 막혔다. 독립적인 Mock 외부 지출 → Asset 스냅샷 → 거래·집계 Outbox → Work 소비 경로는 실제로 검증했다.')
table(['판정', '검증 기록 수', '의미'], [
    ['PASS', counts['PASS'], '해당 HTTP·DB·RPC·Kafka 관찰 또는 Assertion 통과'],
    ['FAIL', counts['FAIL'], '실제 제품 결함 관찰 5건, 수정 원인 그룹 4개'],
    ['TEST_ERROR', counts['TEST_ERROR'], '기대 상태·SQL·초기 잔액 등 시험 준비 문제. 원본 기록 보존, 수정 후 재검증'],
    ['BLOCKED', counts['BLOCKED'], '송금 실패로 최초 실행 단계가 중단된 기록'],
], [64, 80, 367])
p('위 숫자는 재확인과 명세 조회를 포함한 121개 기록의 분류이며, 고유 기능 수나 전체 기능 통과율이 아니다. 실행하지 않은 장애 시나리오는 별도로 표시했다. 원본 JSON의 FAIL 13건을 숨기지 않고 제품 결함·시험 오류·후속 중단으로 구분했다.')
for title, anchor in [('1. 환경과 기준 코드', 'environment'), ('2. 정상 기능 실행 결과', 'normal'),
                      ('3. 결함과 담당 서비스', 'findings'), ('4. 보류된 시나리오', 'blocked'),
                      ('5. 시험 오류·한계', 'limits'), ('6. 재현·정리', 'cleanup'),
                      ('7. 실행 API 목록', 'api'), ('8. 개별 검증 기록', 'records')]:
    STORY.append(Paragraph(f'<link href="#{anchor}" color="#24617A">{escape(title)}</link>', BODY))

STORY.append(PageBreak())
h('1. 환경과 기준 코드', 'environment')
table(['구분', '내용'], [
    ['격리 프로젝트', 'moaje-e2e-20261010 / Gateway 127.0.0.1:19080'],
    ['데이터 격리', '테스트 전용 MySQL 4개·Redis 2개·Kafka 볼륨 1개, 별도 네트워크·gRPC 인증서'],
    ['이미지', 'Auth·Work·Banking·Asset·Gateway·Mock을 현재 로컬 코드로 빌드. JVM 빌드의 -x test 옵션으로 단위 테스트는 실행하지 않음'],
    ['테스트 설정', 'Banking 대사 활성화·주기 5초, Asset 전월 재집계 주기 15초. 개발 기본 설정 변경 아님'],
    ['장애 프록시', '테스트 전용 Python 프록시 구성. 송금 500으로 Timeout 주입 시험은 실행하지 못함'],
    ['기존 환경', '기존 개발 스택·볼륨·코드를 보존. 업무 소스 수정·Git 커밋·푸시 없음'],
], [110, 401])
table(['저장소', '기준 commit', '시작 시 미커밋 파일 수'], [
    ['Auth', 'de91daa', '0'], ['Work', '0f73ea5', '0'], ['Banking', '9a8123e', '103'],
    ['Asset', '4ef7b9c', '46'], ['공통 gRPC 계약', 'b40e773', '0'], ['Infra', 'ebc9190', '27'], ['Mock', '90519f4', '0'],
], [155, 130, 226])
p('Banking·Asset·Infra는 기존 미커밋 변경을 포함한다. 따라서 commit만 체크아웃한 코드와 이번 실행 이미지가 같다고 주장할 수 없다. 파일 수는 조사 시점이며 테스트 파일 추가로 변할 수 있다.')

STORY.append(PageBreak())
h('2. 정상 기능 실행 결과', 'normal')
table(['흐름', '검증 결과'], [
    ['가입·인증', '실제 사용자 3명 가입 201·로그인 200. 중복 가입 409, 틀린 PIN 로그인 422, 잘못된 길이 400. JWT POST/GET 검증, refresh 교체·재사용 거절·로그아웃 후 refresh 거절 확인'],
    ['계좌 개설', 'Gateway → Banking → Mock 계좌 개설 201. 계좌 생성 Kafka 이벤트를 Asset이 소비하여 상세 조회 가능'],
    ['송금', '실제 POST /api/v1/banking/transfers가 500. Banking 거래 행 0건 확인. 멱등성 키 누락은 Gateway에서 400으로 차단되지만 정상 송금·Application 멱등성은 미검증'],
    ['스냅샷·페이지', 'Mock 공개 출금 API로 CAFE 1원 거래 121건 생성. Asset refresh 잔액 99,879원. 50/50/21건 조회, 중복·누락 없음. 단건 조회 200, 반복 refresh 121건 유지'],
    ['일별 계산', '(99,879 + 100,000 - 10,000 - 5,000) / 10 = 18,487.9원. 캐시 동일 입력 결과 일치. ACTIVE 0원 계산 정상, 미연동 409, 0일 400'],
    ['잔액·계산 RPC', 'Work 인증서로 실제 mTLS GetCurrentBalance·GetDailyCashflow 성공. 빈 사용자 INVALID_ARGUMENT, 미연동 FAILED_PRECONDITION. CLOSED 계좌 합산 제외 및 HTTP 일별 계산 409'],
    ['월·카테고리', '현재 월 지출 121원·자금이동 0원·CAFE 121원. 거래 없는 사용자 조회에서 0원 집계 생성. 실제 Asset Outbox가 발행한 월/카테고리 이벤트를 Work DB 금액으로 검증'],
    ['다개월·revision', '100만원 별도 계좌에 3개월 24건(월 153,500원) 생성. 잔액 539,500원, 스냅샷 24건. fixture 재요청 생성 0·생략 24. 전월 0원 revision 1에서 153,500원 revision 2로 자동 갱신, Work에도 revision 2 반영'],
    ['Work 거래 소비', '실제 Asset 성공 이벤트로 Work 거래 기록 121건 생성. 다개월 시험 후 151건 상태에서 같은 성공 본문·새 eventId 재발행 후 151건 유지. 마지막 Kafka offset 처리 확인'],
    ['역순 revision', '전월 revision 1·지출 1원 이벤트를 뒤늦게 재발행해도 revision 2·153,500원 유지. Work Consumer offset 확인'],
    ['Work 사용자 기능', '온보딩 10문항·수정·진행·미래 카드, 시뮬레이터·조건 변경·준비도, 일정 등록/조회/자동 동기화, 학기 리포트·Recap, FDS 탐지/동일 거래/알림 확인 API 응답 확인. 소비 프로필은 500'],
    ['Work 운영 기능', '사용자만으로 운영 지표 403. 격리 전용 운영 토큰으로 블랙리스트 등록 201·해제 200·지표 200'],
], [103, 408])
p('일별 RPC 금액은 공통 Money의 int64로 변환되어 daily_limit=9,987로 응답했다. HTTP의 소수 네 자리 계산과 단위가 동일하게 보존된다고 가정하지 않는다. AI 결과의 정확도·수익성·품질은 검증 대상이 아니다.')

STORY.append(PageBreak())
h('3. 결함과 담당 서비스', 'findings')
findings = [
    ('F01 | Banking | 송금 차단',
     '정상 로그인 후 송금이 HTTP 500이다. 서버 예외는 PrincipalId.constructor-impl의 value가 null이라는 NullPointerException이다. 계좌 개설은 정상이며 송금 컨트롤러에서 막힌다. Banking 거래 행은 0건이다.',
     'TransferController.kt:28은 @AuthUserId PrincipalId를 받지만 AuthUserIdArgumentResolver.kt:41은 String인 principal.name을 반환한다. MVC에 addArgumentResolvers로 등록하는 코드도 src/main 검색에서 발견되지 않았다. 실제 500 원인 위치와 이 두 정합성 문제를 함께 수정·검증해야 한다. @Component만으로 MVC 등록이 보장된다고 보면 안 된다.',
     '우선순위 1. 수정 승인 후 정상 송금 회귀 테스트부터 다시 실행하고, 그 뒤 장애 시험을 진행한다.'),
    ('F02 | Auth | 타인 계좌 토큰 발급 허용',
     '송금인 JWT로 수취인의 user_id와 가짜 계좌 식별값을 넣어 POST /api/v1/auth/account-token을 요청하자 HTTP 200으로 발급에 성공했다. 예상 403과 다르다.',
     'moaje-auth/app/api/auth.py:create_account_token은 본문의 payload.user_id를 서비스에 전달한다. 본인 API라면 검증된 사용자와의 일치를 확인해야 한다. 위임용 내부 API라면 공개 Gateway 경로에서 분리하고 별도 권한 계약이 필요하다.',
     '우선순위 1. Auth 담당자 확인 필요. 이번 결과가 실제 계좌 소유까지 증명한 것은 아니지만 타인 사용자 ID 지정이 허용된 사실은 확인했다.'),
    ('F03 | Asset | 조회 오류의 HTTP 매핑 누락',
     '타인 계좌 상세 조회와 본인 계좌 경로에 다른 계좌 거래 ID를 넣은 요청 모두 HTTP 500이다. 서버는 각각 사용자의 계좌가 아닙니다 / 거래를 찾을 수 없습니다라는 IllegalArgumentException을 던졌다.',
     'AccountDetailServiceImpl.kt:45,75,118,127. 조회 자체는 거절되어 이번 시험에서 정보가 반환되지는 않았다. 그러나 예상되는 사용자 오류가 500으로 내려가므로 명확한 403 또는 노출 정책에 따른 404로 매핑해야 한다. 계좌 생성 직후 아직 Projection이 없는 조회도 같은 500을 관찰했다.',
     '우선순위 2. 도메인 예외·Advice로 구분하고 상세/단건/목록/refresh에 같은 정책을 적용한다.'),
    ('F04 | Work | 소비 프로필 응답 500',
     '실제 거래 성공 이벤트를 소비한 뒤 GET /spending/{user_id}/profile에서 HTTP 500이다. 서버의 ResponseValidationError는 last_analyzed_at=None이 유효한 datetime이 아니라는 내용이다.',
     'app/schemas/spending.py:18은 last_analyzed_at: datetime을 필수로 선언한다. app/services/ai/spending_service.py:62-63은 값이 없으면 None을 캐시에 쓴다. 필드가 언제 반드시 있어야 하는지와 캐시/DB 반환의 규격을 맞춰야 한다.',
     '우선순위 2. Work 담당자가 수정한다. 초기 사용자 프로필 성공만으로 거래 소비 이후 프로필 성공을 대신할 수 없다.'),
]
for title, actual, source, action in findings:
    STORY.append(para(title, H2))
    p(actual)
    p(source)
    p(action)

STORY.append(PageBreak())
h('4. 보류된 시나리오', 'blocked')
table(['계획 ID', '현재 판정과 이유'], [
    ['A03~A06', '정상 송금 및 그에 의존하는 결과 저장·멱등성·본문 충돌·잔액 부족 시험은 Controller 500으로 BLOCKED. 키 누락 Gateway 차단만 별도 PASS'],
    ['B01', '같은 키 경쟁·다른 키 동시 출금: 원거래 진입점 복구 후 실행'],
    ['B02~B03', 'Banking 성공 이벤트의 Asset 중복 소비·스냅샷과 도착 순서 역전: BLOCKED. 이번에 검증한 Work 중복 소비와 구분'],
    ['B04~B06', 'Kafka 중단·ack 직후 종료·Outbox retry 소진·다중 Publisher Lease: NOT RUN. 실패하는 송금으로 정상 결과 보존을 입증할 수 없음'],
    ['B07~B09', '응답 Timeout·결과 저장 직전 종료·대사 Lease/attempt 소진: BLOCKED. 프록시는 준비했으나 실제 지연 주입은 하지 않음'],
    ['B10~B11', 'Asset DB 장애·손상 Protobuf·DLT 발행 실패·SYNC_REQUIRED 복구: NOT RUN. 별도 장애 검증이 필요하며 단순 refresh 성공으로 대체하지 않음'],
    ['B12', 'Work 중단 후 따라잡기: NOT RUN. Work 정상 실행 중 실제 소비·revision·중복 처리는 PASS'],
    ['기타', '보상 실행 정책, 반전 실행, 실제 SMS, AI 예측 품질, 부하/처리량, 모든 일정의 보존·캐시 입력 조합은 이번 시험에서 보장하지 않음'],
], [76, 435])
p('전월 재집계는 테스트 주기를 15초로 바꿔 실제 Worker 경로를 실행했다. 매월 1일 정각의 운영 cron 자체를 기다려 관찰한 것은 아니다. 미연동 사용자의 0원 집계는 조회 API로 확인했으며, 정기 Worker가 계좌 없는 모든 Auth 사용자를 찾아 발행한다는 보장은 검증하지 않았다.')

h('5. 시험 오류·한계', 'limits')
p('제품 결함을 덮기 위해 Assertion을 느슨하게 바꾸지 않았다. 아래는 실제 코드와 시험 입력을 대조해 원인이 시험 쪽에 있음을 확인한 항목이다. 원본 실패 기록은 부록에 남겼다.')
table(['시험 문제', '수정·재검증'], [
    ['PIN 길이 기대 422', 'Auth app/main.py의 RequestValidationError 핸들러는 400이다. 기대값 400으로 재실행해 PASS. 잘못된 PIN 로그인 422와는 다른 경로'],
    ['집계 DB SQL 오류', 'MySQL YEAR_MONTH 예약어인 컬럼을 인용하지 않은 시험 SQL 때문에 조회 실패. `year_month`로 인용한 뒤 월 집계 1건·카테고리 CAFE 1건 및 금액 확인'],
    ['fixture 잔액 부족', '처음의 99,879원 계좌로 3개월 총 460,500원을 준비하려 해 400. 충분한 잔액의 새 100만원 계좌로 24건·최종 539,500원 검증'],
    ['단계 중단', '정상 송금 500 뒤 transferId를 읽으려던 시험의 KeyError와 SQL 단계 중단을 구분. 이후 독립 단계로 나눠 나머지 기능 검사'],
    ['반복 실행 제한', '테스트 스크립트는 순서형 세션 검사다. setup을 다시 실행하면 중복 가입이므로 빈 테스트 볼륨으로 시작해야 한다. 금융 장애 단계는 선행 송금 수정 전 실행 금지'],
], [115, 396])
p('테스트 스크립트의 종료 코드만으로 제품 성공을 판정하지 않았다. 초기 버전은 기록 중 FAIL이 있어도 0으로 종료했으므로 JSON Assertion을 기준으로 집계했다. 최종 스크립트는 해당 단계의 FAIL이 있으면 1로 종료하도록 보강했다. 수정 이후 전체 세션을 새로 실행한 것은 아니다.')

STORY.append(PageBreak())
h('6. 재현·정리', 'cleanup')
p('추가한 파일: tests/docker-compose.e2e.yaml, tests/e2e-proxy.py, tests/full-e2e.py, tests/render-e2e-report.py. Production 소스·개발 Compose 기본 파일은 이번 실행에서 변경하지 않았다. 기존 미커밋 변경은 유지했다.')
p('PowerShell에서 C:\\moaje\\moaje-infra로 이동한 뒤 다음 설정으로 실행한다. .env의 기존 로컬 인증 설정을 읽되 실제 비밀값을 보고서에 넣지 않는다.')
for command in [
    "$env:MOAJE_STACK_PREFIX='moaje-e2e-20261010'",
    "$env:MOAJE_GRPC_CERTS_DIR='./.local/e2e-20261010/certs'",
    'docker compose -p moaje-e2e-20261010 -f docker-compose.yaml -f tests/docker-compose.e2e.yaml --profile apps up -d --build --wait --wait-timeout 240',
    'docker cp tests/full-e2e.py moaje-e2e-20261010-work:/tmp/full-e2e.py',
    'docker exec -e PYTHONPATH=/app moaje-e2e-20261010-work python /tmp/full-e2e.py normal',
]:
    p(command)
p('송금 결함이 남아 있으면 normal은 중단된다. 이번에는 생성된 사용자 상태를 이용해 independent → verify-consumed → work → auth → extended → multimonth → final → replay → catalog를 분리 실행했다. 시험 스크립트의 각 단계는 앞선 상태에 의존하므로 만능 재실행 명령으로 보지 않는다.')
p('결과·API 목록은 토큰과 계좌번호를 제외한 JSON으로만 로컬 .local에 복사했다. 테스트 JWT·Mock 토큰은 컨테이너 /tmp에만 있었으며 컨테이너 삭제로 제거했다. Kafka 테스트 메시지도 테스트 Kafka 볼륨 삭제로 제거했다.')
p('정리 명령: docker compose -p moaje-e2e-20261010 -f docker-compose.yaml -f tests/docker-compose.e2e.yaml --profile apps down --volumes --remove-orphans')
p('위 명령은 종료 코드 0으로 완료했고 테스트 볼륨 7개·전용 네트워크·컨테이너가 삭제됐다. 기존 moaje-infra 및 다른 프로젝트는 대상에 포함하지 않았다. PDF와 비밀값 없는 결과 JSON은 남긴다.')
p('다음 순서: Banking Controller의 인증값 바인딩과 Auth 계좌 토큰 권한 계약 수정 → 빈 격리 환경에서 정상 송금 재검증 → 동시성/Outbox/Timeout/DLT/복구 시험 → 동일 보고서 형식으로 재시험 결과 추가. 수정은 별도 승인 후 진행한다.')

STORY.append(PageBreak())
h('7. 실행 API 목록', 'api')
p('실행 컨테이너의 OpenAPI를 읽어 확인했다. Auth 내부 /api/auth는 Gateway /api/v1/auth로 변환된다. 명세 조회 성공이 모든 입력·보안·장애 경로의 검증 완료를 뜻하지 않는다. health·운영 API도 포함한다.')
for name, endpoints in catalog.items():
    STORY.append(para(f'{name} | 등록 {len(endpoints)}개', H2))
    table(['Method', '경로', '명세 설명'], [[e['method'], e['path'], e['summary']] for e in endpoints], [47, 284, 180])

STORY.append(PageBreak())
h('8. 개별 검증 기록', 'records')
p('실행 순서대로 기록했다. FAIL은 제품 결함, TEST_ERROR는 시험 코드·데이터 문제, BLOCKED는 선행 실패로 인한 중단이다. 같은 기능 재시험과 부가 Assertion도 각각 기록되어 있다. 사용자 ID는 테스트에서 생성한 가짜 ID다.')
for i, row in enumerate(rows, 1):
    status_color = '#A12B32' if row['status'] == 'FAIL' else '#27604A' if row['status'] == 'PASS' else '#725A20'
    label = f"{i:03d} [{row['status']}] {row['name']}"
    title = Paragraph(f'<font color="{status_color}">{escape(label)}</font>', H2)
    detail = para(row['detail'], SMALL)
    STORY.append(KeepTogether([title, detail, Spacer(1, 4)]))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('KR', 8)
    canvas.setFillColor(colors.HexColor('#657580'))
    canvas.drawString(42, 24, 'MOAJE | 격리 통합 테스트 결과 | 2026-10-10')
    canvas.drawRightString(A4[0] - 42, 24, str(doc.page))
    canvas.restoreState()


doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=42, rightMargin=42, topMargin=42, bottomMargin=43,
                        title='MOAJE 종합 통합 테스트 결과', author='MOAJE 테스트 기록')
doc.build(STORY, onFirstPage=footer, onLaterPages=footer)
print(OUT)
print(dict(counts))
