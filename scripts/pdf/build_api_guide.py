"""API별 요청·응답 필드의 의미를 표로 제공한다. 애플리케이션 코드는 변경하지 않는다."""
import ast
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, CondPageBreak

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((Path(__file__).with_name('api-manifest.json')).read_text(encoding='utf-8'))
APIS = [a for group in ('Auth','Banking','Asset','Work') for a in DATA['apis'] if a['group']==group]
MODELS = DATA['models']

# 최신 Auth 모델을 다시 읽어 이전 이메일 로그인 명세가 섞이지 않게 한다.
auth_root=ROOT.parent/'moaje-auth'
for file in (auth_root/'app/schemas/auth.py',auth_root/'app/schemas/common.py'):
    for cls in ast.parse(file.read_text(encoding='utf-8')).body:
        if not isinstance(cls,ast.ClassDef): continue
        fs=[]
        for node in cls.body:
            if not isinstance(node,ast.AnnAssign): continue
            opts={}
            if isinstance(node.value,ast.Call):
                for kw in node.value.keywords:
                    try: opts[kw.arg]=ast.literal_eval(kw.value)
                    except (ValueError,TypeError): pass
            required=node.value is None or (isinstance(node.value,ast.Call) and bool(node.value.args)
                                            and isinstance(node.value.args[0],ast.Constant)
                                            and node.value.args[0].value is Ellipsis)
            fs.append({'name':node.target.id,'type':ast.unparse(node.annotation),'required':required,'opts':opts})
        MODELS[cls.name]={'fields':fs,'bases':[]}

TOKENS={'access_token':'<ACCESS_TOKEN>','refresh_token':'<REFRESH_TOKEN>',
        'token_type':'bearer','expires_in':1800,'onboarding_completed':False}
ME={'user_id':'123','onboarding_completed':False,'phone_number':'+821000000000',
    'name':'테스트학생','email':'student@example.test'}
AUTH_UPDATES={
    '/register':('회원가입 · 휴대폰 번호 + 6자리 PIN',
                 {'phone_number':'01000000000','name':'테스트학생','pin':'123456','pin_confirm':'123456',
                  'terms_agreed':True,'privacy_agreed':True,'terms_version':'v1','privacy_version':'v1',
                  'email':'student@example.test','device_info':'MOAJE Android test'},
                 dict(TOKENS,user_id='123',phone_number='+821000000000',name='테스트학생'),
                 'AUTH-201-001','회원가입이 완료되었습니다.'),
    '/login':('로그인 · 휴대폰 번호 + 6자리 PIN',
              {'phone_number':'01000000000','pin':'123456','device_info':'MOAJE Android test'},
              TOKENS,'AUTH-200-001','로그인이 완료되었습니다.'),
    '/refresh':('토큰 재발급',{'refresh_token':'<REFRESH_TOKEN>'},
                dict(TOKENS,onboarding_completed=None),'AUTH-200-002','토큰이 재발급되었습니다.'),
}
for a in APIS:
    if a['group']=='Auth':
        tail=a['path'].removeprefix('/api/v1/auth')
        if tail in AUTH_UPDATES:
            title,request,response,code,message=AUTH_UPDATES[tail]
            a.update(title=title,request=request)
            a['response_value'].update(data=response,code=code,message=message)
        elif tail=='/logout':
            a['response_value'].update(message='로그아웃이 완료되었습니다.',data={'message':'ok'})
            a['implementation_note']='현재 서비스 로직은 refresh_token을 필수로 요구함. all_devices=true이면 이 토큰의 사용자에 속한 모든 기기 세션을 폐기.'
    if a.get('operator') or a['id']=='API-22':
        a['operator_policy']=True
        a['audience']='운영자 전용 · 일반 사용자 앱에서 호출하지 않음'
    if a['id']=='API-22':
        a['implementation_note']='운영 정책은 운영자 전용. 현재 코드는 본인 조회를 허용하므로, Work에 운영자 접근 제한 추가가 필요함. 이 문서 수정으로 접근 권한이 바뀌지는 않음.'

new_auth=[
    ('API-47','GET','/me','내 정보 조회',None,'CurrentUserResponse',ME,'AUTH-200-007','사용자 정보 조회가 완료되었습니다.'),
    ('API-48','PATCH','/me','내 정보 수정',{'name':'테스트학생','email':'student@example.test'},'CurrentUserResponse',ME,'AUTH-200-012','회원 정보가 수정되었습니다.'),
    ('API-49','DELETE','/me','회원 탈퇴',{'current_pin':'123456'},'MessageResponse',{'message':'ok'},'AUTH-200-013','회원 탈퇴가 완료되었습니다.'),
    ('API-50','POST','/session/unlock','앱 잠금 해제',{'refresh_token':'<REFRESH_TOKEN>','pin':'123456'},'TokenResponse',TOKENS,'AUTH-200-010','앱 잠금이 해제되었습니다.'),
    ('API-51','POST','/pin/change','PIN 변경',{'current_pin':'123456','new_pin':'654321','new_pin_confirm':'654321'},'MessageResponse',{'message':'ok'},'AUTH-200-011','간편 비밀번호가 변경되었습니다. 다시 로그인해 주세요.'),
]
for ident,method,path,title,request,model,response,code,message in new_auth:
    body={'API-48':'UpdateProfileRequest','API-49':'WithdrawRequest','API-50':'SessionUnlockRequest','API-51':'PinChangeRequest'}.get(ident)
    item={'id':ident,'group':'Auth','method':method,'path':'/api/v1/auth'+path,'title':title,
          'body':body,'params':[],'auth':True,'status':200,'request':request,
          'response':f'ApiResponse[{model}]',
          'response_value':{'success':True,'status':200,'code':code,'message':message,'data':response,
                            'error':None,'traceId':'example-trace-id','timestamp':'2026-10-11T03:00:00Z'}}
    if ident=='API-48':
        item['implementation_note']='name·email 중 한 항목 이상 전송. email을 생략하면 유지, null을 전송하면 삭제. name은 null로 보내면 현재 값을 유지.'
    if ident=='API-50':
        item['auth']=False
        item['implementation_note']='Gateway 공개 경로. Access Token 없이 Refresh Token+6자리 PIN으로 잠금 해제. 응답의 새 Access/Refresh Token으로 기존 값을 교체한다.'
    if ident=='API-51':
        item['implementation_note']='PIN 변경 후 Refresh Token이 폐기됨. 새 PIN으로 다시 로그인.'
    APIS.append(item)
