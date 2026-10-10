"""재시험의 실제 실행 기록으로 새 PDF를 만든다. 이전 판정은 재사용하지 않는다."""
import json
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf/moaje-integration-test-report-20261010.pdf'
rows = json.loads((ROOT / '.local/e2e-20261010-r2-results.json').read_text(encoding='utf-8'))
catalog = json.loads((ROOT / '.local/e2e-20261010-r2-catalog.json').read_text(encoding='utf-8'))
baseline = json.loads((ROOT / '.local/e2e-20261010-r2-baseline.json').read_text(encoding='utf-8-sig'))
cleanup = json.loads((ROOT / '.local/e2e-20261010-r2-cleanup.json').read_text(encoding='utf-8-sig'))
images = json.loads((ROOT / '.local/e2e-20261010-r2-images.json').read_text(encoding='utf-8-sig'))
for row in rows:
    if row['name'] == '시험 구간 중단 dlt':
        row['status'] = 'TEST_ERROR'
    if row['name'] == 'Timeout 복구 Outbox 발행':
        row['status'] = 'CHECK_ONLY'
        row['detail'] += ' | 초기 Assertion은 Topic을 검사하지 않았다. 후속 검사에서 실패 이벤트 발행으로 확인되어 성공 복구 근거에서 제외한다.'
counts = Counter(r['status'] for r in rows)
pdfmetrics.registerFont(TTFont('KR', 'C:/Windows/Fonts/malgun.ttf'))
pdfmetrics.registerFont(TTFont('KRB', 'C:/Windows/Fonts/malgunbd.ttf'))
pdfmetrics.registerFontFamily('KR', normal='KR', bold='KRB', italic='KR', boldItalic='KRB')
BODY = ParagraphStyle('body', fontName='KR', fontSize=9.3, leading=15, spaceAfter=8, wordWrap='CJK')
SMALL = ParagraphStyle('small', parent=BODY, fontSize=8, leading=12, spaceAfter=3)
TITLE = ParagraphStyle('title', parent=BODY, fontName='KRB', fontSize=23, leading=32, spaceAfter=17)
H1 = ParagraphStyle('h1', parent=BODY, fontName='KRB', fontSize=15, leading=22, spaceAfter=13)
H2 = ParagraphStyle('h2', parent=BODY, fontName='KRB', fontSize=10.5, leading=16, spaceBefore=9, spaceAfter=7)
story = []


def p(text, style=BODY):
    return Paragraph(escape(str(text)).replace('\n', '<br/>'), style)


def text(value):
    story.append(p(value))


def heading(title, anchor):
    story.append(Paragraph(f'<a name="{anchor}"/>' + escape(title), H1))


def table(headers, data, widths, compact=False):
    content = [[p(x, SMALL) for x in headers]] + [[p(x, SMALL) for x in row] for row in data]
    t = Table(content, colWidths=widths, repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E8EEF2')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), .7, colors.HexColor('#93A3AE')),
        ('LINEBELOW', (0, 1), (-1, -1), .25, colors.HexColor('#DCE3E7')),
        ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 4 if compact else 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4 if compact else 6),
    ]))
    story.extend([t, Spacer(1, 10)])


story += [p('MOAJE 종합 통합 테스트', TITLE), p('Banking 인증 수정 후 재시험', H1)]
text('2026년 10월 10일 | email + 6자리 PIN | 별도 Docker Compose 환경')
text('결론: 정상 송금 전체 경로와 Kafka 장애 후 재발행은 통과했다. 그러나 응답 지연 시 Mock은 성공인데 Banking은 FAILED로 남는 문제가 확인되어, 금융 장애 복구까지 통과했다고 볼 수 없다.')
table(['판정', '기록 수', '의미'], [
    ['PASS', counts['PASS'], '해당 HTTP·DB·RPC·Kafka Assertion 통과'],
    ['FAIL', counts['FAIL'], '제품의 기대 동작과 불일치. 아래 4개 원인 그룹으로 구분'],
    ['TEST_ERROR', counts['TEST_ERROR'], '시험용 metrics 노출 누락. 환경 보완 후 DLT 재검증'],
    ['CHECK_ONLY', counts['CHECK_ONLY'], '초기 Outbox 확인은 성공 이벤트 검사가 빠져 복구 근거에서 제외'],
], [75, 60, 376])
text(f'총 {len(rows)}건은 재확인·명세 조회를 포함한 검증 기록 수다. 고유 API 수나 서비스 전체 통과율이 아니다. 이전 PDF는 삭제하고 이번 실행 결과로 새로 작성했다.')
for title, anchor in [('1. 환경과 기준 코드', 'environment'), ('2. 정상 흐름과 검증 결과', 'flow'),
                      ('3. 장애 주입과 복구 결과', 'faults'), ('4. 발견한 문제와 담당 서비스', 'findings'),
                      ('5. 실행하지 않은 시험·시험 한계', 'limits'), ('6. 재현 및 데이터 정리', 'cleanup'),
                      ('7. 실행 API 목록', 'api'), ('8. 개별 검증 기록', 'records')]:
    story.append(Paragraph(f'<link href="#{anchor}" color="#24617A">{escape(title)}</link>', BODY))

