"""수정 후 r3 실행 기록만 읽어 결과를 작성한다. 이전 결과는 섞지 않는다."""
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
PREFIX = ROOT / '.local/e2e-20261010-r3'


def read(suffix):
    return json.loads(Path(str(PREFIX) + '-' + suffix + '.json').read_text(encoding='utf-8-sig'))


rows, baseline, cleanup, images, catalog = [read(x) for x in ['results', 'baseline', 'cleanup', 'images', 'catalog']]
counts = Counter(r['status'] for r in rows)
pdfmetrics.registerFont(TTFont('KR', 'C:/Windows/Fonts/malgun.ttf'))
pdfmetrics.registerFont(TTFont('KRB', 'C:/Windows/Fonts/malgunbd.ttf'))
body = ParagraphStyle('body', fontName='KR', fontSize=9, leading=14, spaceAfter=8, wordWrap='CJK')
small = ParagraphStyle('small', parent=body, fontSize=8, leading=12, spaceAfter=3)
head = ParagraphStyle('head', parent=body, fontName='KRB', fontSize=16, leading=23, spaceAfter=14)
sub = ParagraphStyle('sub', parent=body, fontName='KRB', fontSize=10, leading=15, spaceBefore=9)
story = []


def p(value, style=body):
    return Paragraph(escape(str(value)).replace('\n', '<br/>'), style)


def text(value):
    story.append(p(value))


def heading(title, anchor):
    story.append(Paragraph(f'<a name="{anchor}"/>{escape(title)}', head))


def table(headers, items, widths):
    t = Table([[p(v, small) for v in row] for row in [headers] + items], colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E8EEF2')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#CDD7DE')),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.extend([t, Spacer(1, 10)])


heading('MOAJE 수정 후 통합 재시험', 'summary')
text('2026-10-10 | r3 | email + 6자리 PIN | 격리 Compose 환경')
text('Banking의 미확정 응답 분류와 Asset의 오류 응답을 수정한 뒤, 세 JVM 서비스 이미지를 다시 빌드하여 기존 통합 시나리오를 재실행했다. Auth·Work는 기존 이미지와 코드를 사용했다.')
table(['검증 기록', '건수'], [[k, v] for k, v in counts.items()], [360, 151])
text(f'총 {len(rows)}건은 API 수가 아니라 개별 Assertion 기록 수다. 실패 항목이 같은 결함을 반복 검증할 수 있다. 아래 결과는 이번 실행 기록에서만 생성했다.')
for title, anchor in [('1. 환경과 기준 코드', 'environment'), ('2. 수정 사항 재검증', 'fixed'),
                      ('3. 남은 실패와 시험 한계', 'limits'), ('4. 데이터 정리', 'cleanup'),
                      ('5. 실행 API 명세', 'api'), ('6. 전체 검증 기록', 'records')]:
    story.append(Paragraph(f'<link href="#{anchor}" color="#24617A">{escape(title)}</link>', body))
story.append(PageBreak())
heading('1. 환경과 기준 코드', 'environment')
text('프로젝트 moaje-e2e-20261010-r3, Gateway 127.0.0.1:19080. MySQL 4개·Redis 2개·Kafka 1개의 신규 테스트 볼륨을 사용했다. 기존 개발 스택은 기동하지 않았고 개발 볼륨은 그대로 보존했다.')
text('Banking 대사는 5초 주기, PROCESSING 경과 기준은 120초다. Mock 처리 후 Proxy가 응답을 35초 지연하며 Banking readTimeout은 30초다. Asset 전월 재집계는 시험용 15초 주기다.')
table(['저장소', 'commit / branch', '미커밋 파일'], [[r['repository'], r['commit']+' / '+r['branch'], r['dirtyFiles']] for r in baseline], [130, 290, 91])
text('Mock과 Infra는 미커밋 변경을 포함하므로 commit만으로 실행 소스를 재현할 수 없다. Banking·Asset은 push한 코드로 실행했다. 이미지 빌드는 -x test이며 Asset 단위/JPA 테스트 38건은 빌드 전에 별도로 통과했다. Banking 89건과 Mock 23건은 직전 수정 단계의 결과다.')
table(['실행 이미지', '이미지 ID'], [[r['service'], r['id']] for r in images], [95, 416])
story.append(PageBreak())
heading('2. 수정 사항 재검증', 'fixed')
names = ['타인 계좌 상세 차단', '다른 계좌 거래 ID 차단', 'Mock 성공 후 응답 Timeout', 'Timeout 대사 SUCCEEDED 복구',
         'Timeout 성공 복구 Outbox 발행', 'Timeout 원거래와 Banking 상태 일치', 'Timeout 실제 성공 이벤트 복구 여부',
         '응답 추출 오류 기록 후 대사 성공', '불명확 응답에서 실패 이벤트 미생성', 'Timeout 복구 Asset 거래 1건']
