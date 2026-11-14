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


def _rich_title(block: dict, source_kind: str | None) -> bool:
    """Inspect only the selected title, not table cells or image objects."""
    if source_kind == "legacy":
        content = block.get("c") or []
    elif block.get("t") in {"Table", "Figure"} and _slot_text(block["c"][1]):
        content = block["c"][1]
    else:
        content = next((image["c"][1] for image in _images(block)
                        if plain_text(image["c"][1]).strip()), [])

    def rich(value):
        if isinstance(value, dict):
            return (value.get("t") in {"Math", "Emph", "Strong", "Underline", "Strikeout",
                                      "SmallCaps", "Span", "Code", "Link", "Quoted",
                                      "Note", "RawInline"} or
                    any(rich(child) for child in value.values()))
        return isinstance(value, list) and any(rich(child) for child in value)

    return rich(content)


@dataclass
class CaptionSource:
    env: str
    begin: int
    end: int
    body: str = ""
    source_index: int | None = None
    source_kind: str | None = None
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
            source.source_kind = "legacy" if legacy else "native"
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
    source_kind: str | None
    envelope: tuple[str, str] | None
    rich: bool
    source_object: tuple[str, int] | None


def _selected_native_object(ast: dict, source: CaptionSource) -> tuple[str, int] | None:
    """Identify the selected table/image, including objects without captions."""
    if source.source_kind != "native" or source.source_index is None:
        return None
    bs = blocks(ast)
    selected = bs[source.source_index]
    preceding = bs[source.begin + 1:source.source_index]
    if selected.get("t") == "Table":
        return ("table", sum(block.get("t") == "Table" for block in preceding))
    if selected.get("t") != "Figure" or not _slot_text(selected["c"][1]):
        # ALT fallback in an ordinary paragraph has no native caption
        # paragraph to preserve, even when another image later has one.
        return None

    def image_count(block):
        if block.get("t") == "Table":
            return 0
        content = block["c"][2] if block.get("t") == "Figure" else block
        return sum(1 for _ in _images(content))

    count = image_count(selected)
    if not count:
        return None
    offset = sum(image_count(block) for block in preceding)
    # Pandoc places a Figure's caption after its image content.
    return ("figure", offset + count - 1)


def build_caption_plans(ast: dict, annotations: list[NodeInfo], config: Config,
                        strategy: Strategy) -> tuple[list[CaptionPlan], list[Finding]]:
    sources = discover_captions(ast, strategy, config.anchor_prefix)
    nodes = {node.index: node for node in annotations}
    plans: list[CaptionPlan] = []
    findings: list[Finding] = []
    for source in sources:
        findings.extend(source.findings)
        text = None
        rich = False
        if source.source_index is not None:
            node = nodes[source.source_index]
            if node.caption_index is None:
                raise RuntimeError("caption source is missing its numbering annotation")
            text = strategy.format_caption(
                strategy.envs[source.env], node.section_path[:config.caption_max_depth],
                node.caption_index, source.body)
            rich = _rich_title(blocks(ast)[source.source_index], source.source_kind)
        envelope = None
        if text is not None and text.count(source.body) == 1:
            prefix, suffix = text.split(source.body)
            envelope = (prefix, suffix)
        elif text is not None and source.source_index is not None:
            # A short title can also occur in the section number or label.
            # Probe only to locate its envelope, never to replace the real
            # formatter's authoritative (possibly title-dependent) output.
            token = "__snippet_docx_caption_title__"
            while token in text or token in source.body:
                token += "_"
            probe = strategy.format_caption(
                strategy.envs[source.env], node.section_path[:config.caption_max_depth],
                node.caption_index, token)
            if probe.count(token) == 1:
                prefix, suffix = probe.split(token)
                if prefix + source.body + suffix == text:
                    envelope = (prefix, suffix)
        plans.append(CaptionPlan(source.env, text, source.source_kind, envelope, rich,
                                 _selected_native_object(ast, source)))
    return plans, findings


def _caption_has_content(paragraph, label: str) -> bool:
    text = "".join(t.text or "" for t in paragraph.iter(qn("w:t")))
    return bool(normalize_caption(text, label) or
                paragraph.find(f".//{qn('m:oMath')}") is not None)


