"""SalomeMCP: an MCP server for building Salome structures."""
from salome_mcp.pymodal_bridge import closest_node, load_nodes_json
from salome_mcp.runner import SalomeRunResult, find_salome, run_script
from salome_mcp.session import Session

__all__ = [
    "Session",
    "SalomeRunResult",
    "find_salome",
    "run_script",
    "load_nodes_json",
    "closest_node",
]
__version__ = "0.2.0"