APIS=[a for group in ('Auth','Banking','Asset','Work') for a in APIS if a['group']==group]
pdfmetrics.registerFont(TTFont('KR','C:/Windows/Fonts/malgun.ttf'))
pdfmetrics.registerFont(TTFont('KRB','C:/Windows/Fonts/malgunbd.ttf'))

# 각 설명은 요청 모델, 응답 모델과 응답 조립 코드에 대응한다.
MEANINGS = dict(line.split('|',1) for line in '''
email|선택 이메일 주소. 회원가입·내 정보 수정에 사용하며 로그인은 휴대폰 번호+PIN으로 진행.
pin|숫자 6자리 로그인 PIN. 앞자리 0을 유지하도록 문자열로 전송.
device_info|로그인한 기기를 구분하기 위한 설명. 생략 가능.
user_id|사용자 ID. 본인 조회·요청에서는 로그인한 사용자와 같은 값을 사용.
userId|로그인한 사용자 ID. Banking·Asset 응답에서는 문자열.
success|요청 처리 성공 여부.
status|처리 상태. API에 따라 HTTP 상태 번호 또는 업무 상태 문자열.
code|서버가 정의한 결과 코드. 화면 문구와 별도로 처리 결과를 구분.
message|서버가 제공하는 안내 문구.
data|실제 업무 응답 객체. Auth는 이 객체 안에서 결과를 읽음.
error|오류 정보. 정상 시 null. 오류 시 reason(사유), details(상세 목록), requiredAction(후속 행동)을 포함.
traceId|서버 로그에서 해당 요청을 찾기 위한 추적 ID.
timestamp|서버가 응답을 만든 시각.
is_active|현재 사용 가능한 상태인지 여부.
access_token|인증이 필요한 요청의 Authorization 헤더에 넣을 Access Token.
refresh_token|Access Token 재발급·로그아웃에 사용하는 Refresh Token.
token_type|인증 헤더 방식. bearer이면 Authorization: Bearer 토큰값.
expires_in|Access Token 만료까지 남은 시간. 단위: 초.
expires_at|토큰 만료 시각. Unix 초: 1970-01-01 UTC부터 지난 초.
is_valid|전달한 토큰의 유효성 검사 결과.
account_token|Auth가 발급한 불투명 계좌 토큰. 실제 계좌번호가 아님.
account_number|계좌 토큰을 발급할 대상 계좌번호.
transaction_id|해당 요청·거래를 구분하는 문자열 ID. Work에서는 탐지 대상 거래 ID.
all_devices|true이면 해당 사용자의 모든 기기 세션에서 로그아웃.
ci|Mock 계좌 개설에 전달하는 사용자 식별값.
userName|계좌 개설 요청자의 이름.
phoneNumber|계좌 개설 요청자의 휴대폰 번호.
bankCode|은행 코드 문자열. 앞자리 0 보존. 생성 요청은 공백 불가, 최대 20자.
bankName|계좌 생성 때 지정한 은행 이름. 기존 계좌에서 알 수 없는 값만 null.
productName|계좌 상품 이름.
initialBalance|Mock 계좌를 만들 때 넣을 초기 잔액. 단위: 원.
withdrawalAccountId|돈을 출금할 본인 계좌의 Banking 내부 ID. 수취 계좌 ID가 아님.
depositBankCode|돈을 받을 계좌의 은행 코드.
depositAccountNumber|돈을 받을 계좌번호.
amount|해당 거래·항목의 금액.
currency|금액의 통화 코드. 기본값 KRW.
accountId|계좌 선택·상세·거래내역 조회에 필수인 내부 문자열 ID. 계좌번호와 다름. Number 변환 금지.
accountNumber|본인 소유권 확인 후 개설·상세·Refresh에 제공하는 14자리 전체 계좌번호. 표시·복사·수취용이며 조회·출금 ID로 사용하지 않음.
transferId|Banking 송금의 문자열 ID. Asset 거래내역 ID와 다름. Number 변환 금지.
publicTransferId|사용자 화면에 표시할 송금 번호.
externalTransactionId|Mock Banking이 반환한 외부 거래 번호. 아직 없으면 null.
balance|해당 계좌의 잔액. Asset 응답은 조회용으로 저장된 잔액.
createdAt|항목 생성 시각.
canceledAt|계좌 취소 시각. 취소되지 않았으면 null.
displayAccountNumber|상세 화면 표시용 마스킹 계좌번호. 끝 네 자리만 표시. 아직 확인하지 못한 기존 계좌는 null.
maskedAccountNumber|끝 네 자리만 남긴 계좌번호. 목록·상세 표시용이며 수취 계좌번호로 사용할 수 없음. 확인 전에는 null.
syncStatus|SYNCED=동기화됨, SYNC_REQUIRED=확인 필요, RECONCILING=갱신 중, STALE=최신화 실패.
refreshing|계좌 정보 갱신이 진행 중인지 여부.
refreshFailed|계좌 최신화 실패 상태인지 여부.
lastSyncedAt|계좌 동기화를 마지막으로 완료한 시각. 이력이 없으면 null.
transactionHistory|계좌 상세에 포함되는 거래내역 첫 페이지. 최대 50건.
transactions|조회한 거래내역 페이지. 최대 50건.
nextCursor|다음 요청의 lastTransactionId에 그대로 넣는 문자열 ID. 마지막 페이지는 null.
hasNext|이후에 조회할 거래내역 페이지가 있는지 여부.
lastTransactionId|이전 응답의 nextCursor. 첫 요청에는 이 쿼리 항목을 생략.
transactionId|Asset 거래내역의 문자열 ID. 단건 조회·커서에 사용. Number 변환 금지.
publicTransactionId|사용자 화면에 표시할 거래 번호. 내부 거래내역 ID와 다름.
type|DEPOSIT=입금, WITHDRAW=출금, TRANSFER=송금, REVERSAL=반전거래.
targetAccountId|거래 상대 식별용으로 저장된 targetToken 값. 실제 계좌번호로 해석하지 않음. 없으면 null.
merchantName|가맹점 이름. 개인 간 송금 등 가맹점이 없으면 null.
categoryCode|거래 분류 코드. TRANSFER는 자금이동이며 일반 소비와 구분.
expectedIncome|다음 수입일까지 예상되는 수입 금액. 기본값 0원.
fixedExpenses|계산 기간에 예정된 고정 지출. 기본값 0원.
eventBuffer|학사 일정 등 추가 지출에 대비해 남겨둘 금액. 기본값 0원.
daysUntilNextPayday|다음 수입일까지 남은 일수. 1 이상이어야 함.
snapshotDate|일일 계산의 기준 날짜. YYYY-MM-DD.
forceRefresh|true이면 기존 계산 캐시를 사용하지 않고 다시 계산.
currentBalance|사용자의 ACTIVE 계좌 잔액 합계. 0원도 정상적인 잔액.
dailyLimit|하루 사용 가능 금액. (잔액+예상수입-고정지출-예비비) / 남은 일수.
yearMonth|집계 대상 월. YYYY-MM.
incomeAmount|해당 월의 수입 합계. 단위: 원.
expenseAmount|해당 월의 소비 지출 합계. 단순 자금이동은 제외.
transferAmount|해당 월의 자금이동 합계. 수입·소비와 별도로 표시.
revision|월 집계 수정 버전. 같은 월에 더 높은 버전이 오면 최신 집계.
calculatedAt|집계를 계산한 시각. 거래가 발생한 시각이 아님.
categories|카테고리별 집계 목록.
category|INCOME=수입, FOOD=식비, CAFE=카페, TRANSPORT=교통, CULTURE=문화·여가, SHOPPING=쇼핑·미용, STUDY=교육, HOUSING=주거·통신, TRANSFER=자금이동, OTHER=기타, UNCATEGORIZED=미분류.
id|해당 목록 항목을 구분하는 내부 ID.
name|대학교 이름.
short_name|대학교 약칭.
region|대학교 소재 지역. 정보가 없으면 null.
university_id|학교 목록 응답에서 선택한 학교의 id.
university_name|동기화 대상 대학교 이름.
year|조회·등록 대상 연도.
semester|학기. 1=1학기, 2=2학기.
synced_count|이번 요청에서 동기화한 학사 일정 건수.
schedules|동기화하거나 조회한 학사 일정 목록.
event_type|EXAM=시험, MT=MT, FESTIVAL=축제, VACATION=방학, EMPLOYMENT=취업, SEMESTER_START/END=개강/종강, MIDTERM/FINAL=중간/기말, HOLIDAY=휴일.
event_name|사용자에게 표시할 학사 일정 이름.
start_date|일정 시작 날짜 또는 시작 시각. 예시 형식에 맞춰 해석.
end_date|일정 종료 날짜 또는 종료 시각. 예시 형식에 맞춰 해석.
expected_extra_spend|해당 일정에 예상되는 추가 지출. 단위: 원.
is_auto|true=학교 일정에서 자동 등록, false=사용자가 직접 등록.
merchant|거래 가맹점 이름.
hour|거래가 발생한 시간대. 0~23시.
occurred_at|거래가 실제로 발생한 시각. 생략 가능.
risk_score|이상거래 위험 점수. 값이 클수록 위험도가 높음.
risk_level|LOW=낮음, MEDIUM=중간, HIGH=높음.
reason_code|탐지 결과의 사유 코드.
is_alerted|이 거래에 대해 이상거래 알림을 생성했는지 여부.
is_blocked|해당 사용자가 블랙리스트로 차단되어 있는지 여부.
reason|ABNORMAL_AMOUNT=비정상 금액, ABNORMAL_TIME=비정상 시간, RAPID_REPEAT=빠른 반복, MANUAL=수동 등록.
description|블랙리스트 등록 사유 설명.
registered_at|블랙리스트에 등록한 시각.
released_at|블랙리스트 해제 시각. 미해제이면 null.
created_at|Work가 해당 기록을 저장한 시각. 원거래 발생 시각과 다를 수 있음.
total|전체 항목 수 또는 합계. 해당 표의 상위 필드 기준.
unread|해당 사용자의 미확인 알림 전체 건수. limit와 무관.
returned|이번 응답에 포함된 알림 건수. limit의 영향을 받음.
alerts|조회된 이상거래 알림 목록.
is_confirmed|사용자가 알림을 확인했는지 여부.
confirmed_at|알림 확인 시각. 아직 확인하지 않았으면 null.
alert_id|확인 처리할 이상거래 알림의 ID.
safety_score|소비 안전도 점수. API에 따라 만점이 다르므로 상위 항목 설명 참조.
grade|소비 안전도 등급. A=90점 이상, B=75점 이상, C=55점 이상, D=55점 미만.
emoji|안전도 등급에 맞춰 표시할 아이콘 문자.
total_tx|분석 대상 거래 건수.
high_count|HIGH 위험도로 탐지된 거래 건수.
medium_count|MEDIUM 위험도로 탐지된 거래 건수.
period_days|분석 대상 기간의 일수.
total_users|집계 기간에 기능을 사용한 사용자 수.
onboarding_started|온보딩을 시작한 사용자 수.
onboarding_completed|온보딩을 완료한 사용자 수.
completion_rate|온보딩 완료율. 0~1 문자열. 화면에서 100을 곱하면 %.
question_dropoff|문항별 답변 수·이탈률 목록.
answered|해당 문항에 답변한 사용자 수.
dropoff_rate|다음 문항으로 넘어가지 않은 비율. 0~1 문자열.
simulator_users|시뮬레이터를 사용한 사용자 수.
simulator_calls|시뮬레이터 실행 횟수.
simulator_reuse_rate|시뮬레이터를 2회 이상 사용한 사용자 비율. 0~1.
recap_users|Money Recap을 열람한 사용자 수.
recap_views|Money Recap 열람 횟수.
recap_repeat_rate|서로 다른 달의 Recap을 2개 이상 열람한 사용자 비율. 0~1.
is_reliable|분석 결과를 해석하기에 데이터가 충분한지 여부.
note|데이터 부족 등 분석 결과 해석 시 참고할 안내.
warnings|분석 지표를 해석할 때 주의할 사항 목록.
question_no|온보딩 문항 번호. 1~10.
phase|온보딩 문항이 속한 단계 이름.
text|화면에 표시할 질문 문구.
purpose|해당 질문을 하는 목적.
free_text|자유 입력형 문항인지 여부.
options|해당 문항의 선택지 목록.
label|화면에 표시할 항목 이름.
answers|저장할 온보딩 답변 목록. 한 개 이상.
answer_code|선택한 답변 코드. 문항 options의 code 사용. 모르겠으면 UNKNOWN.
answer_text|자유 입력 답변. 사용하지 않으면 null 또는 생략.
answered_count|현재 답변한 문항 수.
total_questions|전체 온보딩 문항 수.
is_completed|온보딩 전체 문항 응답이 완료되었는지 여부.
remaining|아직 답변하지 않은 문항 번호 목록.
unknown_answers|UNKNOWN으로 답한 문항 번호 목록. 계산 시 기본 가정을 적용.
next_question_no|다음에 보여줄 미응답 문항 번호. 완료 시 null.
answer_label|선택한 답변 코드에 대응하는 표시 문구.
answered_at|해당 답변을 저장한 시각.
status_code|온보딩에서 선택한 현재 학생·취업 상태 코드.
housing_type|온보딩에서 선택한 미래 주거 형태 코드.
work_env|온보딩에서 선택한 희망 업무 환경 코드.
value_priority|온보딩에서 선택한 연봉·워라밸 가치 우선순위.
must_keep_category|온보딩에서 선택한 포기하기 어려운 소비 영역.
money_concern|온보딩에서 선택한 돈 관리 고민 코드.
success_image|온보딩에서 선택한 미래 성공 모습 코드.
card_title|미래 카드의 제목. 아직 생성되지 않았으면 null.
card_summary|미래 카드의 요약 문구. 아직 생성되지 않았으면 null.
completed_at|온보딩 완료 시각. 완료 전에는 null.
monthly_income|예상 세후 월수입. 단위: 원.
monthly_housing|예상 월 주거비. 단위: 원.
monthly_living|예상 월 기본 생활비. 단위: 원.
monthly_leisure|예상 월 여가비. 단위: 원.
deposit|독립에 필요한 보증금. 단위: 원.
move_in_cost|독립 시 초기 정착 비용. 단위: 원.
current_asset|현재 자산. 요청에서 생략하면 Work가 Asset에서 조회.
percent|사회인 준비도. 0~100. 금융 자격이 아닌 앱 내부 참고 지표.
level|사회인 준비도 단계. 1~5.
level_label|준비도 단계의 표시 이름.
items|준비도를 평가한 항목별 결과 목록.
key|계산·평가 항목을 구분하는 코드.
weight|해당 준비도 항목의 배점.
score|해당 준비도 항목의 획득 점수. 평가 제외이면 null.
detail|해당 준비도 평가 결과에 대한 설명.
evaluated|평가에 반영한 항목 코드 목록.
excluded|데이터가 없어 평가에서 제외한 항목 코드 목록.
asset_source|INPUT=입력 자산, ASSET_SERVICE=Asset 조회, NOT_LINKED=계좌 미연동·활성계좌 없음, UNAVAILABLE=Asset 조회 실패.
disclaimer|준비도 점수가 앱 내부 참고 지표임을 알리는 안내.
months|Money Recap이 존재하는 월 목록. YYYY-MM, 최신순.
year_month|조회·집계 대상 월. YYYY-MM.
total_income|해당 월의 수입 합계. 단위: 원.
total_expense|해당 월의 소비 지출 합계. 단위: 원.
total_transfer|해당 월의 자금이동 합계. 소비 지출과 구분.
net_saving|해당 월의 수입에서 소비 지출을 뺀 순저축액.
share|전체 소비 지출에서 해당 카테고리가 차지하는 비율. 0~1 문자열.
top_category|가장 비중이 높은 소비 카테고리. 데이터가 부족하면 null 가능.
nickname|데이터가 충분할 때 생성하는 소비패턴 별명. 부족하면 null.
nickname_reason|소비패턴 별명을 붙인 이유. 별명이 없으면 null.
coverage|분석에 사용한 거래 수와 분류 수준.
classified_tx|카테고리가 분류된 거래 건수.
unclassified_share|미분류 거래 비율. 0~1 문자열.
insights|소비 분석에서 얻은 안내·해석 문구 목록.
kind|STATISTIC=통계, DERIVED=계산한 값, ASSUMPTION=가정한 값.
source|계산에 사용한 기준값의 출처.
as_of|기준값이 적용되는 기준 시점.
scope|기준값이 적용되는 지역·대상 등의 범위.
url|기준값의 근거 링크. 링크가 없으면 빈 문자열.
target|목표 달성에 필요한 자금의 구성.
emergency_fund|생활비 등에 대비한 비상자금.
cashflow|시뮬레이션에서 사용하는 월수입·월지출 구성.
income|예상 월수입.
housing|예상 월 주거비.
living|예상 월 기본 생활비.
leisure|예상 월 여가비.
expense|월 주거비·생활비·여가비 합계.
savable|월수입에서 월지출을 뺀 월 저축 가능액.
gap|목표 자금에서 현재 자산을 뺀 부족 금액.
months_to_goal|목표까지 남은 개월 수. 월 저축 가능액이 0 이하이면 null.
progress_rate|목표 대비 현재 자산 비율. 0~1 문자열.
assumed_keys|입력하지 않아 기본 가정값으로 계산한 항목 코드 목록.
baselines|계산에 사용한 기준값과 근거 목록.
advice|시뮬레이션 결과에 대한 조언 문구 목록.
monthly_delta|월 지출 변화량. 음수=절약, 양수=지출 증가.
base_monthly_savable|지출 조정 전 월 저축 가능액.
adjusted_monthly_savable|지출 조정 후 월 저축 가능액.
base_months_to_goal|지출 조정 전 목표까지 남은 개월 수. 계산 불가 시 null.
adjusted_months_to_goal|지출 조정 후 목표까지 남은 개월 수. 계산 불가 시 null.
months_saved|단축된 개월 수. 양수이면 목표 달성이 앞당겨짐. 계산 불가 시 null.
event_buffer|학사 일정 등에 대비해 남겨둘 추가 지출 예비비. 단위: 원.
avg_daily_amount|분석된 하루 평균 소비 금액.
peak_spend_hour|소비가 가장 많이 발생한 시간대. 0~23시.
risk_score_baseline|개인 소비 패턴에 대한 기본 위험 점수.
last_analyzed_at|소비 프로필을 마지막으로 분석한 시각.
period_label|조회한 학기를 화면에 표시할 이름.
period_start|리포트 대상 기간의 시작 날짜.
period_end|리포트 대상 기간의 종료 날짜.
spending|학기 소비 통계 요약.
total_tx_count|현재 소비 프로필의 누적 거래 수. 프로필이 없으면 일별 기록 수를 대신 사용. 학기 거래 건수와 다를 수 있음.
avg_daily_limit|기록된 하루 사용 가능 금액의 평균. 실제 하루 지출 평균과 다름.
peak_spend_date|현재 코드는 일별 평균 Daily Limit가 가장 높은 날짜를 반환. 실제 최대 지출일이 아님.
peak_spend_amount|해당 날짜의 평균 Daily Limit. 실제 지출 금액이 아님.
lowest_spend_date|현재 코드는 일별 평균 Daily Limit가 가장 낮은 날짜를 반환. 실제 최소 지출일이 아님.
lowest_spend_amount|해당 날짜의 평균 Daily Limit. 실제 지출 금액이 아님.
total_log_days|하루 사용 가능 금액 기록이 있는 일수.
daily_limit_compliance_rate|Daily Limit가 0보다 큰 날의 비율. 0~1. 실제 지출 준수율과 다름.
daily_limit_cv|Daily Limit의 변동계수. 값이 작을수록 규칙적. 계산 불가 시 null.
fds|학기 이상거래 탐지 요약.
total_detected|리포트에 집계된 탐지 기록 수.
safety_grade|학기 소비 안전도 등급. A/B/C/D.
top_reason|가장 많이 나타난 이상거래 탐지 사유.
events|학사 일정별 소비 통계 목록.
avg_daily_spend|현재 코드는 일정 기간의 평균 Daily Limit를 반환. 실제 하루 지출 평균이 아님.
total_spend|현재 코드는 일정 기간의 평균 Daily Limit × 일정 일수. 실제 총지출이 아님.
vs_normal_ratio|일정 기간 평균 Daily Limit / 학기 일별 평균 Daily Limit. 실제 소비 배율이 아님.
score_breakdown|학기 리포트 총점의 항목별 구성.
daily_limit_score|하루 사용 가능 금액 관련 점수. 만점 30점.
event_score|학사 일정 대비 점수. 만점 20점.
regularity_score|소비 규칙성 점수. 만점 10점.
overall_grade|학기 리포트 최종 등급. A/B/C/D.
overall_score|학기 리포트 최종 점수. 0~100점.
summary_message|학기 리포트의 한 줄 총평.
badges|사용자에게 표시할 배지 목록.
limit|한 번에 조회할 최대 건수.
offset|목록 앞에서 건너뛸 건수. 첫 페이지는 0.
unread_only|true이면 미확인 알림만 조회.
Authorization|인증 토큰. Bearer 뒤에 로그인으로 받은 Access Token을 입력.
Idempotency-Key|클라이언트가 송금별로 만든 문자열 키. 같은 송금 재시도에는 같은 키 사용.
X-Internal-Token|운영 전용 API의 내부 인증 토큰. 일반 앱에 넣지 않음.
'''.strip().splitlines())
MEANINGS.update({
    'email':'선택 이메일 주소. 현재 휴대폰 기반 회원가입·로그인의 로그인 ID가 아님.',
    'phone_number':'휴대폰 번호. 요청은 010으로 시작하는 11자리 또는 +8210 형식. 응답은 +82 국제 형식.',
    'name':'사용자 이름. 공백만 입력할 수 없음.',
    'pin_confirm':'PIN 확인값. pin과 같은 숫자 6자리 문자열이어야 함.',
    'terms_agreed':'서비스 이용약관 동의. 반드시 true.',
    'privacy_agreed':'개인정보 처리 동의. 반드시 true.',
    'terms_version':'사용자가 동의한 이용약관 버전.',
    'privacy_version':'사용자가 동의한 개인정보 처리방침 버전.',
    'onboarding_completed':'온보딩 완료 여부. true=완료, false=미완료. 토큰 재발급 응답에서는 null이므로 완료 여부를 덮어쓰지 않고 /me에서 확인.',
    'current_pin':'현재 사용 중인 숫자 6자리 PIN.',
    'new_pin':'새로 사용할 숫자 6자리 PIN.',
    'new_pin_confirm':'새 PIN 확인값. new_pin과 같아야 함.',
})

