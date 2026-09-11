"""Pandoc subprocess wrapper + helpers over the pandoc JSON AST.

The pandoc JSON AST is the single markdown representation of the tool
(ToolSpec Q12): plain dicts/lists, no pandoc library dependency.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class PandocError(RuntimeError):
    """pandoc is missing or failed."""


def _pandoc() -> str:
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        raise PandocError("pandoc not found on PATH")
    return pandoc


def _run(args: list[str], input_text: str | None = None) -> str:
    proc = subprocess.run(
        [_pandoc(), *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit code {proc.returncode}"
        raise PandocError(f"pandoc failed: {detail}")
    return proc.stdout


# --------------------------------------------------------------------------
# conversions
# --------------------------------------------------------------------------

def md_to_ast(text: str) -> dict:
    """markdown text -> pandoc JSON AST (dict with 'blocks'; bare-list output
    from very old pandoc is wrapped into the dict form)."""
    data = json.loads(_run(["-f", "markdown", "-t", "json"], text))
    if isinstance(data, list):
        return {"pandoc-api-version": [1, 23, 1], "meta": {}, "blocks": data}
    return data


def ast_to_md(ast: dict) -> str:
    """pandoc JSON AST -> markdown text via pandoc (no hard wrapping)."""
    if isinstance(ast, list):
        ast = {"pandoc-api-version": [1, 23, 1], "meta": {}, "blocks": ast}
    return _run(["-f", "json", "-t", "markdown", "--wrap=none"], json.dumps(ast))


def ast_to_docx(ast: dict, out: Path, resource_path: Path | None = None) -> None:
    """pandoc JSON AST -> .docx file.

    ``resource_path`` anchors relative image targets to the source
    markdown's directory; without it pandoc resolves them against the
    process cwd and silently replaces unreadable images with alt text.
    """
    if isinstance(ast, list):
        ast = {"pandoc-api-version": [3, 1, 13], "meta": {}, "blocks": ast}
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-f", "json", "-t", "docx", "-o", str(out)]
    if resource_path is not None:
        args += ["--resource-path", str(resource_path)]
    _run(args, json.dumps(ast))


# --------------------------------------------------------------------------
# AST helpers
# --------------------------------------------------------------------------

def blocks(ast: dict) -> list[dict]:
    if isinstance(ast, list):
        return ast
    return ast["blocks"]


def _code_text(inline: dict) -> str | None:
    if inline.get("t") != "Code":
        return None
    return inline["c"][1]


def code_paragraph_payload(block: dict, prefix: str) -> str | None:
    """Para whose inlines are exactly one Code span whose text starts with
    prefix -> payload after prefix; else None."""
    if block.get("t") != "Para":
        return None
    inlines = block.get("c") or []
    if len(inlines) != 1:
        return None
    text = _code_text(inlines[0])
    if text is None or not text.startswith(prefix):
        return None
    return text[len(prefix):]


def paragraph_starts_with_code(block: dict, prefix: str) -> str | None:
    """Para whose FIRST inline is a Code span with prefix but has other content
    (non-standalone begin/end) -> payload; else None."""
    if block.get("t") != "Para":
        return None
    inlines = block.get("c") or []
    if len(inlines) < 2:
        return None
    text = _code_text(inlines[0])
    if text is None or not text.startswith(prefix):
        return None
    return text[len(prefix):]


_INLINE_CONTAINERS = frozenset({
    "Emph", "Strong", "Underline", "Strikeout", "SmallCaps", "Span",
})


def inline_code_spans(block: dict, prefix: str) -> list[tuple[dict, str]]:
    """(Code inline element, payload) pairs anywhere inside a Para (for
    anchor:section) — recursing into container inlines (Emph/Strong/...)."""
    found: list[tuple[dict, str]] = []

    def _walk(inlines: list) -> None:
        for inline in inlines:
            text = _code_text(inline)
            if text is not None and text.startswith(prefix):
                found.append((inline, text[len(prefix):]))
            elif inline.get("t") in _INLINE_CONTAINERS:
                _walk(inline["c"])

    if block.get("t") == "Para":
        _walk(block.get("c") or [])
    return found


def plain_text(inlines: list) -> str:
    """Flatten pandoc inlines to their visible text."""
    parts: list[str] = []
    for inline in inlines:
        t = inline.get("t")
        if t == "Str":
            parts.append(inline["c"])
        elif t in ("Space", "SoftBreak", "LineBreak"):
            parts.append(" ")
        elif t in ("Code", "RawInline") or t == "Math":
            parts.append(inline["c"][1])
        elif t in _INLINE_CONTAINERS:
            parts.append(plain_text(inline["c"]))
        elif t == "Quoted" or t in ("Link", "Image"):
            parts.append(plain_text(inline["c"][1]))
    return "".join(parts)


def make_para(text: str) -> dict:
    """Plain Para from text (splits on spaces; Str/Space inlines)."""
    inlines: list[dict] = []
    for i, word in enumerate(text.split(" ")):
        if i:
            inlines.append({"t": "Space"})
        if word:
            inlines.append({"t": "Str", "c": word})
    return {"t": "Para", "c": inlines}


def make_code_paragraph(payload_with_prefix: str) -> dict:
    """Standalone anchor paragraph: Para of exactly one Code span."""
    return {"t": "Para", "c": [{"t": "Code", "c": [["", [], []], payload_with_prefix]}]}
