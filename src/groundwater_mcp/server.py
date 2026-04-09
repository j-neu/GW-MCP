"""groundwater-mcp — MCP server entrypoint.

Initialises the MCP app and registers all tool modules.
Run via: groundwater-mcp serve
"""

from mcp.server.fastmcp import FastMCP

from groundwater_mcp.tools import (
    builder,
    calibration,
    docs,
    parameterise,
    postprocess,
    runner,
)

mcp = FastMCP(
    name="groundwater-mcp",
    instructions=(
        "You are connected to a local groundwater modelling stack. "
        "Use the available tools to build MODFLOW 6 models from spatial data, "
        "run simulations, post-process results, and calibrate parameters."
    ),
)

# Register all tool modules
docs.register(mcp)
parameterise.register(mcp)
builder.register(mcp)
runner.register(mcp)
postprocess.register(mcp)
calibration.register(mcp)


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
