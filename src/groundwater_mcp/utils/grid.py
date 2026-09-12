"""DIS / DISV grid-package resolution for MODFLOW 6 GWF models.

FloPy's ``gwf.get_package(name)`` falls back to a *partial* package-type match
when the exact type is not found: it truncates each package's type to
``len(name)`` characters and compares. On a DISV model the package type is
``"disv"``, so ``get_package("dis")`` truncates it to ``"dis"`` and returns the
``ModflowGwfdisv`` object. Any code that branched on ``if dis is not None``
therefore silently took the structured-DIS path on an unstructured grid and
then dereferenced the non-existent ``nrow``/``ncol``.

These helpers return a package only when it is actually of the requested grid
type, so ``get_dis(gwf)`` is ``None`` on a DISV model (and vice-versa).
"""

from __future__ import annotations

import flopy.mf6 as mf6


def get_dis(gwf):
    """Return the GWF's structured DIS package, or None on a DISV model."""
    pkg = gwf.get_package("dis")
    return pkg if isinstance(pkg, mf6.ModflowGwfdis) else None


def get_disv(gwf):
    """Return the GWF's unstructured DISV package, or None on a DIS model."""
    pkg = gwf.get_package("disv")
    return pkg if isinstance(pkg, mf6.ModflowGwfdisv) else None


def get_grid_packages(gwf):
    """Return ``(dis, disv)`` — at most one is not None."""
    return get_dis(gwf), get_disv(gwf)


def get_grid(gwf):
    """Return the model's grid package regardless of discretisation type."""
    dis = get_dis(gwf)
    return dis if dis is not None else get_disv(gwf)