selected = [r for r in rows if r['name'] in names or 'ProblemDetail' in r['name']]
table(['검증', '판정', '실제 관찰'], [[r['name'], r['status'], r['detail']] for r in selected], [140, 45, 326])
text('Timeout 시험은 외부 송금을 다시 요청해서 성공시킨 것이 아니다. Mock이 이미 실행한 거래를 clientTransferId로 조회하여 Banking 상태를 확정하고 Outbox를 발행하는 경로다. 반환 당시 상태와 대사 완료 후 상태는 구분하여 기록했다.')
story.append(PageBreak())
heading('3. 남은 실패와 시험 한계', 'limits')
failures = [r for r in rows if r['status'] == 'FAIL']
table(['실패 기록', '실제 결과'], [[r['name'], r['detail']] for r in failures] or [['없음', '이번에 실행한 조건에서 실패 없음']], [170, 341])
text('Auth 타인 계좌 토큰 발급 실패는 Auth 담당 범위이며, Work 신규 사용자 프로필 실패는 Work 응답의 last_analyzed_at null 허용 문제다. 이번 시험에서는 두 서비스의 소스를 수정하거나 원격 최신화를 하지 않았다. 실제 실패 여부는 위 기록을 기준으로 한다.')
text('ACK 직후 PUBLISHED 저장 전 강제 종료, 여러 Publisher/대사 Worker의 Lease 경쟁, RETRY_EXHAUSTED와 수동 재발행, Consumer DB 장애 및 DLT 발행 실패, 반전거래 정책, 성능·AI 품질은 시험하지 않았다. DLT 복구 대상 지정은 지표로 확인하며 순간적인 SYNC_REQUIRED를 직접 읽은 것은 아니다. 스냅샷 복구는 손상 DLT 본문 자체의 수정·재투입과 다르다.')
text('Banking V6는 이번 신규 MySQL에서 적용 여부를 확인했다. 기존 데이터가 있는 운영 DB의 업그레이드, 과거에 잘못 FAILED로 기록된 거래 복구까지 검증한 것은 아니다. 정상 송금·중복·조회·집계·RPC·Kafka 중단·서버 종료·DLT의 실제 실행 결과는 전체 기록에 남겼다.')
story.append(PageBreak())
heading('4. 데이터 정리', 'cleanup')
table(['정리 항목', '확인 결과'], [[k, str(v)] for k, v in cleanup.items()], [300, 211])
text('시험용 계좌·JWT가 들어 있던 컨테이너 임시 파일과 DB·Redis·Kafka 데이터는 테스트 환경 제거로 삭제했다. 비밀값 없는 검증 결과와 이미지 캐시는 보관했다. 기존 개발 볼륨, 다른 프로젝트 볼륨은 삭제하지 않았다.')
text('재현 도구: tests/docker-compose.e2e.yaml, tests/full-e2e.py, tests/rerun-e2e.py, tests/e2e-proxy.py. 새 -p 이름과 인증서 경로를 사용해야 한다. core → timeout → timeout-audit → fixes → multimonth → replay → fresh-profile → Kafka stop/outage/start/recovered → crash/kill/start/crash-recovered → dlt → final → audit 및 catalog를 실행했다. 서버 kill은 Proxy의 ready_to_kill 확인 뒤 수행했다.')
story.append(PageBreak())
heading('5. 실행 API 명세', 'api')
text('실행 중인 각 서비스의 OpenAPI를 수집했다. 등록 API 목록이며 모든 입력·권한 조합이 시험됐다는 뜻은 아니다.')
for service, endpoints in catalog.items():
    story.append(p(f'{service} | {len(endpoints)}개', sub))
    table(['Method', '경로'], [[r['method'], r['path']] for r in endpoints], [55, 456])
story.append(PageBreak())
heading('6. 전체 검증 기록', 'records')
for i, row in enumerate(rows, 1):
    label = f"{i:03d} [{row['status']}] {row['name']}"
    story.append(KeepTogether([p(label, sub), p(row['detail'], small), Spacer(1, 4)]))


def footer(canvas, doc):
    canvas.setFont('KR', 8)
    canvas.drawString(42, 23, 'MOAJE | 오류 분류·HTTP 응답 수정 후 재시험 | 2026-10-10')
    canvas.drawRightString(A4[0]-42, 23, str(doc.page))


out = ROOT / 'output/pdf/moaje-integration-retest-fixed-20261010.pdf'
out.parent.mkdir(parents=True, exist_ok=True)
SimpleDocTemplate(str(out), pagesize=A4, leftMargin=42, rightMargin=42, topMargin=42, bottomMargin=44,
                  title='MOAJE 수정 후 통합 재시험', author='MOAJE').build(story, onFirstPage=footer, onLaterPages=footer)
print(json.dumps({'path': str(out), 'counts': counts}, ensure_ascii=False))