OVERRIDES = {
    'target.total':'보증금+초기 정착 비용+비상자금의 합계. 단위: 원.',
    'score_breakdown.total':'학기 리포트 항목별 점수 합계. 0~100점.',
    'score_breakdown.safety_score':'이상거래 탐지에 따른 안전도 점수. 만점 40점.',
    'fds.safety_score':'학기 리포트에서 사용하는 안전도 점수. 만점 40점.',
    'options[].code':'선택지 코드. 답변 저장 요청의 answer_code로 전송.',
    'categories[].code':'소비 카테고리 코드.',
    'coverage.is_reliable':'false이면 거래 수가 적거나 미분류 비율이 높아 소비 성향 해석이 제한됨.',
    'categories[].amount':'해당 카테고리의 집계 금액. 단위: 원.',
    'events[].period_days':'해당 학사 일정에 포함되는 일수.',
    'event_buffer':'학사 일정 등에 대비한 추가 지출 예비비. 단위: 원.',
}

ST = {
    'title':ParagraphStyle('title',fontName='KRB',fontSize=20,leading=27,spaceAfter=12),
    'section':ParagraphStyle('section',fontName='KRB',fontSize=16,leading=22,spaceAfter=12),
    'api':ParagraphStyle('api',fontName='KRB',fontSize=11,leading=16,spaceBefore=5,spaceAfter=7,keepWithNext=True),
    'cell':ParagraphStyle('cell',fontName='KR',fontSize=8.4,leading=12,wordWrap='CJK'),
    'head':ParagraphStyle('head',fontName='KRB',fontSize=8.5,leading=12,textColor=colors.white,wordWrap='CJK'),
    'small':ParagraphStyle('small',fontName='KR',fontSize=8,leading=12,spaceAfter=5),
}

