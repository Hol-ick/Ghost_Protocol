"""Read-only navigation decisions, independent of command history and widgets."""
from .policy import analysis_ready
from .opinion_packet import is_board_collection


def is_approved(draft):
    return (draft.get('approved_revision') == draft['revision']
            and not draft.get('failed') and not draft.get('stale_source'))


def resume_step(work):
    current = [d for d in work['drafts'] if not d.get('stale_source')]
    # Historical benchmark drafts remain reviewable, but cannot become a
    # source for a new Studio generation.
    if current:
        return 'approval' if all(is_approved(d) for d in current) else 'review'
    if not is_board_collection(work['source']):
        return 'source'
    if not analysis_ready(work['analysis']) or not work['analysis'].get('confirmed'):
        return 'analysis'
    return 'draft'
