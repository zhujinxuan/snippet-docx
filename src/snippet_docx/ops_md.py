"""Markdown ops: validation, heading numbering and global-var substitution.

Caption title selection is shared with polish; caption numbering and placement
are exclusively DOCX operations.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from snippet_docx.anchors import parse_anchors, validate_anchors
from snippet_docx.captions import HEADING_CONTEXT
from snippet_docx.findings import Finding
from snippet_docx.pandoc_ast import blocks, inline_code_spans

if TYPE_CHECKING:
    from snippet_docx.pipeline import Ctx
    from snippet_docx.walker import NodeInfo

MdOp = Callable[[dict, "Ctx"], list[Finding]]


def _by_index(annotations: list[NodeInfo] | None) -> dict[int, NodeInfo]:
    """Block index -> annotation (the walker emits one NodeInfo per block)."""
    return {node.index: node for node in (annotations or [])}


class ValidateAnchors:
    """Parse anchors from the AST and validate against the strategy registries.

    Collects every finding in one pass; error-severity findings stop the
    pipeline before any output is written (enforced by pipeline.draft).
    """

    def __call__(self, ast: dict, ctx: Ctx) -> list[Finding]:
        anchors = parse_anchors(ast, ctx.config.anchor_prefix)
        return validate_anchors(anchors, ast, ctx.strategy, check_captions=False)


class SetHeadingNumber:
    """Bake the walker-computed section number into heading text (ToolSpec
    Q5: literal text, no Word numPr) and rewrite the header level to the doc
    level so pandoc emits ``Heading N`` at the right level.

    Walker findings (cross-subsection, heading-too-deep) are lifted by the
    pipeline right after the walk; ops never re-report them.
    """

    def __call__(self, ast: dict, ctx: Ctx) -> list[Finding]:
        nodes = _by_index(ctx.annotations)
        for index, block in enumerate(blocks(ast)):
            if block.get("t") != "Header":
                continue
            node = nodes.get(index)
            if node is None or node.kind != "heading":
                continue
            block["c"][0] = node.doc_level
            attributes = block["c"][1][2]
            attributes[:] = [(key, value) for key, value in attributes
                             if key != HEADING_CONTEXT]
            attributes.append((HEADING_CONTEXT, json.dumps(node.section_path)))
            number = ctx.strategy.format_section(node.section_path)
            inlines = block["c"][2]
            head: list[dict] = [{"t": "Str", "c": number}]
            if inlines:
                head.append({"t": "Space"})
            block["c"][2] = head + inlines
        return []


class SubstituteGlobalVar:
    """Replace inline ``anchor:<name>`` spans with the resolved value at the
    CURRENT point of the walk (e.g. ``anchor:section`` -> ``2.2.3``).

    Substitution is md-side (ToolSpec §3): the span never reaches the DOCX.
    Unknown names stay put — ValidateAnchors has already errored on them.
    """

    def __call__(self, ast: dict, ctx: Ctx) -> list[Finding]:
        nodes = _by_index(ctx.annotations)
        prefix = ctx.config.anchor_prefix
        for index, block in enumerate(blocks(ast)):
            if block.get("t") != "Para":
                continue
            node = nodes.get(index)
            if node is None:
                continue
            for elem, payload in inline_code_spans(block, prefix):
                resolver = ctx.strategy.global_vars.get(payload)
                if resolver is None:
                    continue
                value = resolver(node)  # NodeInfo satisfies NumberingState
                elem["t"] = "Str"
                elem["c"] = value
        return []


def ecepdi_md_ops() -> list[MdOp]:
    """md_number phase ops for ecepdi (ToolSpec §6 order)."""
    return [ValidateAnchors(), SetHeadingNumber(), SubstituteGlobalVar()]