def P(s,style='cell'):
    return Paragraph(escape(str(s)).replace('\n','<br/>'), ST[style])

def T(rows,widths,caption=None):
    headrows = 1
    content = [[P(x,'head') for x in rows[0]]] + [[P(x) for x in row] for row in rows[1:]]
    if rows[0][0]=='응답 필드명':
        for cells,row in zip(content[1:],rows[1:]):
            if '.' in row[0] and pdfmetrics.stringWidth(row[0],'KR',8.4)>widths[0]-12:
                cells[0]=P(row[0].replace('.', '.\n'))
    commands = [('BACKGROUND',(0,0),(-1,0),colors.HexColor('#28546a'))]
    if caption:
        content.insert(0,[P(caption,'head')]+['']*(len(widths)-1))
        commands += [('SPAN',(0,0),(-1,0)),('BACKGROUND',(0,0),(-1,1),colors.HexColor('#28546a'))]
        headrows = 2
    tab=Table(content,colWidths=widths,repeatRows=headrows,hAlign='LEFT')
    tab.setStyle(TableStyle(commands + [
        ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),
        ('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('GRID',(0,0),(-1,-1),0.35,colors.HexColor('#cdd9e0')),
        ('ROWBACKGROUNDS',(0,headrows),(-1,-1),[colors.white,colors.HexColor('#f1f6f8')]),
    ]))
    return tab

