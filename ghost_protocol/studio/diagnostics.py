"""Diagnostic detail without credentials, exception locals, or URL secrets."""
import os
import re
import traceback


def safe_message(value):
    text = str(value)
    for name, secret in os.environ.items():
        if len(secret) >= 8 and re.search(r'KEY|TOKEN|SECRET|PASSWORD', name, re.I):
            text = text.replace(secret, '[redacted]')
    text = re.sub(r'(?i)(https?://[^\s?]+)\?[^\s]*', r'\1?[redacted]', text)
    text = re.sub(r'(?i)((?:api[_-]?key|token|password|authorization|cookie)\s*[:=]\s*)[^\s,;]+', r'\1[redacted]', text)
    return text


def exception_detail(exc):
    # No locals or source lines: these may contain request credentials.
    frames = traceback.extract_tb(exc.__traceback__)
    return {'type':type(exc).__name__, 'message':safe_message(exc),
            'frames':[{'file':f.filename, 'line':f.lineno, 'function':f.name} for f in frames]}
