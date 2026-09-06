from ghost_protocol.studio.presentation import resume_step


def work(drafts=None, **updates):
    return {'source':{'source_kind':'board_collection','titles':['달'], 'source_access':{'status':'ok'}},
            'analysis':{'summary':'달 관찰', 'confirmed':True},
            'drafts':drafts or [], 'stage':'approval', **updates}


def test_resume_uses_actual_readiness_not_last_approval_command():
    approved = {'revision':1, 'approved_revision':1}
    pending = {'revision':2, 'approved_revision':None}
    assert resume_step(work([approved,pending])) == 'review'
    assert resume_step(work([approved])) == 'approval'
    assert resume_step(work([pending])) == 'review'
    assert resume_step(work()) == 'draft'


def test_resume_respects_source_and_analysis_gates():
    assert resume_step(work(source={})) == 'source'
    assert resume_step(work(analysis={})) == 'analysis'
    assert resume_step(work(analysis={'summary':'달'})) == 'analysis'
    assert resume_step(work(analysis={'summary':'달','confirmed':True,'_parse_error':True})) == 'analysis'
    assert resume_step(work([{'stale_source':True}])) == 'draft'


def test_failed_drafts_are_not_treated_as_approved():
    assert resume_step(work([{'revision':1,'approved_revision':1,'failed':True}])) == 'review'
