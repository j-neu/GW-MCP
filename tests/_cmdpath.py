"""Compare a PEST++ model-command token with a filesystem path.

On POSIX the server writes absolute command paths relative to the workspace
(pestpp drops a leading "/" before execv), on Windows it writes them as given;
tests compare the path the token resolves to from the workspace.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_token(token: str, ws: str | Path) -> str:
    token = token.strip('"')
    return os.path.normcase(os.path.normpath(os.path.join(str(ws), token)))


def same_path(token: str, expected: str | Path, ws: str | Path) -> bool:
    return resolve_token(token, ws) == os.path.normcase(os.path.normpath(str(expected)))
