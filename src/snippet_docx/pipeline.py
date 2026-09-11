"""Pipeline skeleton (tool-owned, fixed): draft and polish commands.

draft: md text -> pandoc JSON AST -> md_number phase -> md_normalize phase
       -> pandoc JSON->docx (+ optional anchored md emission).
polish: python-docx open draft.docx -> docx_polish phase -> save final.docx.
The docx phase never numbers anything (ToolSpec Q11/Q12).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from docx import Document

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
    annotations: list[NodeInfo] | None = None   # built before md_number ops
    source_dir: Path | None = None              # md/template dirname: base for
    # relative image resolution (pandoc --resource-path + NormalizeImages)


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
    if has_errors(findings):
        return findings

    ast_to_docx(ast, out_docx, resource_path=source_dir)
    if emit_md is not None:
        emit_md.parent.mkdir(parents=True, exist_ok=True)
        emit_md.write_text(ast_to_md(ast), encoding="utf-8")
    return findings


def polish(docx_in: Path, config: Config, strategy: Strategy,
           out_docx: Path, md: Path | None) -> list[Finding]:
    """Command 2: style/repair/strip the draft DOCX into the final DOCX."""
    if not docx_in.is_file():
        raise FileNotFoundError(f"draft DOCX not found: {docx_in}")
    doc = Document(str(docx_in))
    ctx = Ctx(config=config, strategy=strategy)

    def proceed(c: Ctx) -> Ctx:
        ops: list[DocxOp] = strategy.docx_ops()
        for op in ops:
            op(doc, c)
        return c

    run_phase("docx_polish", ctx, proceed)
    out_docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_docx))
    return []
