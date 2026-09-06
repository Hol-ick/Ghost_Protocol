"""Read-only navigation decisions, independent of command history and widgets."""
from .policy import analysis_ready, source_ready


def is_approved(draft):
    return (draft.get('approved_revision') == draft['revision']
            and not draft.get('failed') and not draft.get('stale_source'))


def resume_step(work):
    if not source_ready(work['source']):
        return 'source'
    if not analysis_ready(work['analysis']) or not work['analysis'].get('confirmed'):
        return 'analysis'
    current = [d for d in work['drafts'] if not d.get('stale_source')]
    if not current:
        return 'draft'
    return 'approval' if all(is_approved(d) for d in current) else 'review'