story.append(PageBreak())
heading('1. 환경과 기준 코드', 'environment')
text('일반 Compose 이미지 6개를 먼저 빌드한 뒤, 테스트 Compose가 같은 moaje-infra-* 이미지를 참조하도록 했다. 업무 소스·기존 데이터 볼륨은 수정하지 않았다. 테스트 준비·결과 파일만 Infra에 추가·수정했다.')
table(['구분', '설정'], [
    ['격리 이름', 'moaje-e2e-20261010-r2 / Gateway 127.0.0.1:19080'],
    ['독립 데이터', 'MySQL 4개, Redis 2개, Kafka 1개: 테스트 볼륨 7개와 전용 네트워크'],
    ['인증', '실제 Auth 가입·로그인 JWT → Gateway 검증 → 내부 사용자 헤더 → Banking Resolver'],
    ['테스트 전용 설정', 'Banking 대사 5초 주기, PROCESSING stale 기준 120초 유지. Asset 전월 재집계 15초 주기'],
    ['장애 도구', 'Mock 응답을 받은 뒤 35초 지연하는 내부 Proxy. Banking readTimeout 30초'],
    ['운영 관찰', 'DLT 확인을 위해 테스트 Asset의 health·metrics 엔드포인트만 내부에 노출'],
    ['기존 환경', '시작 당시 실행 컨테이너 없음. 기존 moaje-infra 볼륨 7개 보존. 개발 스택은 새로 기동하지 않음'],
], [105, 406])
table(['저장소', 'commit / branch', '미커밋 파일 수'],
      [[r['repository'], r['commit'] + ' / ' + r['branch'], r['dirtyFiles']] for r in baseline], [110, 310, 91])
text('미커밋 변경이 있는 저장소는 commit만으로 실행 소스를 완전히 재현할 수 없다. Infra 수치는 시험 파일 수정이 시작된 뒤 수집한 값이다. Python 앱은 현행 로컬 코드이며, 원격 pull은 하지 않았다.')
table(['이미지', '실행 이미지 ID 앞 24자리'], [[r['service'], r['id'][:31]] for r in images], [120, 391])
text('Dockerfile은 JVM bootJar 빌드에서 -x test를 사용한다. 따라서 이번 통합 빌드로 단위 테스트까지 다시 실행한 것은 아니다. Banking 단위·MVC 테스트 성공은 직전 코드 변경 검증 결과이며 이번 컨테이너 통합 시험과 구분한다.')

