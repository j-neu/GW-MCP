"""groundwater-mcp — MCP server entrypoint.

Initialises the MCP app and registers all tool modules.
Run via: groundwater-mcp serve
"""

import functools
import inspect
import math

from mcp.server.fastmcp import FastMCP

from groundwater_mcp import prompts, resources
from groundwater_mcp.tools import (
    builder,
    calibration,
    docs,
    environment,
    parameterise,
    postprocess,
    runner,
    spec,
)
from groundwater_mcp.utils import ledger

mcp = FastMCP(
    name="groundwater-mcp",
    instructions=(
        "You are connected to a local groundwater modelling stack. "
        "Use the available tools to build MODFLOW 6 models from spatial data, "
        "run simulations, post-process results, and calibrate parameters."
    ),
)


def _sanitise(obj):
    """Replace non-finite floats with ``None`` so tool results are valid JSON.

    NaN/Infinity serialize as bare ``NaN``/``Infinity`` under Python's default
    ``json.dumps`` — invalid strict JSON that some MCP clients reject. Every
    tool result passes through this on the way out (7e-B12). Other object
    types (e.g. the ``Image`` of a plot tool result) pass through untouched.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitise(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitise(v) for v in obj)
    return obj


def _with_ledger(fn):
    """Wrap a tool function so every call is appended to the model's
    provenance ledger (7f-G2.1), including failures. Results are also
    sanitised of non-finite floats before recording/returning (7e-B12)."""

    def _record(tool_name: str, kwargs: dict, result) -> None:
        try:
            ledger.record_call(tool_name, kwargs, result)
        except Exception:
            # The ledger must never break a tool call.
            pass

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            result = _sanitise(await fn(*args, **kwargs))
            _record(fn.__name__, kwargs, result)
            return result

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        result = _sanitise(fn(*args, **kwargs))
        _record(fn.__name__, kwargs, result)
        return result

    return wrapper


def _with_next_steps(fn):
    """Wrap a builder/parameterise tool so its result carries a next_steps
    list (7e-C8) — the missing prerequisites for the model to be runnable,
    so ordering gaps (e.g. add_sto_package needs TDIS, assign_k_from_zones
    needs NPF) surface proactively instead of only as the next call's error.

    Computed from ``builder._compute_model_status`` after the wrapped call
    returns, so it reflects the model's state post-call. A no-op when the
    result isn't a plain dict with a "model" key, or is an error envelope,
    or the status computation itself fails (e.g. delete_model leaves no
    model to inspect) — next_steps is a hint, never a reason to break a call.
    """
    from groundwater_mcp.tools.builder import _compute_model_status

    def _attach(result):
        if not isinstance(result, dict) or result.get("error"):
            return result
        model = result.get("model")
        if not model:
            return result
        try:
            result["next_steps"] = _compute_model_status(model)["next_steps"]
        except Exception:
            pass
        return result

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            return _attach(await fn(*args, **kwargs))

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return _attach(fn(*args, **kwargs))

    return wrapper


# Register all tool modules. Each tool is wrapped so its call is recorded in
# the workspace provenance ledger; builder/parameterise tools additionally
# carry a next_steps hint (7e-C8).
def _register(module, next_steps: bool = False):
    orig_tool = mcp.tool

    def tool(name=None, **tool_kwargs):
        def decorator(fn):
            wrapped = _with_ledger(fn)
            if next_steps:
                wrapped = _with_next_steps(wrapped)
            return orig_tool(name=name, **tool_kwargs)(wrapped)

        return decorator

    mcp.tool = tool  # type: ignore[method-assign,assignment]
    try:
        module.register(mcp)
    finally:
        mcp.tool = orig_tool  # type: ignore[method-assign]


_register(docs)
_register(parameterise, next_steps=True)
_register(builder, next_steps=True)
_register(runner)
_register(postprocess)
_register(calibration)
_register(spec)
_register(environment)

# Prompts and resources are read-only introspection, not model-mutating
# actions, so they aren't routed through the provenance ledger like tools are.
prompts.register(mcp)
resources.register(mcp)


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "build-index":
        # Remove the subcommand so argparse in index_builder sees a clean argv
        sys.argv.pop(1)
        from groundwater_mcp.index_builder import main as build_main

        build_main()
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
