"""
Tool registration via autodiscovery.

Every sub-package of ``tools`` that exposes a module-level ``register(mcp)``
function IS a tool. ``register_all`` walks this package, imports each tool
package (skipping private ones whose name starts with ``_``) and calls its
``register``. Adding a tool is therefore just dropping a new folder here — no
edit to this file is ever needed.

Discovery is fault-isolated: if a single tool package fails to import or
register (e.g. a typo in a newly added tool), it is logged with its name and
SKIPPED — the rest of the tools and the server keep running.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

from fastmcp import FastMCP

logger = logging.getLogger("vo_mcp.tools")


def register_all(mcp: FastMCP) -> set[str]:
    """Discover and register every tool package under ``tools``.

    Returns the names of the tools that registered successfully. A tool's package
    directory is named after the tool itself, so this doubles as the list of valid
    names for validating ``MCP_ENABLED_TOOLS`` / ``MCP_DISABLED_TOOLS``.
    """
    registered: set[str] = set()
    failed: list[str] = []
    for module_info in pkgutil.iter_modules(__path__):
        name = module_info.name
        # Skip private helpers (_hints, _template) and any loose modules.
        if not module_info.ispkg or name.startswith("_"):
            continue
        try:
            package = importlib.import_module(f"{__name__}.{name}")
            register = getattr(package, "register", None)
            if register is None:
                logger.warning("Tool package '%s' exposes no register(mcp); skipping.", name)
                continue
            register(mcp)
        except Exception:
            # One broken tool must not take down the whole server.
            failed.append(name)
            logger.exception("Failed to load tool '%s'; skipping it (server continues).", name)
            continue
        registered.add(name)
        logger.debug("Registered tool package '%s'.", name)

    if failed:
        logger.warning(
            "Skipped %d tool(s) due to errors: %s", len(failed), ", ".join(sorted(failed))
        )
    return registered
