"""snippet-docx command-line interface: draft and polish (ToolSpec §2)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from snippet_docx.config import ConfigError, load_config
from snippet_docx.findings import has_errors, report_stderr
from snippet_docx.jinja_render import TemplateRenderError, render_template
from snippet_docx.pandoc_ast import PandocError
from snippet_docx.pipeline import draft, polish

if TYPE_CHECKING:
    from snippet_docx.strategy import Strategy


def _fail(message: str) -> SystemExit:
    return SystemExit(f"error: {message}")


def _load(path: Path, strategy_override: str | None):
    try:
        return load_config(path, strategy_override)
    except ConfigError as exc:
        raise _fail(str(exc)) from exc


def _resolve_md_text(args: argparse.Namespace, strategy: Strategy) -> tuple[str, str]:
    """Pick exactly one markdown source (positional md or --template+--data).

    Returns (md_text, source_label). Exactly one source is required: the
    positional input and --template are mutually exclusive. In template mode
    the jinja render IS the first draft phase (ToolSpec §1).
    """
    if args.input is not None and args.template is not None:
        raise _fail(
            "input markdown and --template are mutually exclusive "
            "(give exactly one source)")
    if args.input is None and args.template is None:
        raise _fail(
            "no input given: provide an input markdown file, "
            "or --template + --data")
    if args.template is None:
        if not args.input.is_file():
            raise _fail(f"input markdown not found: {args.input}")
        return args.input.read_text(encoding="utf-8"), str(args.input)

    if args.data is None:
        raise _fail("--template requires --data")
    if not args.template.is_file():
        raise _fail(f"template not found: {args.template}")
    if not args.data.is_file():
        raise _fail(f"data file not found: {args.data}")
    md_text = render_template(args.template, args.data, strategy)
    return md_text, str(args.template)


def _cmd_draft(args: argparse.Namespace) -> int:
    config, strategy = _load(args.snippet, args.strategy)
    try:
        md_text, source = _resolve_md_text(args, strategy)
    except TemplateRenderError as exc:
        raise _fail(str(exc)) from exc
    try:
        findings = draft(md_text, config, strategy, args.out, args.emit_md)
    except PandocError as exc:
        raise _fail(str(exc)) from exc
    report_stderr(findings)
    if has_errors(findings):
        return 1
    print(f"draft: {source} -> {args.out}")
    return 0


def _cmd_polish(args: argparse.Namespace) -> int:
    config, strategy = _load(args.snippet, args.strategy)
    if not args.docx.is_file():
        raise _fail(f"draft DOCX not found: {args.docx}")
    try:
        findings = polish(args.docx, config, strategy, args.out, args.md)
    except PandocError as exc:
        raise _fail(str(exc)) from exc
    report_stderr(findings)
    print(f"polish: {args.docx} -> {args.out}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snippet-docx",
        description="Convert a markdown snippet into a house-standard DOCX.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    draft_parser = sub.add_parser("draft", help="markdown -> draft DOCX via pandoc")
    draft_parser.add_argument(
        "input", type=Path, nargs="?", default=None,
        help="input markdown file (or use --template + --data)")
    draft_parser.add_argument(
        "--template", type=Path, default=None,
        help="jinja2 template (.md.j2) rendered as the first draft phase")
    draft_parser.add_argument(
        "--data", type=Path, default=None,
        help="YAML data for --template (required with it)")
    draft_parser.add_argument("--snippet", type=Path, required=True, help="snippet.yaml config")
    draft_parser.add_argument("--strategy", default=None, help="strategy override (default: ecepdi)")
    draft_parser.add_argument("--out", type=Path, required=True, help="output draft DOCX")
    draft_parser.add_argument("--emit-md", type=Path, default=None, help="write the processed markdown here")
    draft_parser.set_defaults(func=_cmd_draft)

    polish_parser = sub.add_parser("polish", help="draft DOCX -> final DOCX")
    polish_parser.add_argument("docx", type=Path, help="draft DOCX from the draft command")
    polish_parser.add_argument("--snippet", type=Path, required=True, help="snippet.yaml config")
    polish_parser.add_argument("--strategy", default=None, help="strategy override (default: ecepdi)")
    polish_parser.add_argument("--md", type=Path, default=None, help="anchored markdown (optional strategy input)")
    polish_parser.add_argument("--out", type=Path, required=True, help="output final DOCX")
    polish_parser.set_defaults(func=_cmd_polish)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
