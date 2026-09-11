"""md_normalize phase ops (ticket 06): pandoc defect prevention.

ToolSpec Q17 rule: structure pandoc preserves -> repair in polish; structure
pandoc destroys -> prevent here, before the AST reaches the docx writer or
the emitted markdown. Verified against pandoc 3.7 on this host:

- Raw HTML tables survive the markdown reader only as ``RawBlock("html")``
  runs with the cell text as loose ``Plain`` blocks between them; the docx
  writer DROPS those runs entirely (naked text, no ``w:tbl``).
  ``NormalizeTables`` re-reads each run through pandoc's HTML reader into
  real ``Table`` AST nodes.
- Simple tables aligned with fullwidth spaces (and header-only simple
  tables) never parse as tables at all: the reader leaves one ``Para``
  whose SoftBreak lines are the flattened rows — the dash row even gets
  smart-dash mangled (``--`` -> ``–``/``—``). ``NormalizeTables``
  recognizes that wreckage signature and rebuilds the ``Table``.
- Well-formed simple/pipe/grid ``Table`` nodes round-trip cleanly through
  pandoc 3.7 (the markdown writer emits simple tables that reparse
  faithfully; the docx writer emits ``w:tbl`` for every Table shape
  probed: grid cells, col/row spans, empty thead, nested tables). The op
  is a verified no-op for those shapes beyond defensive colspec padding.

``NormalizeImages`` injects ``{width=… height=…}`` attrs (pandoc's
giant-image defect: images without dims render at intrinsic size, so a
multi-thousand-pixel photo dwarfs the page).
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import TYPE_CHECKING

from snippet_docx.findings import Finding
from snippet_docx.ops_md import MdOp
from snippet_docx.pandoc_ast import PandocError, _run, blocks, plain_text

if TYPE_CHECKING:
    from snippet_docx.pipeline import Ctx


# a collapsed simple-table separator row: >=2 groups of >=2 dash-like chars
# (hyphen/en dash/em dash — smart punctuation rewrites "--" runs) separated
# by runs of spaces/fullwidth spaces, with nothing else on the line
_SEPARATOR_RE = re.compile(r"^[\s\u3000]*([-–—]{2,})(?:[\s\u3000]+([-–—]{2,}))+[\s\u3000]*$")
_DASH_GROUPS_RE = re.compile(r"[-–—]{2,}")
# cell boundaries inside wreckage rows: >=2 spaces/fullwidth spaces
_CELL_SPLIT_RE = re.compile(r"[\s\u3000]{2,}")

_DEFAULT_WIDTH_PX = 600  # ~A4 text width at 96 dpi; height left to pandoc's
                         # aspect-preserving sizing when the file is unreadable

# --------------------------------------------------------------------------
# shared AST helpers
# --------------------------------------------------------------------------

def _text_inlines(text: str) -> list[dict]:
    """Str/Space inline list from plain text (pandoc Str carries no spaces)."""
    inlines: list[dict] = []
    for i, word in enumerate(text.split(" ")):
        if i:
            inlines.append({"t": "Space"})
        if word:
            inlines.append({"t": "Str", "c": word})
    return inlines


def _attr() -> list:
    return ["", [], []]


def _cell(text: str) -> list:
    blocks_ = [{"t": "Plain", "c": _text_inlines(text)}] if text else []
    return [_attr(), {"t": "AlignDefault"}, 1, 1, blocks_]


def _row(texts: list[str]) -> list:
    return [_attr(), [_cell(t) for t in texts]]


def _table(header: list[str] | None, body: list[list[str]], ncols: int) -> dict:
    specs = [[{"t": "AlignDefault"}, {"t": "ColWidthDefault"}] for _ in range(ncols)]
    thead_rows = [_row(header)] if header is not None else []
    return {"t": "Table", "c": [
        _attr(), [None, []], specs,
        [_attr(), thead_rows],
        [[_attr(), 0, [], [_row(r) for r in body]]],  # c[4] = [TableBody]
        [_attr(), []],
    ]}



# --------------------------------------------------------------------------
# NormalizeTables
# --------------------------------------------------------------------------

def _para_lines(block: dict) -> list[str] | None:
    """SoftBreak/LineBreak-split text lines of a Para, or None if it carries
    structure we cannot flatten safely (images, math, raw inlines)."""
    lines: list[str] = []
    current: list[dict] = []
    for inline in block.get("c") or []:
        t = inline.get("t")
        if t in ("SoftBreak", "LineBreak"):
            lines.append(plain_text(current))
            current = []
        elif t in ("Image", "Math", "RawInline", "Link"):
            return None
        else:
            current.append(inline)
    lines.append(plain_text(current))
    return lines



def _rebuild_collapsed_table(lines: list[str]) -> dict | None:
    """Rebuild a Table from collapsed simple-table wreckage lines."""
    sep_index = -1
    ncols = 0
    for i, line in enumerate(lines):
        if _SEPARATOR_RE.match(line):
            sep_index = i
            ncols = len(_DASH_GROUPS_RE.findall(line))
            break
    if sep_index < 0 or ncols < 2:
        return None


    def cells_of(line: str) -> list[str]:
        parts = [p.strip() for p in _CELL_SPLIT_RE.split(line.strip())]
        if len(parts) > ncols:  # merge overflow into the last cell
            parts = parts[:ncols - 1] + [" ".join(parts[ncols - 1:])]
        while len(parts) < ncols:
            parts.append("")
        return parts

    header = lines[sep_index - 1] if sep_index > 0 else None
    body_lines = [line for line in lines[sep_index + 1:] if line.strip()]
    if header is None and not body_lines:
        return None
    if header is not None and not header.strip():
        header = None
    header_cells = cells_of(header) if header is not None else None
    body = [cells_of(line) for line in body_lines]
    return _table(header_cells, body, ncols)


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _raw_html_source(block: dict) -> str | None:
    if block.get("t") == "RawBlock" and block.get("c", [None])[0] == "html":
        return block["c"][1]
    return None


def _is_plain_block(block: dict) -> bool:
    return block.get("t") == "Plain"


def _recover_html_run(run: list[dict]) -> list[dict] | None:
    """RawBlock/Plain run containing a <table> -> real blocks via the HTML
    reader. Returns replacement blocks, or None to keep the run as-is."""
    html = "".join(
        _raw_html_source(b) if _raw_html_source(b) is not None
        else _html_escape(plain_text(b.get("c") or []))
        for b in run
    )
    if "<table" not in html.lower():
        return None
    try:
        parsed = json.loads(_run(["-f", "html", "-t", "json"], html))
    except (PandocError, ValueError):
        return None
    new_blocks = parsed["blocks"] if isinstance(parsed, dict) else parsed
    if not any(b.get("t") == "Table" for b in new_blocks):
        return None
    return new_blocks


class NormalizeTables:
    """Prevent the pandoc simple/HTML-table collapse (ToolSpec §6, Q17).

    1. Raw HTML table runs -> real ``Table`` AST nodes (pandoc's docx writer
       drops RawBlock html to naked text).
    2. Collapsed simple-table wreckage (fullwidth-space alignment,
       header-only tables) -> rebuilt ``Table`` nodes.
    3. Existing ``Table`` nodes are left alone: every shape probed through
       pandoc 3.7 survives both writers, so rewriting them would be
       vandalism, not repair.
    """

    def __call__(self, ast: dict, ctx: Ctx) -> list[Finding]:
        block_list = blocks(ast)
        # -- raw HTML runs (scan a snapshot; we rebuild the list in place)
        out: list[dict] = []
        i = 0
        while i < len(block_list):
            block = block_list[i]
            if _raw_html_source(block) is not None or _is_plain_block(block):
                j = i
                run: list[dict] = []
                while j < len(block_list):
                    b = block_list[j]
                    if _raw_html_source(b) is not None or _is_plain_block(b):
                        run.append(b)
                        j += 1
                    else:
                        break
                if any(_raw_html_source(b) is not None for b in run):
                    replacement = _recover_html_run(run)
                    out.extend(replacement if replacement is not None else run)
                else:
                    out.extend(run)
                i = j
            else:
                out.append(block)
                i += 1
        block_list[:] = out

        # -- collapsed simple-table wreckage
        for index, block in enumerate(block_list):
            if block.get("t") != "Para":
                continue
            lines = _para_lines(block)
            if lines is None:
                continue
            rebuilt = _rebuild_collapsed_table(lines)
            if rebuilt is not None:
                block_list[index] = rebuilt
        return []


# --------------------------------------------------------------------------
# NormalizeImages
# --------------------------------------------------------------------------

def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > len(data):
            return None
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        # SOF0-15 minus DHT(C4), JPG(C8), DAC(CC) carry size at +5/+7
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 <= len(data):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return width, height
            return None
        if seg_len < 2:
            return None
        i += 2 + seg_len
    return None


def _image_size(path: Path) -> tuple[int, int] | None:
    """Pixel size of a PNG/JPEG file, or None when unresolvable."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return _png_size(data) or _jpeg_size(data)


