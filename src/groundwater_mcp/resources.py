"""resources.py — MCP resources exposing workspace files as readable URIs
(7e-C7).

Complements the .lst/.pst/file-listing *tools* (get_run_log,
list_model_files) with resource URIs a client can read directly, instead of
round-tripping through a tool call whose whole job is returning a giant
string. Registered as resource *templates* (``{model}`` in the URI) since
models are created at runtime — they surface via
``mcp.list_resource_templates()``, not ``mcp.list_resources()`` (which is
for resources with no variable parts).
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from groundwater_mcp.utils.workspace import resolve_workspace


def _read_lst(model: str) -> str:
    """Return the full text of the model's MODFLOW listing (.lst) file."""
    ws = resolve_workspace(model)
    lst_files = list(ws.glob("*.lst"))
    if not lst_files:
        raise FileNotFoundError(
            f"No listing file (.lst) found in workspace {ws}. "
            "Run the simulation first with run_simulation."
        )
    lst_file = next((f for f in lst_files if f.name == "mfsim.lst"), lst_files[0])
    return lst_file.read_text(errors="replace")


def _read_pst(model: str) -> str:
    """Return the full text of the model's PEST++ control (.pst) file."""
    ws = resolve_workspace(model)
    pst_files = list(ws.glob("*.pst"))
    if not pst_files:
        raise FileNotFoundError(
            f"No PEST control file (.pst) found in workspace {ws}. "
            "Run setup_pest_control or setup_calibration first."
        )
    pst_file = next((f for f in pst_files if f.name == f"{model}.pst"), pst_files[0])
    return pst_file.read_text(errors="replace")


def _read_files(model: str) -> str:
    """Return the workspace's file listing (name/size/type) as JSON text."""
    from groundwater_mcp.tools.builder import _impl_list_model_files

    return json.dumps(_impl_list_model_files(model), indent=2)


def register(mcp: FastMCP) -> None:
    """Register MCP resource templates with the server (7e-C7)."""

    @mcp.resource(
        "gwmcp://models/{model}/lst",
        name="model_listing_file",
        description=(
            "The MODFLOW 6 listing (.lst) file for this model — the full "
            "run log, including the convergence/iteration tables."
        ),
        mime_type="text/plain",
    )
    def model_lst(model: str) -> str:
        return _read_lst(model)

    @mcp.resource(
        "gwmcp://models/{model}/pst",
        name="model_pest_control_file",
        description="The PEST++ control (.pst) file for this model's calibration.",
        mime_type="text/plain",
    )
    def model_pst(model: str) -> str:
        return _read_pst(model)

    @mcp.resource(
        "gwmcp://models/{model}/files",
        name="model_file_listing",
        description="The model workspace's file listing (name, size, extension) as JSON.",
        mime_type="application/json",
    )
    def model_files(model: str) -> str:
        return _read_files(model)
