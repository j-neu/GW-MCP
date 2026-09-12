"""Thin wrapper — calls groundwater_mcp.index_builder.main().

Run directly:
    python scripts/build_index.py [--token TOKEN] [--quiet]

Or via the installed CLI:
    groundwater-mcp build-index [--token TOKEN] [--quiet]
"""

from groundwater_mcp.index_builder import main

if __name__ == "__main__":
    main()
