"""Browser-only usability fixture. No real adapter, credentials, or production DB.

Run with Streamlit on a separate loopback port; data lives in a new temp folder.
"""
from pathlib import Path
import os
import sys
import tempfile

import streamlit as st

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ghost_protocol.studio import ui
from ghost_protocol.studio.service import StudioService


class OfflineBackend:
    def collect(self, *args):
        raise ValueError('UI 검증용: 외부 수집 차단')

    def stored(self, *args):
        raise ValueError('UI 검증용: 운영 DB 접근 차단')

    def analyze(self, work, model, meter):
        return {'summary':'UI 검증용 합성 분석: 달의 명암 경계 관찰',
                'hot_topics':['달의 명암 경계'], 'generation_guidance':'입력한 관측 장면만 짧게 쓴다.'}

    def generate(self, work, model, tone, topic, rules, meter):
        return {'title':'UI 검증용 원고 · 달의 경계', 'content':'밝은 면과 어두운 면의 경계가 보임'}


@st.cache_resource
def sandbox_service(_directory):
    name = os.getenv('GHOST_STUDIO_SANDBOX_NAME','')
    if name:
        if not name.startswith('ghost-studio-usability-') or Path(name).name != name:
            raise ValueError('Only a named usability fixture inside the temp directory is allowed.')
        directory = str(Path(tempfile.gettempdir())/name)
    else:
        directory = tempfile.mkdtemp(prefix='ghost-studio-usability-')
    service = StudioService(directory,OfflineBackend())
    service.import_benchmark()
    print('UI_SANDBOX_DIRECTORY='+directory,flush=True)
    return service


ui.get_service = sandbox_service
ui.render_studio()
