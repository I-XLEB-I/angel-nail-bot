from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alembic_down_revisions_reference_existing_revisions() -> None:
    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    modules = [_load_module(path) for path in sorted(versions_dir.glob("*.py"))]
    revisions = {module.revision for module in modules}

    for module in modules:
        down_revision = getattr(module, "down_revision", None)
        if down_revision is None:
            continue
        if isinstance(down_revision, tuple):
            missing = set(down_revision) - revisions
            assert not missing, f"{module.revision} references missing revisions: {sorted(missing)}"
            continue
        assert down_revision in revisions, (
            f"{module.revision} references missing revision: {down_revision}"
        )
