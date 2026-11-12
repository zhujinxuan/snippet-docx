"""Caption discovery and final DOCX realization, scoped to explicit anchor envs.

Markdown supplies titles and heading context; the DOCX supplies the content
objects. No caption text is expanded or numbered during draft conversion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from docx.oxml.ns import qn
from lxml import etree

from snippet_docx.findings import Finding
from snippet_docx.pandoc_ast import blocks, plain_text

if TYPE_CHECKING:
    from snippet_docx.config import Config
    from snippet_docx.pipeline import Ctx
    from snippet_docx.strategy import EnvSpec, Strategy
    from snippet_docx.walker import NodeInfo

_STALE_NUMBER = re.compile(r"[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*-\d+(?=\s|$)")
HEADING_CONTEXT = "snippet-docx-section"


def normalize_caption(text: str, label: str) -> str:
    """Drop an optional label and stale section-number token from either source."""
    text = text.strip()
    if text.startswith(label):
        rest = text[len(label):]
        if not rest or rest[0].isspace() or _STALE_NUMBER.match(rest):
            text = rest.strip()
    stale = _STALE_NUMBER.match(text)
    return text[stale.end():].strip() if stale else text


def is_legacy_caption(text: str, label: str) -> bool:
    if not text.startswith(label):
        return False
    rest = text[len(label):]
    return not rest or rest[0].isspace() or _STALE_NUMBER.match(rest) is not None


def _images(value):
    """Find images through links, formatting, and Figure blocks without flattening them."""
    if isinstance(value, dict):
        if value.get("t") == "Image":
            yield value
        else:
            for child in value.values():
                yield from _images(child)
    elif isinstance(value, list):
        for child in value:
            yield from _images(child)


def has_image(block: dict) -> bool:
    return next(_images(block), None) is not None


def _slot_text(slot: list) -> str:
    short, long_blocks = slot
    long_text = " ".join(plain_text(b.get("c") or [])
                         for b in long_blocks if b.get("t") in ("Plain", "Para"))
    return long_text.strip() or (plain_text(short).strip() if short else "")


def _native_title(block: dict, env: str) -> str:
    kind = block.get("t")
    if kind == "Table":
        return _slot_text(block["c"][1]) if env != "figure" else ""
    if env == "table" or kind not in ("Figure", "Para", "Plain"):
        return ""
    if kind == "Figure":
        title = _slot_text(block["c"][1])
        if title:
            return title
    return next((plain_text(image["c"][1]).strip() for image in _images(block)
                 if plain_text(image["c"][1]).strip()), "")


@dataclass
class CaptionSource:
    env: str
    begin: int
    end: int
    body: str = ""
    source_index: int | None = None
    findings: list[Finding] = field(default_factory=list)


def discover_captions(ast: dict, strategy: Strategy,
                      anchor_prefix: str = "anchor:", *, anchors=None) -> list[CaptionSource]:
    """Select exactly one title per numbered env; explicit paragraphs win.

    Selection is local to each paired env, never keyed by caption text.
    Empty titles do not hide a usable source of the other kind.
    """
    from snippet_docx.anchors import parse_anchors

    bs = blocks(ast)
    stack: list[tuple[str, int]] = []
    spans: list[CaptionSource] = []
    for anchor in (parse_anchors(ast, anchor_prefix) if anchors is None else anchors):
        if anchor.kind == "begin" and anchor.env in strategy.envs:
            stack.append((anchor.env, anchor.block_index))
        elif anchor.kind == "end" and stack and stack[-1][0] == anchor.env:
            env, begin = stack.pop()
            spec = strategy.envs[env]
            if spec.numbered:
                spans.append(CaptionSource(env, begin, anchor.block_index))
    spans.sort(key=lambda source: source.begin)
    for source in spans:
        spec = strategy.envs[source.env]
        legacy: list[tuple[int, str]] = []
        native: list[tuple[int, str]] = []
        nested = [(other.begin, other.end) for other in spans
                  if source.begin < other.begin < other.end < source.end]
        for index in range(source.begin + 1, source.end):
            if any(begin <= index <= end for begin, end in nested):
                continue
            block = bs[index]
            if block.get("t") == "Para" and not has_image(block):
                text = plain_text(block.get("c") or [])
                if is_legacy_caption(text, spec.label):
                    body = normalize_caption(text, spec.label)
                    if body:
                        legacy.append((index, body))
                    continue
            body = normalize_caption(_native_title(block, source.env), spec.label)
            if body:
                native.append((index, body))
        candidates = legacy or native
        if candidates:
            source.source_index, source.body = candidates[0]
            alternatives = [body for _, body in legacy[1:] + native
                            if body != source.body]
            if alternatives:
                source.findings.append(Finding(
                    code="caption-conflict",
                    severity=strategy.severities().get("caption-conflict", "warn"),
                    message=f"{source.env} env (blocks {source.begin}..{source.end}) "
                            f"has conflicting caption titles; "
                            f"{'explicit paragraph' if legacy else 'first native title'} "
                            f"{source.body!r} wins over {alternatives!r}"))
        else:
            source.findings.append(Finding(
                code="captionless-env",
                severity=("error" if spec.caption_required else
                          strategy.severities().get("captionless-env", "warn")),
                message=f"{source.env} env (blocks {source.begin}..{source.end}) "
                        "has no nonempty native/ALT or explicit caption "
                        "(styled but not numbered)"))
    return spans


def caption_scope(spec: EnvSpec, path: tuple[int | str, ...],
                  max_depth: int) -> tuple[int | str, ...]:
    if spec.counter_scope == "continuous":
        return ()
    if spec.counter_scope == "chapter":
        return path[:1]
    return path[:max_depth]


@dataclass(frozen=True)
class CaptionPlan:
    env: str
    text: str | None


def build_caption_plans(ast: dict, annotations: list[NodeInfo], config: Config,
                        strategy: Strategy) -> tuple[list[CaptionPlan], list[Finding]]:
    sources = discover_captions(ast, strategy, config.anchor_prefix)
    nodes = {node.index: node for node in annotations}
    plans: list[CaptionPlan] = []
    findings: list[Finding] = []
    for source in sources:
        findings.extend(source.findings)
        text = None
        if source.source_index is not None:
            node = nodes[source.source_index]
            if node.caption_index is None:
                raise RuntimeError("caption source is missing its numbering annotation")
            text = strategy.format_caption(
                strategy.envs[source.env], node.section_path[:config.caption_max_depth],
                node.caption_index, source.body)
        plans.append(CaptionPlan(source.env, text))
    return plans, findings


class NumberCaptions:
    """Realize the shared caption plans before styling and landscape sectioning.

    Paragraphs containing drawings are never rewritten or deleted. Pandoc
    native caption paragraphs and legacy caption paragraphs are removed only
    within the corresponding explicit env, then one caption is inserted.
    """

    def __call__(self, doc, ctx: Ctx) -> list[Finding]:
        from snippet_docx.ops_docx import _anchor_marker, _current_pstyle, _set_pstyle

        if ctx.caption_plans is None:
            return [Finding("md-required", "error",
                            "polish requires --md to discover caption titles and section context")]
        body = doc.element.body
        p_tag, table_tag = qn("w:p"), qn("w:tbl")
        stack = []
        spans = []
        for child in body:
            if child.tag != p_tag:
                continue
            marker = _anchor_marker(child, ctx.config.anchor_prefix)
            if marker is None:
                continue
            kind, _, env = marker.partition(":")
            if kind == "begin":
                stack.append((env, child))
            elif kind == "end" and stack and stack[-1][0] == env:
                name, begin = stack.pop()
                spec = ctx.strategy.envs.get(name)
                if spec is not None and spec.numbered:
                    spans.append((name, begin, child))
        positions = {child: index for index, child in enumerate(body)}
        spans.sort(key=lambda span: positions[span[1]])
        plans = ctx.caption_plans
        if [env for env, _, _ in spans] != [plan.env for plan in plans]:
            return [Finding("caption-context-mismatch", "error",
                            "DOCX numbered anchor envs do not match --md; use the Markdown "
                            "that produced this draft (prefer draft --emit-md)")]
        for (env, begin, end), plan in zip(spans, plans):
            spec = ctx.strategy.envs[env]
            inside = []
            for child in begin.itersiblings():
                if child is end:
                    break
                inside.append(child)
            content = []
            native_styles = ({"TableCaption"} if env == "table" else
                             {"ImageCaption"} if env == "figure" else
                             {"TableCaption", "ImageCaption"})
            for child in inside:
                drawing = (child.find(f".//{qn('w:drawing')}") is not None or
                           child.find(f".//{qn('w:pict')}") is not None)
                if child.tag == table_tag or drawing:
                    if ((child.tag == table_tag and env != "figure") or
                            (drawing and env != "table")):
                        content.append(child)
                    continue
                if child.tag != p_tag or _anchor_marker(child, ctx.config.anchor_prefix) is not None:
                    continue
                text = "".join(t.text or "" for t in child.iter(qn("w:t")))
                if (_current_pstyle(child) in native_styles | {f"{env}_caption"}
                        or is_legacy_caption(text, spec.label)):
                    body.remove(child)
            if plan.text is None:
                continue
            caption = etree.Element(p_tag)
            run = etree.SubElement(caption, qn("w:r"))
            text_node = etree.SubElement(run, qn("w:t"))
            text_node.text = plan.text
            caption_style = (spec.caption_style if spec.caption_style != "Caption"
                             else f"{env}_caption")
            _set_pstyle(caption, caption_style)
            if content:
                if spec.caption_placement == "above":
                    content[0].addprevious(caption)
                else:
                    content[-1].addnext(caption)
            else:
                end.addprevious(caption)
        return []
