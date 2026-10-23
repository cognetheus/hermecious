"""Contract: Alembic owns the schema, as one linear, reversible chain."""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

API_ROOT = Path(__file__).resolve().parents[2]


def scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))


def test_application_never_calls_create_all() -> None:
    offenders = [
        str(path.relative_to(API_ROOT))
        for path in (API_ROOT / "app").rglob("*.py")
        if re.search(r"\bcreate_all\s*\(", path.read_text())
    ]
    assert offenders == []


def test_single_head_and_linear_history() -> None:
    script = scripts()
    assert len(script.get_heads()) == 1
    for revision in script.walk_revisions():
        assert not revision.is_merge_point, revision.revision


def test_every_revision_defines_a_downgrade() -> None:
    for revision in scripts().walk_revisions():
        assert callable(getattr(revision.module, "downgrade", None)), revision.revision
