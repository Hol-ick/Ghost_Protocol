"""Editorial gates and public price calculations; no UI or network dependencies."""
from decimal import Decimal
import re

MODELS = ('gemini-3.1-flash-lite', 'gemini-2.5-flash')
STAGES = {'source': '자료 준비', 'analysis': '분석 확인', 'draft': '원고 제작', 'review': '비교·수정', 'approval': '게시 승인'}
RATES = {'gemini-2.5-flash': ('0.30','2.50','0.03'), 'gemini-3.1-flash-lite': ('0.25','1.50','0.025')}


def source_ready(source):
    return bool(isinstance(source, dict) and source.get('titles') and
                source.get('source_access', {}).get('status') == 'ok')


def analysis_ready(analysis):
    return bool(analysis and not analysis.get('_parse_error') and analysis.get('summary') not in (None, '', 'N/A'))


def cost(model, usage):
    if not usage or model not in RATES:
        return None
    p, o, c = map(Decimal, RATES[model])
    prompt = int(usage.get('prompt_token_count', 0))
    cache = int(usage.get('cached_content_token_count', 0))
    output = int(usage.get('candidates_token_count', 0)) + int(usage.get('thoughts_token_count', 0))
    if not 0 <= cache <= prompt:
        return None
    return str(((prompt-cache)*p + cache*c + output*o) / Decimal(1_000_000))


def draft_warnings(draft, source):
    text = f"{draft.get('title', '')}\n{draft.get('content', '')}"
    warnings = []
    if draft.get('_parse_error') or not draft.get('title'):
        warnings.append('응답 파싱 실패 또는 제목 없음 — 승인 불가')
    if draft.get('target_comments'):
        warnings.append('요청하지 않은 댓글을 제외했습니다. 원본 응답에서 확인하세요.')
    invented = sorted(set(re.findall(r'\d+(?:\.\d+)?', text)) - set(re.findall(r'\d+(?:\.\d+)?', source)))
    if invented:
        warnings.append('원본에 없는 숫자 확인: ' + ', '.join(invented))
    if re.search(r'나도|내가|방금.*(?:봤|했|닦)|직접.*(?:봤|했)', text):
        warnings.append('직접 경험처럼 읽히는 표현을 확인하세요.')
    if len(draft.get('title', '')) > 35:
        warnings.append('제목이 35자를 넘습니다. 한 줄 반응으로 다듬어 보세요.')
    return warnings
