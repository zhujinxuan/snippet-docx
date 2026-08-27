"""Strategy implementations. Built-in: ecepdi; external packs register via
the ``snippet_docx.strategies`` entry-point group."""

from __future__ import annotations

from snippet_docx.strategies.ecepdi import EcepdiStrategy

__all__ = ["EcepdiStrategy"]
