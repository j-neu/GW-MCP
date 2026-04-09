"""plotting.py — shared matplotlib helpers for post-processing tools."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import matplotlib
matplotlib.use("Agg")  # non-interactive backend; must be set before pyplot import
import matplotlib.pyplot as plt
from matplotlib.figure import Figure


@contextmanager
def figure(figsize: tuple[float, float] = (10, 8), dpi: int = 150) -> Generator[Figure, None, None]:
    """Context manager that yields a matplotlib Figure and closes it on exit.

    Usage::

        with figure() as fig:
            ax = fig.add_subplot(1, 1, 1)
            ax.plot(...)
            save_figure(fig, output_path)
    """
    fig = plt.figure(figsize=figsize, dpi=dpi)
    try:
        yield fig
    finally:
        plt.close(fig)


def save_figure(fig: Figure, output_path: str | Path | None, workspace: Path) -> str:
    """Save a figure to *output_path* (or a temp file in *workspace*) and return the path.

    Parameters
    ----------
    fig:
        The matplotlib Figure to save.
    output_path:
        Destination path. If None, a temporary PNG file is created inside *workspace*.
    workspace:
        Model workspace directory; used as the parent for auto-generated filenames.

    Returns
    -------
    str
        Absolute path to the saved PNG file.
    """
    if output_path is None:
        fd, path = tempfile.mkstemp(suffix=".png", dir=workspace, prefix="gwmcp_")
        import os
        os.close(fd)
    else:
        path = str(output_path)

    fig.tight_layout()
    fig.savefig(path, dpi=fig.get_dpi(), bbox_inches="tight")
    return str(path)
