"""Fixed draft/polish pipeline: headings in draft, captions in final DOCX."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from docx import Document

from snippet_docx.anchors import parse_anchors, validate_anchors
from snippet_docx.captions import CaptionPlan, build_caption_plans, discover_captions
from snippet_docx.findings import Finding, has_errors
from snippet_docx.pandoc_ast import ast_to_docx, ast_to_md, md_to_ast
from snippet_docx.walker import build_annotations

if TYPE_CHECKING:
    from snippet_docx.config import Config
    from snippet_docx.ops_docx import DocxOp
    from snippet_docx.ops_md import MdOp
    from snippet_docx.strategy import Phase, Strategy

    from .walker import NodeInfo


@dataclass
class Ctx:
    config: Config
    strategy: Strategy
    annotations: list[NodeInfo] | None = None   # shared Markdown section/caption context
    source_dir: Path | None = None              # md/template dirname: base for
    # relative image resolution (pandoc --resource-path + NormalizeImages)
    caption_plans: list[CaptionPlan] | None = None


def run_phase(phase: Phase, ctx: Ctx, proceed: Callable[[Ctx], Ctx]) -> Ctx:
    """Run one phase inside the strategy's wrap_phase continuation.

    ``proceed`` must be called exactly once per invocation (ToolSpec Q20);
    anything else is a strategy defect and raises RuntimeError.
    """
    calls = 0

    def proceed_once(c: Ctx) -> Ctx:
        nonlocal calls
        calls += 1
        return proceed(c)

    result = ctx.strategy.wrap_phase(phase, ctx, proceed_once)
    if calls != 1:
        raise RuntimeError(
            f"strategy {ctx.strategy.name!r} wrap_phase({phase!r}) called proceed "
            f"{calls} times; exactly 1 call is required")
    return result


def _run_md_ops(ops: list[MdOp], ast: dict, findings: list[Finding], c: Ctx) -> Ctx:
    for op in ops:
        findings.extend(op(ast, c))
    return c


def draft(md_text: str, config: Config, strategy: Strategy,
          out_docx: Path, emit_md: Path | None,
          source_dir: Path | None = None) -> list[Finding]:
    """Command 1. Returns findings; on any error, writes no outputs.

    ``source_dir`` (the input markdown's dirname) anchors relative image
    targets: pandoc resolves them against the process cwd otherwise, which
    silently degrades missing images to alt text (2026-09-10 field bug).
    """
    ctx = Ctx(config=config, strategy=strategy, source_dir=source_dir)
    ast = md_to_ast(md_text)
    findings: list[Finding] = []

    def md_number(c: Ctx) -> Ctx:
        # counters advance inside the phase (L3 invariant): the walker runs
        # before the ops so Ctx.annotations exists when they execute
        c.annotations = build_annotations(ast, c.config, c.strategy)
        for node in c.annotations:
            findings.extend(node.findings)
        return _run_md_ops(strategy.md_ops(), ast, findings, c)

    run_phase("md_number", ctx, md_number)
    if has_errors(findings):
        return findings
    run_phase("md_normalize", ctx,
              lambda c: _run_md_ops(strategy.md_normalize_ops(), ast, findings, c))
    findings.extend(finding for source in discover_captions(
        ast, strategy, config.anchor_prefix) for finding in source.findings)
    if has_errors(findings):
        return findings

    ast_to_docx(ast, out_docx, resource_path=source_dir)
    if emit_md is not None:
        emit_md.parent.mkdir(parents=True, exist_ok=True)
        emit_md.write_text(ast_to_md(ast), encoding="utf-8")
    return findings


def polish(docx_in: Path, config: Config, strategy: Strategy,
           out_docx: Path, md: Path | None) -> list[Finding]:
    """Style/repair a draft, using required Markdown for caption context.

    Errors are returned as findings and no final DOCX is written.
    """
    if md is None:
        return [Finding("md-required", "error",
                        "polish requires --md (prefer draft --emit-md) for caption "
                        "titles and section numbering context")]
    if not md.is_file():
        return [Finding("md-required", "error", f"polish Markdown not found: {md}")]
    if not docx_in.is_file():
        raise FileNotFoundError(f"draft DOCX not found: {docx_in}")
    from snippet_docx.ops_md import SubstituteGlobalVar
    from snippet_docx.ops_md_normalize import NormalizeTables

    ctx = Ctx(config=config, strategy=strategy, source_dir=md.resolve().parent)
    ast = md_to_ast(md.read_text(encoding="utf-8"))
    findings: list[Finding] = []
    doc = Document(str(docx_in))

    def proceed(c: Ctx) -> Ctx:
        findings.extend(NormalizeTables()(ast, c))
        findings.extend(validate_anchors(
            parse_anchors(ast, c.config.anchor_prefix), ast, c.strategy,
            check_captions=False))
        c.annotations = build_annotations(ast, c.config, c.strategy)
        findings.extend(SubstituteGlobalVar()(ast, c))
        # Substitution can change title emptiness/selection; number the
        # resolved sources, not the provisional section-context walk.
        c.annotations = build_annotations(ast, c.config, c.strategy)
        findings.extend(finding for node in c.annotations for finding in node.findings)
        c.caption_plans, caption_findings = build_caption_plans(
            ast, c.annotations, c.config, c.strategy)
        findings.extend(caption_findings)
        if has_errors(findings):
            return c
        ops: list[DocxOp] = c.strategy.docx_ops()
        for op in ops:
            findings.extend(op(doc, c) or [])
            if has_errors(findings):
                break
        return c

    run_phase("docx_polish", ctx, proceed)
    if has_errors(findings):
        return findings
    out_docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_docx))
    return findings
