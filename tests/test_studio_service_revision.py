from pathlib import Path

from ghost_protocol.studio.ui import service_dependency_revision


def test_service_dependency_revision_changes_when_collector_changes(tmp_path: Path):
    dependency = tmp_path / 'collector.py'
    dependency.write_text('version = 1\n', encoding='utf-8')
    before = service_dependency_revision([dependency])

    dependency.write_text('version = 2\n', encoding='utf-8')

    assert service_dependency_revision([dependency]) != before
