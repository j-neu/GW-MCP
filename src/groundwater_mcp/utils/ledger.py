"""ledger.py — provenance ledger for model workspaces (7f-G2).

Every MCP tool call is appended to ``<workspace>/.gwmcp_history.jsonl``: a
timestamp, the tool name, an argument digest, and a one-line description of
the resulting change. Failing calls are recorded with their error code. The
ledger is what lets ``describe_model`` answer "where did every number come
from, and what is unverified?" after the session that built the model ends.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from groundwater_mcp.utils.workspace import resolve_workspace

_LEDGER_FILE = ".gwmcp_history.jsonl"


def _model_name(kwargs: dict) -> str | None:
    """Return the model identity from a tool call's keyword arguments."""
    if "model" in kwargs and kwargs["model"]:
        return str(kwargs["model"])
    if "name" in kwargs and kwargs["name"]:
        return str(kwargs["name"])
    return None


def _args_digest(kwargs: dict) -> str:
    """A short, stable digest of the call arguments (arrays/records truncated)."""

    def _snip(value):
        if isinstance(value, (dict, list)):
            return f"<{type(value).__name__} len={len(value)}>"
        if isinstance(value, float):
            return round(value, 6)
        return value

    try:
        payload = json.dumps(
            {k: _snip(v) for k, v in kwargs.items() if k not in ("stress_period_data",)},
            sort_keys=True,
            default=str,
        )
    except Exception:
        return "<unserialisable>"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def _change_summary(tool_name: str, result) -> str:
    """A one-line, human-readable description of what the call changed."""
    if isinstance(result, (list, tuple)):
        # Tools that return an image content block plus a result dict (7f-I1)
        # pass a list; summarise from the trailing dict if present.
        for item in reversed(result):
            if isinstance(item, dict):
                return _change_summary(tool_name, item)
        return f"{tool_name} returned {len(result)} items"
    if isinstance(result, dict):
        if result.get("error"):
            code = result.get("code", "ERROR")
            msg = str(result.get("message", ""))[:80]
            return f"failed: {code} — {msg}"
        # Pick the most informative per-tool fields.
        if "grid_type" in result:
            return f"built {result['grid_type']} grid ({result.get('ncells')} cells)"
        if "package" in result and "stress_periods" in result:
            return (
                f"added {result['package']} package "
                f"({sum(result['stress_periods'].values())} records)"
            )
        if "package" in result:
            return f"added {result['package']} package"
        if "reach_count" in result:
            return f"imported {result['reach_count']} river reaches"
        if "site_count" in result:
            return f"imported {result['site_count']} observation sites"
        if "convergence" in result:
            return f"ran simulation: {result['convergence']}"
        if "check_passed" in result:
            return f"checked model: {'passed' if result['check_passed'] else 'errors'}"
        if "n_observations" in result:
            return f"wrote PEST control ({result['n_observations']} observations)"
        if "rmse" in result and "n" in result:
            return f"compared to observed: RMSE {result['rmse']:.3g} (n={result['n']})"
        if "written" in result and result.get("written") is False:
            return f"{tool_name} (staged, deferred write)"
        if "written" in result:
            return f"{tool_name} flushed to disk"
        if tool_name == "create_model":
            return f"created model workspace {result.get('workspace', '')}"
        if tool_name == "adopt_model":
            return f"adopted model from {result.get('workspace', '')}"
        if "clone" in tool_name:
            return f"cloned model to {result.get('workspace', '')}"
        if "flushed" in result:
            return f"{tool_name} (flushed={result['flushed']})"
        return f"{tool_name} returned {len(result)} keys"
    return f"{tool_name} returned {type(result).__name__}"


def record_call(tool_name: str, kwargs: dict, result) -> None:
    """Append one ledger line for a tool call, if it identifies a model."""
    model = _model_name(kwargs)
    if model is None:
        return
    try:
        ws = resolve_workspace(model)
    except KeyError:
        # create_model/adopt_model register the workspace during the call, so
        # resolution must succeed for them; anything else that fails here is
        # skipped quietly.
        return
    line = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool": tool_name,
        "args": _args_digest(kwargs),
        "change": _change_summary(tool_name, result),
    }
    path = Path(ws) / _LEDGER_FILE
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def read_records(model: str) -> list[dict]:
    """Return the ledger lines for a model, in call order."""
    path = resolve_workspace(model) / _LEDGER_FILE
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records
