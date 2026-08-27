"""md-phase ops: MdOp = Callable[[dict (AST), Ctx], list[Finding]].

Whole-AST transforms, mutating in place. Ticket 02: ValidateAnchors.
Ticket 03: SetHeadingNumber + SubstituteGlobalVar — numbering executes here,
pre-pandoc (ToolSpec Q11). Ticket 04: NumberCaptions — strips stale caption
numbers, renumbers from the walker's counters and moves each caption to its
EnvSpec placement; registered after SetHeadingNumber (ToolSpec §6 order).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from snippet_docx.anchors import parse_anchors, validate_anchors
from snippet_docx.findings import Finding
from snippet_docx.pandoc_ast import blocks, inline_code_spans, make_para, plain_text

if TYPE_CHECKING:
    from snippet_docx.pipeline import Ctx
    from snippet_docx.walker import NodeInfo

MdOp = Callable[[dict, "Ctx"], list[Finding]]

# a stale caption number: `4.3-7`, `2.2.3-12`, `A.2-1` (appendix prefixes)
_STALE_NUMBER = re.compile(r"[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*-\d+")


def _caption_body(text: str, label: str) -> str:
    """Caption text with any stale number token dropped (``表 4.3-7 电量表``
    -> ``电量表``); numberless captions (``表 电量表``) pass through."""
    rest = text.removeprefix(label)
    parts = rest.strip().split(None, 1)
    if parts and _STALE_NUMBER.fullmatch(parts[0]):
        return parts[1].strip() if len(parts) > 1 else ""
    return rest.strip()


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
        return validate_anchors(anchors, ast, ctx.strategy)


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


class NumberCaptions:
    """Renumber caption paragraphs from the walker's per-(env, section)
    counters and move each to its EnvSpec placement (ToolSpec §3: captions
    are plain paragraphs, not anchors).

    Stale numbers (``表 4.3-7 电量表``) are silently replaced — the walker
    already counted the caption regardless of its old number. Each caption
    lands immediately above its env's table / below its image no matter
    where the author typed it inside the env, and ``ctx.annotations`` is
    re-synced so later ops still see one NodeInfo per block.
    """

    def __call__(self, ast: dict, ctx: Ctx) -> list[Finding]:
        bs = blocks(ast)
        nodes = ctx.annotations or []
        for node in nodes:
            if node.kind != "caption" or node.caption_index is None:
                continue
            spec = ctx.strategy.envs.get(node.caption_env or "")
            block = bs[node.index] if 0 <= node.index < len(bs) else None
            if spec is None or block is None or block.get("t") != "Para":
                continue
            body = _caption_body(plain_text(block.get("c") or []), spec.label)
            depth = min(spec.caption_max_depth, ctx.config.caption_max_depth)
            block["c"] = make_para(ctx.strategy.format_caption(
                spec, node.section_path[:depth], node.caption_index, body))["c"]
        self._move_to_placement(bs, nodes, ctx)
        return []

    def _move_to_placement(self, bs: list[dict], nodes: list[NodeInfo],
                           ctx: Ctx) -> None:
        spans: list[tuple[str, NodeInfo, NodeInfo]] = []
        stack: list[tuple[str, NodeInfo]] = []
        for node in nodes:
            anchor = node.anchor
            if anchor is None:
                continue
            if anchor.kind == "begin":
                stack.append((anchor.env or "", node))
            elif anchor.kind == "end" and stack and stack[-1][0] == anchor.env:
                # inner envs close first: spans order innermost-before-outer
                spans.append((*stack.pop(), node))
        for env, begin, end in spans:
            spec = ctx.strategy.envs.get(env)
            if spec is None or not spec.numbered:
                continue
            inside = [n for n in nodes if begin.index < n.index < end.index]
            captions = sorted((n for n in inside
                               if n.kind == "caption" and n.caption_env == env),
                              key=lambda n: n.index)
            if not captions:
                continue  # captionless-env warning comes from ValidateAnchors
            content = next((n for n in inside
                            if n.kind in ("table", "image_para")), None)
            if content is None:
                continue  # nothing to place against; leave the caption put
            idxs = [n.index for n in captions]
            moved = [(node, bs[i]) for node, i in zip(captions, idxs)]
            for i in reversed(idxs):
                bs.pop(i)
                nodes.pop(i)
            target = content.index - sum(1 for i in idxs if i < content.index)
            at = target + 1 if spec.caption_placement == "below" else target
            for offset, (node, block) in enumerate(moved):
                bs.insert(at + offset, block)
                nodes.insert(at + offset, node)
            for position, node in enumerate(nodes):
                node.index = position  # keep annotations parallel to blocks


def ecepdi_md_ops() -> list[MdOp]:
    """md_number phase ops for ecepdi (ToolSpec §6 order)."""
    return [ValidateAnchors(), SetHeadingNumber(), NumberCaptions(), SubstituteGlobalVar()]
