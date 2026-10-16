# Contributing to groundwater-mcp

Thanks for helping. The project is a local-first MCP server for MODFLOW 6 +
PEST++ modelling; contributions that fix wrong answers, close capability gaps
or improve the documentation are all welcome.

## Set up

```bash
git clone https://github.com/j-neu/GW-MCP.git
cd GW-MCP
uv sync --extra dev
uv run get-modflow :      # MODFLOW 6 binary
uv run get-pestpp :       # PEST++ binaries (calibration tests)
```

## Workflow

1. Open an issue first for anything larger than a bug fix.
2. Write the failing test **before** the change and watch it fail for the
   right reason. Bug fixes need a regression test that reproduces the bug.
3. Keep the change minimal; match the surrounding code's style and idiom.
4. Update `tools.md` (tool signature, defaults, error codes) and, for a new
   capability, `research/capability-matrix.md` in the same commit.
5. Run the checks below, then open a pull request.

```bash
uv run pytest                       # full suite (a few minutes)
uv run ruff check src tests
uv run mypy src/
```

## Design rules

- **Fail loudly.** Return a structured error (`{"error": true, "code": ...,
  "message": ..., "suggestion": ...}`) rather than a plausible-looking wrong
  result. A tool that cannot be sure of a value must not guess it.
- **Local-first.** No network calls at run time; all I/O is the local
  filesystem or subprocesses.
- **MODFLOW 6 only.** Legacy MODFLOW-2005/NWT is limited to the read-only
  MT3D-USGS post-processing subsystem.
- **Opt-in for anything destructive or lossy** (e.g. `allow_flatten`,
  `allow_sequential`, `unmatched="nearest"`): the safe behaviour is the default.

## Validation data

The sealed validation pool lives outside this repository
(see `research/holdout-registry.md`). Do not copy holdout data into `tests/`,
fixtures, docs or the search index.
