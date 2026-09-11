"""Numbering walker (tool-owned, ToolSpec §4): ONE AST traversal that owns
the section state machine and every counter.

``build_annotations`` walks the blocks once, advancing the section counters
exactly once per heading — the root-level counter is fixed at the declared
prefix, deeper levels count from ``numbering.sections.start`` (default 1) —
and annotates every block with its enclosing section path. Per-(env,
section) caption counters advance in this same walk: a caption is a plain
Para inside an open env whose text starts with the env's label + space
(ToolSpec §3: captions are NOT anchors — stale numbers are counted here and
stripped by the NumberCaptions op). The strategy contributes only pure
formatting (``format_section`` / ``format_caption``); the state machine is
shared by all strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from snippet_docx.anchors import Anchor, parse_anchors
from snippet_docx.findings import Finding
from snippet_docx.pandoc_ast import blocks, plain_text

if TYPE_CHECKING:
    from snippet_docx.config import Config
    from snippet_docx.strategy import EnvSpec, Strategy

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


def _has_image(inline: dict) -> bool:
    t = inline.get("t")
    if t == "Image":
        return True
    if t in ("Emph", "Strong", "Underline", "Strikeout", "SmallCaps", "Span"):
        return any(_has_image(i) for i in inline.get("c") or [])
    if t in ("Link", "Quoted"):
        return any(_has_image(i) for i in inline["c"][1])
    return False


def _is_image_block(block: dict) -> bool:
    """Standalone image content: a pandoc Figure block, or a Para/Plain
    carrying an Image inline (directly or inside emphasis/link)."""
    t = block.get("t")
    if t == "Figure":
        return True
    return t in ("Para", "Plain") and any(_has_image(i) for i in block.get("c") or [])


def _caption_scope(spec: EnvSpec, path: tuple[int | str, ...],
                   max_depth: int) -> tuple[int | str, ...]:
    """Counter scope key for one caption (EnvSpec.counter_scope).

    ``section`` scopes by the DISPLAYED section — the path clamped to the
    caption depth — so tables under ``2.2.3`` and under ``2.2.3.1`` share the
    ``表 2.2.3-N`` sequence and caption numbers stay unique per document.
    ``chapter`` scopes by the first path element, ``continuous`` globally.
    """
    if spec.counter_scope == "continuous":
        return ()
    if spec.counter_scope == "chapter":
        return path[:1]
    return path[:max_depth]


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

    def current_path() -> tuple[int | str, ...]:
        return prefix + tuple(counters[level] for level in sorted(counters))

    caption_counters: dict[tuple[str, tuple[int | str, ...]], int] = {}
    # open env names, innermost last. Captionless-env warnings are
    # ValidateAnchors' job; this stack only drives caption detection and
    # per-block env_scope.
    env_stack: list[str] = []

    def match_caption(text: str) -> tuple[str, EnvSpec] | None:
        """Innermost numbered env whose label prefixes ``text``, if any."""
        for env in reversed(env_stack):
            spec = strategy.envs.get(env)
            if spec is None or not spec.numbered:
                continue
            if text.startswith(f"{spec.label} "):
                return spec.name, spec
        return None

    annotations: list[NodeInfo] = []
    for index, block in enumerate(blocks(ast)):
        node = NodeInfo(index=index)
        if block.get("t") == "Header":
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
                if env_stack and block.get("t") == "Para":
                    matched = match_caption(plain_text(block.get("c") or []))
                    if matched is not None:
                        name, spec = matched
                        node.kind = "caption"
                        node.caption_env = name
                        key = (name, _caption_scope(spec, current_path(),
                                                    config.caption_max_depth))
                        start = config.env_start.get(name, 1)
                        caption_counters[key] = caption_counters.get(key, start - 1) + 1
                        node.caption_index = caption_counters[key]
                    elif _is_image_block(block):
                        node.kind = "image_para"
                elif block.get("t") == "Table":
                    node.kind = "table"
                elif _is_image_block(block):
                    node.kind = "image_para"
                node.env_scope = env_stack[-1] if env_stack else None
            node.section_path = current_path()
        annotations.append(node)

    return annotations