story.append(PageBreak())
heading('2. 정상 흐름과 검증 결과', 'flow')
table(['단계', '실제 실행', '확인 결과'], [
    ['1', 'Auth 가입·로그인 → Gateway JWT 검증', '실제 JWT로 송금 요청. 거래 principal_id가 로그인 사용자 ID와 일치'],
    ['2', 'Banking → Mock 송금', '10,000원 송금: Mock 출금계좌 100,000→90,000원 / 수취계좌 0→10,000원'],
    ['3', 'Banking 결과 + Outbox', 'SUCCEEDED와 외부 거래 ID 저장. Outbox PUBLISHED 및 Event ID 확인'],
    ['4', 'Kafka → Asset', '잔액 90,000원 및 banking_transfer_id로 연결된 거래내역 1건 확인'],
    ['5', 'Asset 성공·집계 → Work', '실제 성공 메시지 소비행, 월 지출 121원·자금이동 10,001원 집계 소비 확인'],
    ['6', 'Work → Asset 잔액 RPC', 'mTLS 호출·HTTP 잔액 일치, 시뮬레이터 ASSET_SERVICE 응답 확인'],
], [35, 206, 270])
text('개인 간 송금은 생활 지출에 섞지 않고 TRANSFER로 집계했다. 가맹점 지출은 Mock 공개 출금 API로 121건 만들고 스냅샷으로 가져와 CAFE 121원으로 분류했다.')
table(['기능', '검증 범위'], [
    ['멱등성', '같은 키 재요청 동일 transferId·Mock 추가 호출 없음. 12개 동시 동일 요청: DB 1행·Mock POST 1회'],
    ['충돌·인증', '같은 키 다른 금액/수취계좌 409, 키 누락 400, 무인증 401, 타인 출금계좌 403'],
    ['조회·계산', '거래 페이지 50/50/23건, 중복·누락 없음. 단건 조회, refresh 반복, 일별 캐시, 0일 거절, 미연동 409'],
    ['0원·계좌 상태', '별도 신규 ACTIVE 0원 계좌는 정상 일별 계산. 해지 계좌는 잔액 RPC 합산 제외 및 일별 계산 409'],
    ['다개월 집계', '100만원 전용 계좌에서 3개월 24건 생성, 잔액 539,500원, 재생성 0건. 전월 revision 1→2, Work 지출 153,500원'],
    ['Work HTTP', '온보딩·시뮬레이터·준비도·일정·학기 리포트·Recap·FDS·운영 API 정상/권한 확인. AI 내용의 품질 검증은 아님'],
    ['Auth 세션', '토큰 검증·refresh 교체·기존 refresh 거절·로그아웃 후 refresh 거절. access JWT 즉시 폐기는 검증하지 않음'],
], [90, 421])

story.append(PageBreak())
heading('3. 장애 주입과 복구 결과', 'faults')
table(['시험', '주입 방법', '판정·관찰'], [
    ['Kafka 중단', '테스트 Kafka 컨테이너 stop 후 7원 송금', '금융 성공, Outbox PENDING·실패 횟수 1·nextAttemptAt 보존'],
    ['Kafka 복구', '같은 Kafka 볼륨으로 start', '같은 eventId로 PUBLISHED, 시도 횟수 3. Asset 거래 연결 1건'],
    ['중복 메시지', '실제 Banking/Asset 본문을 그대로 또는 새 eventId로 재발행', 'Consumer offset 처리 후 Asset 잔액·거래 1건 유지, Work 소비행 불변'],
    ['늦은 수정 이벤트', '현재보다 낮은 revision 발행', 'Work revision 2·153,500원 유지'],
    ['본문 손상', 'Protobuf 해석 불가 본문 + 식별 Header', '해당 원본 Offset의 DLT 1건·추적 헤더 확인. 복구 라우팅 지표 1, 후속 refresh 잔액 89,848원·SYNCED 확인'],
    ['정상 PROCESSING', '외부 성공 응답을 지연하는 동안 동일 키 재요청', 'API PROCESSING 반환, Mock 추가 호출 없음. 대사 시도 0 확인'],
    ['프로세스 종료', 'Mock 응답을 받은 Proxy가 대기 중일 때 Banking kill/start', '120초 경과 후 대사 1회로 SUCCEEDED·Outbox PUBLISHED·Asset 거래 1건. 재요청 시 Mock 추가 호출 없음'],
    ['응답 Timeout', 'Mock 성공 후 응답 전송 35초 지연', '실패. Mock SUCCEEDED인데 Banking FAILED·대사 시도 0. 실패 이벤트 발행'],
], [90, 170, 251])
text('응답 Timeout과 프로세스 종료는 서로 다른 시험이다. 전자는 살아 있는 Banking이 예외를 잘못 분류하는지를, 후자는 결과 저장 전 종료된 PROCESSING을 Worker가 복구하는지를 확인한다.')
text('DLT의 순간적인 SYNC_REQUIRED 상태를 직접 읽지는 못했다. 복구 라우팅 지표와 최종 SYNCED·잔액을 확인했다. 스냅샷으로 장부를 복구한 것과 손상된 DLT 본문 자체를 고쳐 재처리한 것은 다르다.')
text('Outbox가 보장하는 것은 Banking DB에 커밋된 이벤트의 재발행이다. Mock 성공을 Banking이 FAILED로 잘못 확정하면 Outbox도 잘못된 실패 이벤트를 안정적으로 전달할 수 있다. Outbox만으로 외부 결과 판정 오류를 해결하지 못한다.')

