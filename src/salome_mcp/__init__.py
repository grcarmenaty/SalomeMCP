"""SalomeMCP: an MCP server for building Salome structures."""
from salome_mcp.session import Session
from salome_mcp.runner import SalomeRunResult, find_salome, run_script

__all__ = ["Session", "SalomeRunResult", "find_salome", "run_script"]
__version__ = "0.1.0"