def _leading_caption_text(paragraph):
    leading = []
    for node in paragraph.iter():
        if node.tag in {qn("m:oMath"), qn("w:tab"), qn("w:br"), qn("w:fldChar")}:
            # A non-whitespace sentinel represents the protected object only
            # for normalization; it is never written into the document.
            return leading, "".join(node.text or "" for node in leading) + "\0"
        if node.tag == qn("w:t"):
            leading.append(node)
    return leading, "".join(node.text or "" for node in leading)


def _trim_caption_prefix(paragraph, label: str) -> None:
    """Remove only leading text, including a stale prefix split over rich runs.

    OMML and other non-text objects end the leading-text region: their text
    must neither participate in normalization nor be rewritten as prose.
    """
    leading, text = _leading_caption_text(paragraph)
    normalized = normalize_caption(text, label)
    # Unlike normalize_caption, do not trim the trailing gap before math.
    remove = len(text) - len(text.lstrip())
    if normalized:
        remove = text.rfind(normalized, remove)
    else:
        remove = len(text)
    for node in leading:
        value = node.text or ""
        cut = min(remove, len(value))
        node.text = value[cut:]
        remove -= cut


def _caption_text_run(text: str):
    run = etree.Element(qn("w:r"))
    node = etree.SubElement(run, qn("w:t"))
    node.set(qn("xml:space"), "preserve")
    node.text = text
    return run


def _has_rich_content(paragraph) -> bool:
    return any(node.tag not in {qn("w:p"), qn("w:pPr"), qn("w:pStyle"),
                               qn("w:r"), qn("w:t")}
               for child in paragraph if child.tag != qn("w:pPr")
               for node in child.iter())


class NumberCaptions:
    """Realize the shared caption plans before styling and landscape sectioning.

    Paragraphs containing drawings are never rewritten or deleted. The selected
    caption paragraph is moved intact, with only its text prefix normalized;
    redundant native/legacy representations are removed within the same env.
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
        findings = []
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
            candidates = {"native": [], "legacy": []}
            removable = []
            objects = {}
            table_index = figure_index = 0
            for child in inside:
                if child.tag == table_tag:
                    objects[("table", table_index)] = child
                    table_index += 1
                elif child.tag == p_tag:
                    for node in child.iter():
                        if node.tag in {qn("w:drawing"), qn("w:pict")}:
                            objects[("figure", figure_index)] = child
                            figure_index += 1
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
                _, text = _leading_caption_text(child)
                style = _current_pstyle(child)
                kind = ("native" if style in native_styles else
                        "legacy" if is_legacy_caption(text, spec.label) else None)
                if kind is not None or style == f"{env}_caption":
                    removable.append(child)
                    if kind is not None and _caption_has_content(child, spec.label):
                        candidates[kind].append(child)
            if plan.text is None:
                for child in removable:
                    body.remove(child)
                continue
            if plan.source_kind == "native":
                source_object = plan.source_object
                selected_object = objects.get(source_object)
                caption = None
                if selected_object is not None and source_object is not None:
                    is_table = source_object[0] == "table"
                    caption = (selected_object.getprevious() if is_table
                               else selected_object.getnext())
                    native_style = "TableCaption" if is_table else "ImageCaption"
                    if (caption not in candidates["native"] or
                            _current_pstyle(caption) != native_style):
                        caption = None
            else:
                selected = candidates.get(plan.source_kind, [])
                caption = selected[0] if selected else None
            if caption is None and plan.rich:
                findings.append(Finding(
                    "caption-context-mismatch", "error",
                    f"{env} selected rich caption has no matching DOCX paragraph; "
                    "refusing to replace it with plain text"))
                continue
            if caption is not None and plan.envelope is None and _has_rich_content(caption):
                findings.append(Finding(
                    "caption-format-unsupported", "error",
                    f"{env} caption formatter must retain its rich title exactly once; "
                    "refusing to flatten native caption content"))
                continue
            for child in removable:
                body.remove(child)
            if caption is None:
                caption = etree.Element(p_tag)
                caption.append(_caption_text_run(plan.text))
            elif plan.envelope is None:
                for child in list(caption):
                    if child.tag != qn("w:pPr"):
                        caption.remove(child)
                caption.append(_caption_text_run(plan.text))
            else:
                _trim_caption_prefix(caption, spec.label)
                prefix, suffix = plan.envelope
                if prefix:
                    ppr = caption.find(qn("w:pPr"))
                    caption.insert(1 if ppr is not None else 0, _caption_text_run(prefix))
                if suffix:
                    caption.append(_caption_text_run(suffix))
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
        return findings