story.append(PageBreak())
heading('4. 발견한 문제와 담당 서비스', 'findings')
table(['우선순위·담당', '문제와 사용자 영향', '코드 근거·후속 조치'], [
    ['P1 Banking', 'Mock 송금 성공에도 Banking FAILED. reconciliation_required=false·시도 0으로 자동 대사 대상에서 제외. 사용자에게 잘못된 실패 결과를 줄 수 있음',
     'integration/mockbanking/MockBankingApiClient.kt: transferExecute. ResourceAccessException만 TIMEOUT, 일반 RestClientException은 FAILED. 실제 오류는 response 추출·application/octet-stream. 예외 체인과 외부 결과 불명확 정책 보강 필요'],
    ['P1 Auth', '송금인 JWT로 다른 user_id의 계좌 토큰 발급 요청 시 200. 기대는 403',
     'moaje-auth/app/api/auth.py: create_account_token에서 payload.user_id 전달. 위임 API인지 일반 사용자 API인지 계약 확정 후 요청 주체와 소유자 검증 필요'],
    ['P2 Asset', '타인 계좌 상세와 다른 계좌의 거래 ID 요청에 500. 데이터 제공은 차단되나 정상적인 4xx 응답이 아님',
     'account/application/service/AccountDetailServiceImpl.kt: 소유권 require와 거래 없음 IllegalArgumentException. 도메인 예외·HTTP 매핑 필요'],
    ['P2 Work', '집계 전 신규 사용자에게 성공 거래 이벤트 1건 반영 후 소비 프로필 500. 월 집계 이후 프로필은 200',
     'moaje-work/app/schemas/spending.py: last_analyzed_at 필수 datetime / app/services/ai/spending_service.py: None 직렬화. 신규 사용자 응답 규격 보강 필요'],
], [85, 205, 221])
text('원인 확정과 추론 구분: HTTP/DB/Kafka 상태는 실제 관찰이다. Timeout의 세부 내부 예외 발생 순서는 메시지·catch 분기에 근거한 분석이며, 추가 stack trace 또는 재현 단위 테스트로 확인해야 한다. 업무 소스 수정은 이번 시험에서 수행하지 않았다.')

story.append(PageBreak())
heading('5. 실행하지 않은 시험·시험 한계', 'limits')
text('다음 항목은 이번 보고서에서 통과로 주장하지 않는다. 테스트 코드나 관련 기능이 존재한다는 사실도 실행 성공과 다르다.')
table(['미검증', '이유·후속 조건'], [
    ['ACK 직후 PUBLISHED 저장 전 종료', '정확한 종료 지점 주입 미구현. 동일 eventId 중복 재발행 소비는 검증했지만 해당 crash window 자체는 미실행'],
    ['여러 Publisher·대사 Worker 경쟁', '인스턴스 1개 실행. 다중 인스턴스 Lease 배타성과 만료 인계는 별도 시험 필요'],
    ['RETRY_EXHAUSTED·수동 재발행', 'Kafka는 3회 발행 시도 안에 복구. 최대 10회 소진·운영자 재발행은 미실행'],
    ['Consumer 일시 DB 장애·DLT 발행 실패', '손상 본문 DLT 적재는 실행. DB 연결/락 장애 및 DLT 브로커 전송 실패는 별도 시험 필요'],
    ['DLT 잔류·운영 재처리', '손상 본문은 스냅샷 복구와 구분된다. 원본 손상 DLT 레코드 자체를 수정·재투입하는 운영 절차는 미실행'],
    ['거래 순서 완전 통제', '스냅샷·이벤트가 실제로 협력하고 중복을 막는 것은 확인. 두 도착 순서를 각각 강제한 경쟁 시험은 미실행'],
    ['성능·AI·보상', '부하/성능/AI 품질 미측정. 정책상 반전거래 실행 및 SMS 제외. 외부 실제 은행 검증 아님'],
], [150, 361])
text('시험 자체의 수정 이력: 최초 사전 실행에서 /app 모듈 경로 누락으로 일부 구간이 멈췄다. 결과를 별도 preflight JSON에 보존하고 테스트 볼륨을 전부 초기화한 뒤 본 시험을 다시 시작했다. 이 사전 실행은 본 시험 집계에서 제외했다.')
text('DLT 첫 실행은 metrics 엔드포인트 미노출(404)로 후속 검사가 멈췄다. 테스트 Compose에서 내부 metrics만 노출하고 Asset을 재기동해 재검증했다. 최초 DLT 적재 성공과 검사 중단 기록을 모두 유지한다. Timeout 초기 Outbox 검사는 Topic을 보지 않아 성공 복구 근거에서 제외하고, 실제 Topic 재검사 실패를 남겼다.')