def fields(name):
    m=MODELS.get(name,{})
    return [f for b in m.get('bases',[]) for f in fields(b)] + m.get('fields',[])

def base_type(typ):
    typ=typ.replace(' | None','').replace('Optional[','')
    if typ.endswith(']') and 'list[' not in typ:
        typ=typ[:-1]
    return typ

def typename(typ,value):
    typ=typ.replace('?', ' | None')
    nullable='None' in typ or 'Optional' in typ
    b=base_type(typ)
    if 'list[' in b or isinstance(value,list):
        result='배열'
    elif b in MODELS or isinstance(value,dict):
        result='객체'
    elif b=='Decimal':
        result='금액 문자열'
    elif b in ('int','Long','Int'):
        result='정수'
    elif b in ('bool','Boolean') or isinstance(value,bool):
        result='boolean'
    elif b in ('str','String','date','datetime'):
        result='문자열'
    elif isinstance(value,(int,float)):
        result='숫자'
    else:
        result='문자열'
    return result+(' / null' if nullable or value is None else '')

def meaning(a,path,request=False):
    key=path.split('.')[-1].replace('[]','')
    normal=path.removeprefix('data.').removeprefix('[].')
    if normal in OVERRIDES:
        return OVERRIDES[normal]
    if key=='status' and a['group']=='Banking':
        return ('ACCEPTED=수락, PROCESSING=처리·확인 중, COMPLETED=송금 성공, FAILED=실패, REVERSED=성공 후 반전됨.'
                if a['path'].endswith('/transfers') else '계좌 상태. ACTIVE=사용 가능, CANCELED=취소됨.')
    if key=='bankName' and request:
        return '계좌 생성 필수 은행명. 공백 불가, 최대 100자. 코드·이름의 실제 일치 여부는 별도 검증하지 않음.'
    if key=='status' and a['path']=='/api/v1/assets/accounts':
        return '계좌 상태. ACTIVE=거래 가능, CLOSED=닫힌 계좌. 잔액 동기화 상태와 별개.'
    if key=='status' and a['group']=='Asset':
        return 'PENDING=대기, SUCCESS=성공, CANCELED=취소, UNKNOWN=확인 중, FAILED=실패.'
    if key=='createdAt' and a['group']=='Asset':
        return '외부 거래 발생 시각. 없으면 Asset 저장 시각을 사용.'
    if key=='amount':
        return '거래·집계 금액. 단위: 원. 양수 금액이며 입출금 구분은 type 등 관련 필드로 판단.' if a['group']=='Asset' else '거래 또는 기준 금액. 단위: 원.'
    if key=='safety_score' and 'safety-score' in a['path']:
        return '소비 안전도 점수. 0~100점. 높을수록 안전.'
    if key=='is_reliable' and '/metrics/' in a['path']:
        return '표본이 충분한지 여부. 현재는 사용자 10명 미만이면 false.'
    if key=='total' and '/alerts' in a['path']:
        return '사용자의 전체 알림 건수. limit·unread 필터와 무관.'
    if key=='id':
        if 'universities' in a['path']:
            return '학교 ID. 학사 일정 동기화 요청의 university_id에 사용.'
        return ('알림 ID. 알림 확인 요청의 alert_id에 사용.' if 'alerts' in path else
                '해당 기록의 내부 ID. 계좌·거래 ID와 별개.')
    if key=='code' and a['group']=='Auth':
        return 'Auth 응답 결과 코드. 성공·오류 종류를 구분.'
    if key=='unread' and request:
        return 'true이면 미확인 알림만 조회. 기본값 false.'
    if key not in MEANINGS:
        raise ValueError(f'설명 누락: {a["id"]} {path}')
    return MEANINGS[key]

