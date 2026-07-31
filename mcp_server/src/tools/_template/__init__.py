"""
Template tool package — COPY this folder to create a new tool.

The leading underscore in ``_template`` makes autodiscovery SKIP it, so this
folder is never registered as a real tool. See ``tools/README.md`` for the
step-by-step guide.
"""

from .tool import register

__all__ = ["register"]