story.append(PageBreak())
heading('6. 재현 및 데이터 정리', 'cleanup')
text('재현 시 tests/docker-compose.e2e.yaml과 tests/rerun-e2e.py를 사용한다. 테스트 스크립트는 빈 볼륨을 전제로 하며 각 단계의 순서에 의존한다. 기존 개발 볼륨에 실행하면 안 된다.')
text('기본 이미지 빌드: docker compose --profile apps build banking asset mock-banking auth work gateway')
text('테스트 환경: MOAJE_STACK_PREFIX=moaje-e2e-20261010-r2, MOAJE_GRPC_CERTS_DIR=./.local/e2e-20261010-r2/certs')
text('기동: docker compose -p moaje-e2e-20261010-r2 -f docker-compose.yaml -f tests/docker-compose.e2e.yaml --profile apps up -d --no-build')
text('컨테이너 안에 /tests 스크립트를 복사하고 공통 proto에서 테스트용 Python 클래스를 생성한다. core → timeout → timeout-audit → multimonth → replay → fresh-profile → Kafka stop/outage/start/recovered → crash/kill/start/crash-recovered → dlt → final → audit 순서로 실행하고 catalog도 수집한다. crash는 Proxy의 ready_to_kill 확인 후 Banking을 종료해야 하므로 단순 일괄 실행 스크립트가 아니다.')
text('종료: docker compose -p moaje-e2e-20261010-r2 -f docker-compose.yaml -f tests/docker-compose.e2e.yaml --profile apps down --volumes --remove-orphans')
table(['정리 확인', '실제 결과'], [[k, str(v)] for k, v in cleanup.items()], [230, 281])
text('테스트 토큰·계좌번호가 있던 /tmp 상태 파일은 Work 컨테이너 제거와 함께 삭제했다. PDF·비밀값 없는 검증 JSON·시험 코드는 남겼다. 기존 개발 볼륨과 다른 프로젝트의 볼륨은 삭제하지 않았다. 테스트 이미지 캐시는 데이터 볼륨과 별개이며 재사용을 위해 남긴다.')

story.append(PageBreak())
heading('7. 실행 API 목록', 'api')
text('실행 컨테이너의 OpenAPI를 직접 조회했다. Auth 내부 /api/auth는 Gateway /api/v1/auth에 대응한다. 목록에 있다는 사실은 모든 입력·권한·장애 조합이 검증됐다는 뜻이 아니다. 개별 실행은 다음 절에서 확인한다.')
for service, endpoints in catalog.items():
    story.append(p(f'{service} | 등록 API {len(endpoints)}개', H2))
    table(['Method', '경로', '설명'], [[r['method'], r['path'], r['summary']] for r in endpoints], [45, 295, 171], compact=True)

story.append(PageBreak())
heading('8. 개별 검증 기록', 'records')
text('실행 순서대로 기록했다. 사용자·거래 ID는 격리 환경에서 생성한 시험용 값이다. 개인정보·JWT·계좌번호 원문은 보고서에 넣지 않았다. FAIL 여러 건이 동일 원인을 반복 검증할 수 있으므로 결함 개수와 구분한다.')
for i, row in enumerate(rows, 1):
    color = '#A12B32' if row['status'] == 'FAIL' else '#27604A' if row['status'] == 'PASS' else '#725A20'
    label = f"{i:03d} [{row['status']}] {row['name']}"
    title = Paragraph(f'<font color="{color}">{escape(label)}</font>', H2)
    story.append(KeepTogether([title, p(row['detail'], SMALL), Spacer(1, 3)]))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('KR', 8)
    canvas.setFillColor(colors.HexColor('#657580'))
    canvas.drawString(42, 24, 'MOAJE | 인증 수정 후 격리 통합 재시험 | 2026-10-10')
    canvas.drawRightString(A4[0] - 42, 24, str(doc.page))
    canvas.restoreState()


OUT.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=42, rightMargin=42, topMargin=42, bottomMargin=43,
                        title='MOAJE 통합 테스트 재시험 결과', author='MOAJE 테스트 기록')
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(json.dumps({'pdf': str(OUT), 'counts': dict(counts)}, ensure_ascii=False))