def value_text(v):
    if isinstance(v,dict): return '하위 필드 참조'
    if isinstance(v,list) and v and isinstance(v[0],dict): return '아래 [] 항목 참조'
    return json.dumps(v,ensure_ascii=False)

def schema_for(a):
    name=a.get('response','')
    if name.startswith('ApiResponse['):
        inner=name[len('ApiResponse['):-1]
        result={f['name']:f['type'] for f in fields('ApiResponse')}
        result['data']=inner+' | None'
        return result
    return {f['name']:f['type'] for f in fields(name.removeprefix('list[').removesuffix(']'))}

NULL_TYPES={
    'maskedAccountNumber':'String?','displayAccountNumber':'String?',
    'bankCode':'String?','bankName':'String?','targetAccountId':'String?',
    'merchantName':'String?','message':'String?','lastSyncedAt':'datetime | None',
    'nextCursor':'String | None','canceledAt':'datetime | None','externalTransactionId':'String?',
}

def response_rows(a):
    rows=[]
    def walk(value,prefix='',schema=None):
        schema=schema or {}
        if isinstance(value,list):
            if not prefix:
                rows.append(('$','배열','응답 본문 자체가 목록. 각 항목은 아래 [] 필드로 구성.','[] 또는 항목 목록'))
            if value and isinstance(value[0],dict):
                walk(value[0],prefix+'[]',schema)
            return
        for key,v in value.items():
            path=f'{prefix}.{key}' if prefix else key
            fallback=NULL_TYPES.get(key,'') if a['group']=='Asset' else {
                'externalTransactionId':'String | None','canceledAt':'datetime | None',
            }.get(key,'')
            typ=schema.get(key,fallback)
            if a['group'] in ('Banking','Asset') and key in ('accountId','transactionId','transferId','nextCursor'):
                typ='String | None' if v is None else 'String'
            if '?' in typ: typ=typ.replace('?',' | None')
            rows.append((path,typename(typ,v),meaning(a,path),value_text(v)))
            if isinstance(v,(dict,list)):
                model=base_type(typ)
                if model.startswith('list['): model=model[5:-1]
                walk(v,path,{f['name']:f['type'] for f in fields(model)})
            elif v is None and base_type(typ)=='CategoryShareResponse':
                start=len(rows)
                walk({'code':'FOOD','label':'식비','amount':'10000','share':'0.5'},path,
                     {f['name']:f['type'] for f in fields('CategoryShareResponse')})
                rows[start:]=[(name,kind,'상위 객체가 있을 때: '+desc,example)
                              for name,kind,desc,example in rows[start:]]
    walk(a['response_value'],'',schema_for(a))
    return rows