def _iter_images(node):
    """Recursively yield every Image inline dict in the AST."""
    if isinstance(node, dict):
        if node.get("t") == "Image":
            yield node
        for value in node.values():
            yield from _iter_images(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_images(item)


class NormalizeImages:
    """Inject ``{width=… height=…}`` attrs on size-less images (pandoc's
    giant-image defect: no dims -> rendered at intrinsic pixel size).

    Sizes come from the image file's real pixel dimensions (PNG IHDR /
    JPEG SOF headers, no imaging dependency). Unresolvable files get a
    width-only sensible default (A4 text width at 96 dpi); pandoc then
    preserves the aspect ratio instead of distorting a guessed height.
    Images that already carry either dimension are left untouched.
    """

    def __call__(self, ast: dict, ctx: Ctx) -> list[Finding]:
        for image in _iter_images(ast):
            attr = image["c"][0]
            if not isinstance(attr, list) or len(attr) < 3:
                continue
            kvs = attr[2]
            keys = {k for k, _v in kvs}
            if "width" in keys or "height" in keys:
                continue
            url = image["c"][2][0] if len(image["c"]) > 2 else ""
            target = Path(url)
            if not target.is_absolute() and ctx is not None and ctx.source_dir is not None:
                target = ctx.source_dir / target
            size = _image_size(target)
            if size is not None:
                kvs.append(["width", f"{size[0]}px"])
                kvs.append(["height", f"{size[1]}px"])
            else:
                kvs.append(["width", f"{_DEFAULT_WIDTH_PX}px"])
        return []


def ecepdi_normalize_ops() -> list[MdOp]:
    """md_normalize phase ops for ecepdi."""
    return [NormalizeTables(), NormalizeImages()]
