from __future__ import annotations

import json
import pathlib
import sys

from tigger._constants import home_config_dir
from tigger.types import TrustLevel

_DEFAULT_TRUSTED_FILE = home_config_dir() / "trusted_paths.json"


def is_trusted(cwd: pathlib.Path, trusted_file: pathlib.Path) -> bool:
    """Return True if *cwd* or any parent is listed in *trusted_file*.

    A corrupt, empty, or unreadable trust file is treated as untrusted
    (and a warning is emitted to stderr) instead of raising — startup
    must never crash because the user's trust file got truncated or
    chmod'd to 000.
    """
    if not trusted_file.exists():
        return False
    try:
        trusted = json.loads(trusted_file.read_text())
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        print(
            f"[trust] {trusted_file} is unreadable ({exc}); treating as untrusted",
            file=sys.stderr,
        )
        return False
    cwd = cwd.resolve()
    for t in trusted:
        try:
            cwd.relative_to(pathlib.Path(t).resolve())
            return True
        except ValueError:
            continue
    return False


def write_trusted(path: pathlib.Path, trusted_file: pathlib.Path) -> None:
    """Add *path* to *trusted_file* (no-op if already present).

    A corrupt existing trust file is recovered from rather than crashed on:
    we treat it as empty and overwrite with the single new entry.
    """
    trusted_file.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    if trusted_file.exists():
        try:
            existing = json.loads(trusted_file.read_text())
        except (json.JSONDecodeError, ValueError) as exc:
            print(
                f"[trust] {trusted_file} is corrupt ({exc}); rewriting from scratch",
                file=sys.stderr,
            )
            existing = []
    entry = str(path.resolve())
    if entry not in existing:
        existing.append(entry)
    trusted_file.write_text(json.dumps(existing))


def check_trust(
    cwd: pathlib.Path,
    trusted_file: pathlib.Path | None = None,
) -> TrustLevel | None:
    """Return TrustLevel.ALWAYS if *cwd* is already trusted, else None (prompt required)."""
    if trusted_file is None:
        trusted_file = _DEFAULT_TRUSTED_FILE
    if is_trusted(cwd, trusted_file):
        return TrustLevel.ALWAYS
    return None
