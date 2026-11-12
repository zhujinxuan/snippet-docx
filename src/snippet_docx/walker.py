"""Shared section walker and exactly-once, per-env caption counters.

Caption source selection lives in captions.py. Draft only bakes headings;
polish uses these same annotations to format and position the chosen titles.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from snippet_docx.anchors import Anchor, parse_anchors
from snippet_docx.captions import (
    HEADING_CONTEXT,
    caption_scope,
    discover_captions,
    has_image,
)
from snippet_docx.findings import Finding
from snippet_docx.pandoc_ast import blocks

if TYPE_CHECKING:
    from snippet_docx.config import Config
    from snippet_docx.strategy import Strategy

NodeKind = Literal["heading", "anchor", "caption", "table", "image_para", "block"]

#: house styles define H1–H5 only; deeper headings bake their number but warn
MAX_DOC_LEVEL = 5


@dataclass
class NodeInfo:
    """Per-block annotation; ``index`` is the block's index in the AST."""

    index: int
    kind: NodeKind = "block"
    doc_level: int | None = None                  # heading: len(prefix) + hashes - 1
    section_path: tuple[int | str, ...] = ()      # heading: its own; others: enclosing
    anchor: Anchor | None = None                  # first anchor span in this block
    caption_env: str | None = None                # caption: env matched by label prefix
    caption_index: int | None = None              # caption: per-(env, section) ordinal
    env_scope: str | None = None                  # innermost open env at this block
    findings: list[Finding] = field(default_factory=list)


def build_annotations(ast: dict, config: Config, strategy: Strategy) -> list[NodeInfo]:
    """ONE traversal; section counters and per-(env, section) caption
    counters advance exactly once here (§4).

    ``#`` maps to doc level ``len(prefix)``; each extra ``#`` is one level
    deeper. A second heading at root level warns ``cross-subsection``
    (numbering is undefined across a subsection boundary); a heading deeper
    than doc level 5 warns ``heading-too-deep``. Both keep the build going.
    A snippet with no headings numbers captions from the declared prefix
    alone. Malformed anchor pairing is NOT diagnosed here — ValidateAnchors
    owns that; the env stack just tolerates it without crashing.
    """
    severities = strategy.severities()
    prefix = tuple(config.prefix)
    root = len(prefix)

    def warn(code: str, message: str) -> Finding:
        return Finding(code=code, severity=severities.get(code, "warn"), message=message)

    anchors_by_block: dict[int, list[Anchor]] = {}
    for anchor in parse_anchors(ast, config.anchor_prefix):
        anchors_by_block.setdefault(anchor.block_index, []).append(anchor)

    counters: dict[int, int] = {}
    seen_root = False
    explicit_path: tuple[int | str, ...] | None = None

    def current_path() -> tuple[int | str, ...]:
        if explicit_path is not None:
            return explicit_path
        return prefix + tuple(counters[level] for level in sorted(counters))

    caption_counters: dict[tuple[str, tuple[int | str, ...]], int] = {}
    # open env names, innermost last. Captionless-env warnings are
    # ValidateAnchors' job; this stack only drives caption detection and
    # per-block env_scope.
    env_stack: list[str] = []

    sources = {source.source_index: source
               for source in discover_captions(ast, strategy, config.anchor_prefix)
               if source.source_index is not None}

    annotations: list[NodeInfo] = []
    for index, block in enumerate(blocks(ast)):
        node = NodeInfo(index=index)
        if block.get("t") == "Header":
            marker = dict(block["c"][1][2]).get(HEADING_CONTEXT)
            if marker is not None:
                explicit_path = tuple(json.loads(marker))
                node.kind = "heading"
                node.doc_level = block["c"][0]
                node.section_path = explicit_path
                node.env_scope = env_stack[-1] if env_stack else None
                annotations.append(node)
                continue
            explicit_path = None
            doc_level = root + block["c"][0] - 1
            node.kind = "heading"
            node.doc_level = doc_level
            if doc_level == root:
                # the root-level counter is fixed at the declared prefix
                if seen_root:
                    node.findings.append(warn(
                        "cross-subsection",
                        f"heading {strategy.format_section(prefix)!r} at block {index} is a "
                        "second heading at the snippet's root level; numbering behavior "
                        "is undefined across a subsection boundary"))
                seen_root = True
                counters.clear()  # a root heading resets every deeper counter
                node.section_path = prefix
            else:
                # skipped intermediate levels initialize lazily at their start value
                for level in range(root + 1, doc_level):
                    counters.setdefault(level, config.section_start.get(level, 1))
                if doc_level in counters:
                    counters[doc_level] += 1
                else:
                    counters[doc_level] = config.section_start.get(doc_level, 1)
                for level in [lv for lv in counters if lv > doc_level]:
                    del counters[level]  # deeper counters reset below this heading
                node.section_path = current_path()
                if doc_level > MAX_DOC_LEVEL:
                    node.findings.append(warn(
                        "heading-too-deep",
                        f"heading at block {index} maps to doc level {doc_level} "
                        f"(> {MAX_DOC_LEVEL}); house styles define H1-H5 only — the "
                        "number is baked but the paragraph style is undefined"))
            node.env_scope = env_stack[-1] if env_stack else None
        else:
            if index in anchors_by_block:
                node.kind = "anchor"
                node.anchor = anchors_by_block[index][0]
                scope = env_stack[-1] if env_stack else None
                for anchor in anchors_by_block[index]:
                    if anchor.kind == "begin":
                        if anchor.env in strategy.envs:
                            env_stack.append(anchor.env)
                            scope = anchor.env
                    elif anchor.kind == "end":
                        if anchor.env in env_stack:
                            # pop down to the matching env (mismatched nesting
                            # is reported by ValidateAnchors, not here)
                            while env_stack[-1] != anchor.env:
                                env_stack.pop()
                            scope = env_stack.pop()
                        else:
                            scope = anchor.env  # stray end; ValidateAnchors errors
                node.env_scope = scope
            else:
                if block.get("t") == "Table":
                    node.kind = "table"
                elif has_image(block):
                    node.kind = "image_para"
                node.env_scope = env_stack[-1] if env_stack else None
            # An inline global anchor does not stop its enclosing paragraph
            # from being the selected explicit caption.
            source = sources.get(index)
            if source is not None:
                name = source.env
                spec = strategy.envs[name]
                node.kind = "caption"
                node.caption_env = name
                key = (name, caption_scope(spec, current_path(),
                                           config.caption_max_depth))
                start = config.env_start.get(name, 1)
                caption_counters[key] = caption_counters.get(key, start - 1) + 1
                node.caption_index = caption_counters[key]
            node.section_path = current_path()
        annotations.append(node)

    return annotations
