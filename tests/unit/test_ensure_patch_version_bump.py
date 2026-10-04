from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def load_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "ensure_patch_version_bump.py"
    spec = importlib.util.spec_from_file_location("ensure_patch_version_bump", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_ensure_patch_bump_updates_patch_when_version_is_unchanged() -> None:
    current = '[project]\nversion = "1.2.3"\n'
    committed = '[project]\nversion = "1.2.3"\n'

    updated, modified = MODULE.ensure_patch_bump(current, committed)

    assert modified is True
    assert updated == '[project]\nversion = "1.2.4"\n'


def test_ensure_patch_bump_leaves_higher_version_unchanged() -> None:
    current = '[project]\nversion = "1.3.0"\n'
    committed = '[project]\nversion = "1.2.9"\n'

    updated, modified = MODULE.ensure_patch_bump(current, committed)

    assert modified is False
    assert updated == current


def test_ensure_patch_bump_skips_when_no_committed_pyproject_exists() -> None:
    current = '[project]\nversion = "1.2.3"\n'

    updated, modified = MODULE.ensure_patch_bump(current, None)

    assert modified is False
    assert updated == current


def test_read_git_file_uses_utf8_decoding(mocker: Any) -> None:
    completed = mocker.Mock(returncode=0, stdout='[project]\nversion = "1.2.3"\n')
    run_mock = mocker.patch.object(MODULE.subprocess, "run", return_value=completed)

    output = MODULE.read_git_file("HEAD:pyproject.toml")

    assert output == '[project]\nversion = "1.2.3"\n'
    run_mock.assert_called_once_with(
        ["git", "show", "HEAD:pyproject.toml"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_main_bumps_patch_version_when_staged_version_matches_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    monkeypatch.setattr(MODULE, "PYPROJECT_PATH", pyproject_path)
    monkeypatch.setattr(MODULE, "has_staged_changes", lambda: True)
    monkeypatch.setattr(
        MODULE, "read_committed_pyproject", lambda: '[project]\nversion = "1.2.3"\n'
    )
    monkeypatch.setattr(MODULE, "read_staged_pyproject", lambda: '[project]\nversion = "1.2.3"\n')

    assert MODULE.main() == 1
    assert pyproject_path.read_text(encoding="utf-8") == '[project]\nversion = "1.2.4"\n'