def request_rows(a):
    rows=[]
    if a.get('auth') or (a['group']=='Auth' and a['method']=='GET'):
        rows.append(('Authorization','헤더','필수','문자열',MEANINGS['Authorization'],'Bearer <ACCESS_TOKEN>'))
    if a['path'].endswith('/transfers'):
        rows.append(('Idempotency-Key','헤더','필수','문자열',MEANINGS['Idempotency-Key'],'demo-transfer-001'))
    if a.get('operator'):
        rows.append(('X-Internal-Token','헤더','필수','문자열',MEANINGS['X-Internal-Token'],'<INTERNAL_TOKEN>'))
    params=list(a.get('params',[]))
    for key in re.findall(r'\{([^}]+)\}',a['path']):
        if not any(f['name']==key for f in params):
            params.append({'name':key,'where':'Path','required':True,'type':'Long'})
    for f in params:
        if f['where']=='Header': continue
        key=f['name']
        val=f.get('default')
        if val is None:
            val={'user_id':123,'accountId':123,'transactionId':789,'question_no':1,'alert_id':1,
                 'yearMonth':'2026-09','year_month':'2026-09','year':2026,'semester':2,
                 'lastTransactionId':789}.get(key,False if 'bool' in f['type'] else 1)
        if a['group'] in ('Banking','Asset') and key in ('accountId','transactionId','lastTransactionId'):
            val=str(val) if val is not None else val
            f=dict(f,type='String')
        desc=meaning(a,key,True)
        constraints=f.get('opts',{})
        limits=[('최소',constraints.get('ge')),('최대',constraints.get('le'))]
        desc+=''.join(f' {label} {value}.' for label,value in limits if isinstance(value,(int,float)))
        if key=='lastTransactionId': desc=MEANINGS[key]
        rows.append((key,{'Path':'경로','Query':'쿼리'}[f['where']], '필수' if f.get('required') else '선택',
                     typename(f['type'],val),desc,value_text(val)))
    body=a.get('request')
    schema={f['name']:f for f in fields(a.get('body'))}
    def add_body(obj,prefix='',schema=None):
        schema=schema or {}
        for key,v in obj.items():
            path=prefix+'.'+key if prefix else key
            f=schema.get(key,{})
            required=f.get('required',key not in ('currency','expectedIncome','fixedExpenses','eventBuffer','snapshotDate','forceRefresh'))
            if a['group']=='Auth' and a['path'].endswith('/logout') and key=='refresh_token':
                required=True
            desc=meaning(a,path,True)
            if key=='answer_code': desc=MEANINGS[key]
            rows.append((path,'본문','필수' if required else '선택',typename(f.get('type',''),v),desc,value_text(v)))
            if isinstance(v,list) and v and isinstance(v[0],dict):
                model=base_type(f.get('type',''))
                if model.startswith('list['): model=model[5:-1]
                add_body(v[0],path+'[]',{f['name']:f for f in fields(model)})
    if body is not None:
        add_body(body,schema=schema)
        if 'current_asset' in schema and 'current_asset' not in body:
            rows.append(('current_asset','본문','선택','금액 문자열 / null',MEANINGS['current_asset'],'미전송 (Asset 조회)'))
    return rows

