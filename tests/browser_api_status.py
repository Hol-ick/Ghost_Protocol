"""Run via the webapp-testing server helper; never clicks collection or publish."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18519)
    parser.add_argument('--missing', action='store_true')
    args = parser.parse_args()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{args.port}/?legacy=1', wait_until='domcontentloaded')
        if not args.missing:
            page.get_by_role('button', name='최근/관리 열기').click(timeout=30000)
            page.get_by_role('button', name='고급', exact=True).click()
        expected = 'LLM 설정 필요' if args.missing else 'LLM 설정됨'
        page.get_by_text(expected, exact=False).first.wait_for(timeout=45000)
        text = page.locator('body').inner_text()
        assert 'Traceback' not in text, text[-1000:]
        assert 'OLLAMA 연결 안 됨' not in text
        assert not errors, errors
        out = Path('logs') / ('api-ui-missing.png' if args.missing else 'api-ui-configured.png')
        out.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(out), full_page=False)
        print(json.dumps({'status_present': True, 'missing_key_case': args.missing, 'page_errors': errors, 'screenshot': str(out)}))
        browser.close()


if __name__ == '__main__':
    main()
