"""Ghost Protocol local Studio entrypoint; legacy operations are explicitly separate."""
from pathlib import Path
import runpy
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

if st.query_params.get('legacy') == '1':
    runpy.run_path(str(ROOT / 'legacy_app.py'), run_name='__main__')
else:
    from ghost_protocol.studio.ui import render_studio
    render_studio()