# 기존 예시에서 숫자로 표현했던 Auth 검증 응답은 실제 스키마가 문자열이다.
for a in APIS:
    if a['group']=='Auth' and a['path'].endswith('/token/validate'):
        a['response_value']['data']['user_id']='123'
    if a['id']=='API-18':
        a['response_value'][0].update(name='테스트대학교',short_name='테스트대')
    if a['id']=='API-29':
        a['response_value'].update(total_users=10,onboarding_started=10,onboarding_completed=8,
                                   simulator_users=2,simulator_calls=3,recap_users=2,recap_views=3,
                                   is_reliable=True,note='표본 규모를 고려해 지표를 해석합니다.')
        a['response_value']['question_dropoff'][0].update(answered=10)
    if a['id']=='API-38':
        a['response_value']['categories'][0].update(code='CAFE',label='카페/디저트',amount='100000',share='1.0')
    if a['id']=='API-46':
        a['response_value']['fds'].update(total_detected=2,safety_score=29,safety_grade='B')
        a['response_value']['score_breakdown'].update(safety_score=29,daily_limit_score=22,
                                                    event_score=20,regularity_score=10,total=81)
        a['response_value'].update(overall_score=81,overall_grade='B')

story=[P('MOAJE API 요청·응답 명세','title')]
story.append(T([
    ['항목','내용'],
    ['공통 주소','http://localhost:8080 (Gateway 경유)'],
    ['요청 형식','본문이 있으면 Content-Type: application/json. 표의 필드명 그대로 JSON 구성.'],
    ['응답 표 읽기','점(.)은 객체 내부, []는 배열 항목. 예: data.user_id → response.data.user_id.'],
    ['타입·예시','문자열은 따옴표, 숫자는 따옴표 없이 전송. null=값 없음. 금액은 별도 표시가 없으면 원. 예시는 실제 사용자 데이터가 아님.'],
    ['식별자 규칙','Banking·Asset의 accountId·transferId·transactionId·nextCursor는 JSON 문자열. 저장·재전송 때 Number로 변환하지 않음. 금액은 기존 숫자 타입 유지.'],
    ['범위','Auth 13개 · Banking 2개 · Asset 8개 · Work 29개. 블랙리스트 조회·등록·해제와 재방문 지표는 운영자 전용으로 분리. 내부 Mock API 제외.'],
    ['기준','2026-10-14 수정 반영. 계좌 목록·은행명·문자열 ID 계약 추가. Auth·Work는 기존 규격 유지. 정상 응답 중심. 운영 정책과 현재 접근 제한이 다른 부분은 해당 API에 명시.'],
],[95,420]))
story.append(Spacer(1,14))
index=[['모듈','메서드 / API 경로','기능']]
ORDERED=[a for a in APIS if not a.get('operator_policy')]+[a for a in APIS if a.get('operator_policy')]
for a in ORDERED:
    index.append([a['group'],a['method']+' '+a['path'],a['title']+(' [운영자 전용]' if a.get('operator_policy') else '')])
index_table=T(index,[49,295,171])
for i,a in enumerate(ORDERED,1):
    index_table._cellvalues[i][1]=Paragraph(f'<link href="#{a["id"]}" color="#146281">{escape(a["method"]+" "+a["path"])}</link>',ST['cell'])
story.append(index_table)

coverage=[]
for group in ('Auth','Banking','Asset','Work','Work 운영자 전용'):
    is_ops=group=='Work 운영자 전용'
    items=[x for x in APIS if (x.get('operator_policy') if is_ops else x['group']==group and not x.get('operator_policy'))]
    story.extend([PageBreak(),P(group+' API','section')])
    for a in items:
        if a['id']=='API-52':
            story.append(PageBreak())
        story.append(CondPageBreak(170))
        display=a['id']+' · '+a['title']+(' [운영자 전용]' if a.get('operator_policy') else '')
        story.append(Paragraph(f'<a name="{a["id"]}"/>{escape(display)}',ST['api']))
        meta=[
            ['항목','내용'],
            ['메서드 / 경로',a['method']+' '+a['path']],
            ['인증','JWT + 운영용 내부 토큰 (일반 앱 호출용 아님)' if a.get('operator') else
                      'JWT 필요' if a.get('auth') else 'JWT 검증 대상 토큰을 Authorization에 전송' if a['method']=='GET' else 'JWT 불필요'],
            ['정상 HTTP 상태',str(a.get('status',200))],
        ]
        if a.get('audience'): meta.append(['사용 대상',a['audience']])
        if a.get('implementation_note'): meta.append(['현재 구현 / 주의',a['implementation_note']])
        story.append(T(meta,[95,420]))
        story.append(Spacer(1,7))
        req=request_rows(a)
        if req:
            story.append(T([['필드명','위치','필수','타입','의미 / 조건','예시']]+req,
                           [96,31,29,58,187,114],a['id']+' · 요청 데이터'))
        else:
            story.append(T([['요청 데이터','내용'],['추가 입력','요청 본문·경로 변수·쿼리 없음.']], [95,420]))
        if a.get('request') is None:
            story.append(T([['요청 본문','없음']], [95,420]))
        story.append(Spacer(1,7))
        resp=response_rows(a)
        story.append(T([['응답 필드명','타입','의미','예시 값']]+resp,[125,66,209,115],
                       a['id']+' · 응답 데이터 (정상 응답)'))
        coverage.append({'id':a['id'],'response_fields':len(resp),'request_fields':len(req)})
        story.append(Spacer(1,19))

def footer(c,doc):
    c.setFont('KR',8)
    c.setFillColor(colors.HexColor('#617781'))
    c.drawString(40,22,'MOAJE · 프론트엔드 API 명세')
    c.drawRightString(A4[0]-40,22,str(doc.page))

# 끝의 여백만 다음 페이지로 넘어가 빈 페이지가 만들어지는 것을 막는다.
story.pop()
out=ROOT/'output/pdf/moaje-frontend-api-guide-20261011.pdf'
doc=SimpleDocTemplate(str(out),pagesize=A4,leftMargin=40,rightMargin=40,topMargin=35,bottomMargin=43,
                      title='MOAJE API 요청·응답 필드 명세',author='MOAJE')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
(ROOT/'tmp/pdfs/tabular-api-coverage.json').parent.mkdir(parents=True,exist_ok=True)
(ROOT/'tmp/pdfs/tabular-api-coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'API {len(APIS)}개 / 응답 필드 {sum(x["response_fields"] for x in coverage)}개 / {out}')
