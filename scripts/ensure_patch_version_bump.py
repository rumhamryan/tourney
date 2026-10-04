from __future__ import annotations

import re
import subprocess
from pathlib import Path

PYPROJECT_PATH = Path("pyproject.toml")
VERSION_PATTERN = re.compile(r'^(version\s*=\s*")(\d+)\.(\d+)\.(\d+)(")[ \t]*$', re.MULTILINE)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def has_staged_changes() -> bool:
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 1


def read_git_file(pathspec: str) -> str | None:
    result = subprocess.run(
        ["git", "show", pathspec],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    return result.stdout


def read_committed_pyproject() -> str | None:
    return read_git_file("HEAD:pyproject.toml")


def read_staged_pyproject() -> str | None:
    return read_git_file(":pyproject.toml")


def extract_version(content: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.search(content)
    if match is None:
        raise ValueError("Could not find a simple X.Y.Z version in pyproject.toml")
    major, minor, patch = (int(part) for part in match.groups()[1:4])
    return major, minor, patch


def is_version_greater(current: tuple[int, int, int], committed: tuple[int, int, int]) -> bool:
    return current > committed


def bump_patch(version: tuple[int, int, int]) -> tuple[int, int, int]:
    major, minor, patch = version
    return major, minor, patch + 1


def replace_version(content: str, new_version: tuple[int, int, int]) -> str:
    replacement = f"\\g<1>{new_version[0]}.{new_version[1]}.{new_version[2]}\\g<5>"
    updated_content, count = VERSION_PATTERN.subn(replacement, content, count=1)
    if count != 1:
        raise ValueError("Expected to replace exactly one version line in pyproject.toml")
    return updated_content


def ensure_patch_bump(current_content: str, committed_content: str | None) -> tuple[str, bool]:
    if committed_content is None:
        return current_content, False

    current_version = extract_version(current_content)
    committed_version = extract_version(committed_content)
    if is_version_greater(current_version, committed_version):
        return current_content, False

    return replace_version(current_content, bump_patch(current_version)), True


def main() -> int:
    if not PYPROJECT_PATH.exists():
        print("version-bump: pyproject.toml not found; skipping.")
        return 0

    if not has_staged_changes():
        print("version-bump: no staged changes; skipping.")
        return 0

    committed_content = read_committed_pyproject()
    current_content = read_staged_pyproject() or read_text(PYPROJECT_PATH)
    updated_content, modified = ensure_patch_bump(current_content, committed_content)
    if not modified:
        print("version-bump: existing version is already greater than HEAD; leaving it unchanged.")
        return 0

    write_text(PYPROJECT_PATH, updated_content)
    print("version-bump: bumped pyproject.toml patch version. Stage the file and retry the commit.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
