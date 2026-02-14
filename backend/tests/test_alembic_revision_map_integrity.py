from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_revision_map_integrity() -> None:
    """
    Ensures Alembic can build the revision graph from the repo's migration files.

    This catches production-blocking issues like a missing/incorrect down_revision.
    """
    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert heads, "Expected at least one Alembic head revision"

