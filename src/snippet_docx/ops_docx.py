"""docx-phase ops: DocxOp = Callable[[Document, Ctx], None].

python-docx document transforms. Ticket 02: StripAnchors. Ticket 05:
CreateStyles + SetParagraphStyle (anchor-delimited range assignment; the
anchors are still present because StripAnchors runs LAST). Ticket 06:
FixTable + ClampImageWidths (pandoc-defect repair). Ticket 07:
InsertSectionBreak (landscape env -> section breaks), registered before
StripAnchors so it can still see the anchors; StripAnchors stays LAST.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from typing import TYPE_CHECKING

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from snippet_docx import styles

if TYPE_CHECKING:
    from snippet_docx.pipeline import Ctx

DocxOp = Callable[[Document, "Ctx"], None]

_W_P = qn("w:p")
_W_R = qn("w:r")
_W_T = qn("w:t")
_W_RPR = qn("w:rPr")
_W_RSTYLE = qn("w:rStyle")
_W_PPR = qn("w:pPr")
_W_PSTYLE = qn("w:pStyle")
_W_NUMPR = qn("w:numPr")
_W_VAL = qn("w:val")
_W_TBL = qn("w:tbl")
_W_DRAWING = qn("w:drawing")
_W_PICT = qn("w:pict")
_W_TR = qn("w:tr")
_W_TC = qn("w:tc")
_W_TCPR = qn("w:tcPr")
_W_TCW = qn("w:tcW")
_W_GRIDSPAN = qn("w:gridSpan")
_W_TBLPR = qn("w:tblPr")
_W_TBLGRID = qn("w:tblGrid")
_W_GRIDCOL = qn("w:gridCol")
_W_TBLW = qn("w:tblW")
_W_TBLBORDERS = qn("w:tblBorders")
_W_TBLAYOUT = qn("w:tblLayout")
_W_JC = qn("w:jc")
_W_SECTPR = qn("w:sectPr")
_W_PGSZ = qn("w:pgSz")
_W_PGMAR = qn("w:pgMar")
_W_W = qn("w:w")
_W_H = qn("w:h")
_W_ORIENT = qn("w:orient")
_W_LEFT = qn("w:left")
_W_RIGHT = qn("w:right")
_W_CX = "cx"  # unqualified attributes on wp:extent / a:ext
_W_CY = "cy"
_W_TYPE = qn("w:type")
_W_EXTENT = qn("wp:extent")
_A_EXT = qn("a:ext")
_VERBATIM = "VerbatimChar"

# pandoc's implicit-figure / table-caption styles -> our named caption styles
_PANDOC_CAPTION_STYLES = {"ImageCaption": "figure_caption",
                          "TableCaption": "table_caption"}
_HEADING_STYLE_RE = re.compile(r"Heading([1-9])")


def _run_text(run: object) -> str:
    return "".join(t.text or "" for t in run.findall(_W_T))


def _is_anchor_run(run: object, prefix: str) -> bool:
    """A VerbatimChar run whose text starts with the anchor prefix."""
    rpr = run.find(_W_RPR)
    if rpr is None:
        return False
    rstyle = rpr.find(_W_RSTYLE)
    if rstyle is None or rstyle.get(qn("w:val")) != _VERBATIM:
        return False
    return _run_text(run).startswith(prefix)


def _anchor_marker(para: object, prefix: str) -> str | None:
    """Payload after the prefix if the paragraph is a standalone anchor.

    A standalone anchor paragraph's every non-empty run is an anchor run
    (e.g. ``anchor:begin:table``); mixed paragraphs (inline ``anchor:section``
    inside prose) return None.
    """
    runs = para.findall(_W_R)
    if not runs:
        return None
    anchor_runs = [r for r in runs if _is_anchor_run(r, prefix)]
    if not anchor_runs:
        return None
    text_runs = [r for r in runs if _run_text(r)]
    if not all(r in anchor_runs for r in text_runs):
        return None
    return "".join(_run_text(r) for r in anchor_runs)[len(prefix):]


def _set_pstyle(para: etree._Element, style_id: str) -> None:
    """Point the paragraph at a named style via w:pStyle (first pPr child)."""
    ppr = para.find(_W_PPR)
    if ppr is None:
        ppr = etree.Element(_W_PPR)
        para.insert(0, ppr)
    pstyle = ppr.find(_W_PSTYLE)
    if pstyle is None:
        pstyle = etree.Element(_W_PSTYLE)
        ppr.insert(0, pstyle)
    pstyle.set(_W_VAL, style_id)


def _current_pstyle(para: etree._Element) -> str:
    ppr = para.find(_W_PPR)
    if ppr is None:
        return ""
    pstyle = ppr.find(_W_PSTYLE)
    if pstyle is None:
        return ""
    return pstyle.get(_W_VAL) or ""


class CreateStyles:
    """Define the named DOCX paragraph styles from the merged style config.

    One style per merged entry (heading1..5, normal_text, table_caption,
    figure_caption, table, list_item): fonts, size, emphasis, alignment,
    spacing, leading, first-line indent. Runs once, before assignment.
    """

    def __call__(self, doc: Document, ctx: Ctx) -> None:
        for name, spec in styles.resolve_styles(ctx.strategy, ctx.config).items():
            styles.define_paragraph_style(doc, name, spec)


class SetParagraphStyle:
    """Assign the named styles per anchor-delimited range.

    Walks the body in document order, tracking open envs from the standalone
    ``anchor:begin:<env>`` / ``anchor:end:<env>`` paragraphs (still present:
    StripAnchors runs after this op). Ranges: pandoc Heading N -> headingN,
    env captions (label-prefixed text) -> {env}_caption, pandoc caption
    styles -> our caption styles, numbered list paragraphs -> list_item,
    image-only paragraphs -> centered style with no first-line indent
    (figure_caption values: centered, indent-free, auto leading so tall
    images are never clipped by an exact line height), everything else ->
    normal_text. Table cell paragraphs get the table content style.
    """

    def __call__(self, doc: Document, ctx: Ctx) -> None:
        known = set(styles.resolve_styles(ctx.strategy, ctx.config))
        envs = ctx.strategy.envs
        prefix = ctx.config.anchor_prefix
        stack: list[str] = []
        for child in doc.element.body:
            if child.tag == _W_TBL:
                if "table" in known:
                    for para in child.iter(_W_P):
                        _set_pstyle(para, "table")
                continue
            if child.tag != _W_P:
                continue

            marker = _anchor_marker(child, prefix)
            if marker is not None:
                kind, _, env = marker.partition(":")
                if kind == "begin" and env:
                    stack.append(env)
                elif kind == "end" and env in stack:
                    if stack[-1] == env:
                        stack.pop()
                    else:
                        stack.remove(env)
                continue  # never styled; StripAnchors removes it later

            current = _current_pstyle(child)
            heading = _HEADING_STYLE_RE.fullmatch(current)
            if heading:
                name = f"heading{heading.group(1)}"
                if name in known:
                    _set_pstyle(child, name)
                continue
            caption = _PANDOC_CAPTION_STYLES.get(current)
            if caption is not None:
                if caption in known:
                    _set_pstyle(child, caption)
                continue

            ppr = child.find(_W_PPR)
            if ppr is not None and ppr.find(_W_NUMPR) is not None:
                if "list_item" in known:
                    _set_pstyle(child, "list_item")
                continue

            text = "".join(t.text or "" for t in child.iter(_W_T))
            has_image = (child.find(f".//{_W_DRAWING}") is not None
                         or child.find(f".//{_W_PICT}") is not None)
            if has_image and not text.strip():
                if "figure_caption" in known:
                    _set_pstyle(child, "figure_caption")
                continue

            env = stack[-1] if stack else None
            spec = envs.get(env) if env is not None else None
            caption_name = f"{env}_caption" if env is not None else None
            if (spec is not None and caption_name in known
                    and text.startswith(spec.label + " ")):
                _set_pstyle(child, caption_name)
                continue

            if "normal_text" in known:
                _set_pstyle(child, "normal_text")


# --------------------------------------------------------------------------
# FixTable / ClampImageWidths (ticket 06): pandoc-defect repair, ToolSpec §6
# --------------------------------------------------------------------------

# front-matter layout tables (keyword exclusion, 踏勘 prior art)
_FRONT_MATTER_RE = re.compile(r"^(项目名称|建设地点|建设单位|设计单位|编制|审核|批准|日期)")

# tblGrid recompute rules (styles/ecepdi-default.yaml conventions)
_CJK_TWIPS = 160            # per CJK char at 9 pt
_ASCII_TWIPS = 80           # per ASCII char at 9 pt
_CELL_PAD_TWIPS = 108       # cell padding per column
_NUMERIC_FLOOR = 1200       # numeric-column floor
_TEXT_FLOOR = 500           # text-column floor
_NUMERIC_CELL_RE = re.compile(r"^[0-9.,%±\-–—/∶: ]*$")

# element order inside w:tblPr (CT_TblPrBase sequence)
_WNS = _W_TBLPR[: _W_TBLPR.index("}") + 1]
_TBLPR_ORDER = [_WNS + n for n in (
    "tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
    "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd",
    "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook",
    "tblCaption", "tblDescription")]


def _insert_in_order(parent: etree._Element, child: etree._Element,
                     order: list) -> None:
    """Insert ``child`` into ``parent`` at its schema position."""
    rank = order.index(child.tag)
    for existing in parent:
        if existing.tag in order and order.index(existing.tag) > rank:
            existing.addprevious(child)
            return
    parent.append(child)


def _tc_text(tc: etree._Element) -> str:
    """Longest paragraph text in a cell (drives the column width)."""
    best = ""
    for para in tc.findall(_W_P):
        text = "".join(t.text or "" for t in para.iter(_W_T)).strip()
        if len(text) > len(best):
            best = text
    return best


def _text_twips(text: str) -> int:
    return sum(_CJK_TWIPS if ord(ch) > 127 else _ASCII_TWIPS for ch in text)


def _grid_span(tc: etree._Element) -> int:
    tcpr = tc.find(_W_TCPR)
    if tcpr is None:
        return 1
    span = tcpr.find(_W_GRIDSPAN)
    if span is None:
        return 1
    try:
        return max(1, int(span.get(_W_VAL, "1")))
    except ValueError:
        return 1


class FixTable:
    """Repair pandoc's table output (ported from 踏勘 ``fix_pandoc_tables.py``
    conventions, ToolSpec §6): single sz=4 borders on all six edges, table
    centered, tblGrid recomputed from cell content widths (CJK 160 / ASCII
    80 twips per char at 9 pt, +108 padding; numeric floor 1200, text floor
    500).

    Cell FONTS come from the named ``table`` paragraph style (9 pt
    宋体/TNR, styles engine + SetParagraphStyle) — this op never writes
    run-level font overrides, per the named-style-not-direct-formatting
    architecture.

    Front-matter layout tables are skipped: <=2 columns whose first column
    starts with a cover-sheet keyword (项目名称/建设地点/...).
    """

    def __call__(self, doc: Document, ctx: Ctx) -> None:
        for tbl in doc.element.body.iter(_W_TBL):
            self._fix(tbl)

    # -- structure

    def _fix(self, tbl: etree._Element) -> None:
        rows = tbl.findall(_W_TR)
        if not rows:
            return
        ncols = self._column_count(tbl, rows)
        if ncols <= 2:
            first = rows[0].findall(_W_TC)
            if first and _FRONT_MATTER_RE.match(_tc_text(first[0])):
                return  # layout table: never mangled
        widths = self._compute_widths(rows, ncols)
        self._apply_props(tbl)
        self._apply_grid(tbl, widths)
        self._apply_cell_widths(rows, widths)

    def _column_count(self, tbl: etree._Element, rows: list) -> int:
        grid = tbl.find(_W_TBLGRID)
        if grid is not None:
            ncols = len(grid.findall(_W_GRIDCOL))
            if ncols:
                return ncols
        return max(sum(_grid_span(tc) for tc in row.findall(_W_TC)) for row in rows)

    # -- geometry

    def _compute_widths(self, rows: list, ncols: int) -> list[int]:
        col_max = [0] * ncols
        numeric: list[bool] = [True] * ncols
        seen: list[bool] = [False] * ncols
        for r, row in enumerate(rows):
            col = 0
            for tc in row.findall(_W_TC):
                span = _grid_span(tc)
                text = _tc_text(tc)
                width = _text_twips(text) + _CELL_PAD_TWIPS
                for j in range(col, min(col + span, ncols)):
                    col_max[j] = max(col_max[j], width // span)
                if r > 0 and text:  # numeric-ness judged on body rows
                    ok = bool(_NUMERIC_CELL_RE.match(text))
                    for j in range(col, min(col + span, ncols)):
                        numeric[j] = numeric[j] and ok
                        seen[j] = True
                col += span
        return [max(col_max[j], _NUMERIC_FLOOR if seen[j] and numeric[j]
                    else _TEXT_FLOOR) for j in range(ncols)]

    # -- application

    def _apply_props(self, tbl: etree._Element) -> None:
        tblpr = tbl.find(_W_TBLPR)
        if tblpr is None:
            tblpr = etree.Element(_W_TBLPR)
            tbl.insert(0, tblpr)
        for tag in (_W_TBLW, _W_TBLBORDERS, _W_TBLAYOUT, qn("w:jc")):
            old = tblpr.find(tag)
            if old is not None:
                tblpr.remove(old)
        tblw = etree.Element(_W_TBLW)
        tblw.set(_W_W, "5000")           # pct 5000 = 100% of text width
        tblw.set(_W_TYPE, "pct")
        _insert_in_order(tblpr, tblw, _TBLPR_ORDER)
        jc = etree.Element(_W_JC)
        jc.set(_W_VAL, "center")
        _insert_in_order(tblpr, jc, _TBLPR_ORDER)
        borders = etree.Element(_W_TBLBORDERS)
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            el = etree.SubElement(borders, qn(f"w:{edge}"))
            el.set(_W_VAL, "single")
            el.set(qn("w:sz"), "4")
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), "000000")
        _insert_in_order(tblpr, borders, _TBLPR_ORDER)
        layout = etree.Element(_W_TBLAYOUT)
        layout.set(_W_TYPE, "autofit")
        _insert_in_order(tblpr, layout, _TBLPR_ORDER)

    def _apply_grid(self, tbl: etree._Element, widths: list[int]) -> None:
        old = tbl.find(_W_TBLGRID)
        if old is not None:
            tbl.remove(old)
        grid = etree.Element(_W_TBLGRID)
        for width in widths:
            col = etree.SubElement(grid, _W_GRIDCOL)
            col.set(_W_W, str(width))
        first_row = tbl.find(_W_TR)
        if first_row is not None:
            first_row.addprevious(grid)
        else:
            tbl.append(grid)

    def _apply_cell_widths(self, rows: list, widths: list[int]) -> None:
        for row in rows:
            col = 0
            for tc in row.findall(_W_TC):
                span = _grid_span(tc)
                tcpr = tc.find(_W_TCPR)
                if tcpr is None:
                    tcpr = etree.Element(_W_TCPR)
                    tc.insert(0, tcpr)
                old = tcpr.find(_W_TCW)
                if old is not None:
                    tcpr.remove(old)
                tcw = etree.Element(_W_TCW)
                tcw.set(_W_W, str(sum(widths[col:col + span])))
                tcw.set(_W_TYPE, "dxa")
                tcpr.insert(0, tcw)  # CT_TcPr: only cnfStyle precedes tcW
                col += span


_EMU_PER_TWIP = 635
_A4_PGSZ_TWIPS = 11906
_A4_MARGIN_TWIPS = 1440


class ClampImageWidths:
    """Clamp images wider than the text width (section pgSz minus margins)
    to the text width, scaling height proportionally. Both ``wp:extent``
    and the DrawingML ``a:ext`` transform are updated."""

    def __call__(self, doc: Document, ctx: Ctx) -> None:
        body = doc.element.body
        # keep every proxy alive in `seq` so id() stays unique per element
        seq = list(body.iter())
        order = {id(el): i for i, el in enumerate(seq)}
        sectprs = [(order[id(el)], el) for el in seq if el.tag == _W_SECTPR]
        for drawing in [el for el in seq if el.tag == _W_DRAWING]:
            extent = drawing.find(f".//{_W_EXTENT}")
            if extent is None:
                continue
            try:
                cx, cy = int(extent.get(_W_CX, "0")), int(extent.get(_W_CY, "0"))
            except ValueError:
                continue
            text_width = self._text_width(self._sectpr(drawing, order, sectprs))
            if cx <= 0 or cx <= text_width:
                continue
            scale = text_width / cx
            extent.set(_W_CX, str(text_width))
            extent.set(_W_CY, str(round(cy * scale)))
            for ext in drawing.iter(_A_EXT):  # pic:spPr/a:xfrm/a:ext
                ext.set(_W_CX, str(text_width))
                ext.set(_W_CY, str(round(cy * scale)))

    def _sectpr(self, drawing: etree._Element, order: dict,
                sectprs: list) -> etree._Element | None:
        """Section properties governing this drawing: its own paragraph's
        sectPr (it closes that section), else the first sectPr at or after
        it in document order, else None."""
        para = drawing.getparent()
        while para is not None and para.tag != _W_P:
            para = para.getparent()
        if para is not None:
            ppr = para.find(_W_PPR)
            if ppr is not None:
                sect = ppr.find(_W_SECTPR)
                if sect is not None:
                    return sect
        start = order.get(id(para if para is not None else drawing), 0)
        for pos, sect in sectprs:
            if pos >= start:
                return sect
        return None

    def _text_width(self, sectpr: etree._Element | None) -> int:
        pg_w, margin = _A4_PGSZ_TWIPS, _A4_MARGIN_TWIPS
        if sectpr is not None:
            pgsz = sectpr.find(_W_PGSZ)
            if pgsz is not None and pgsz.get(_W_W):
                pg_w = int(pgsz.get(_W_W))
            pgmar = sectpr.find(_W_PGMAR)
            if pgmar is not None and pgmar.get(_W_LEFT) and pgmar.get(_W_RIGHT):
                margin = int(pgmar.get(_W_LEFT)) + int(pgmar.get(_W_RIGHT))
        return (pg_w - margin) * _EMU_PER_TWIP


# --------------------------------------------------------------------------
# InsertSectionBreak (ticket 07): landscape env -> A4 landscape section
# --------------------------------------------------------------------------

_A4_LONG_TWIPS = 16838            # A4 long edge (landscape page width)
_LANDSCAPE_ENV = "landscape"
# pandoc's body sectPr carries no page geometry; explicit A4 portrait
# defaults keep every section deterministic (same margins everywhere)
_PGMAR_DEFAULTS = (("top", 1440), ("right", 1440), ("bottom", 1440),
                   ("left", 1440), ("header", 720), ("footer", 720),
                   ("gutter", 0))


class InsertSectionBreak:
    """Give each ``landscape`` env its own A4 landscape section (§6).

    Word stores a section's properties in the LAST paragraph of that
    section (``pPr/sectPr``). For every landscape env — located via its
    anchor paragraphs, which are still present because StripAnchors runs
    after this op:

    - an empty paragraph inserted before the begin anchor closes the
      portrait section (sectPr copied from the body section);
    - the env's last paragraph closes the landscape section: ``w:pgSz
      w=16838 h=11906 w:orient="landscape"``, margins copied verbatim
      from the portrait body section. A sectPr needs a paragraph to live
      on, so an empty one is inserted when the env ends on a table (or
      on nothing but anchors);
    - an empty paragraph after the end anchor opens the following
      portrait section.

    No ``w:type`` child means next-page breaks (the Word default). The
    copied portrait sectPr never rides on an anchor paragraph: those are
    removed by StripAnchors, which would take the section break with
    them.
    """

    def __call__(self, doc: Document, ctx: Ctx) -> None:
        body = doc.element.body
        body_sect = body.find(_W_SECTPR)
        if body_sect is None:
            return
        self._ensure_geometry(body_sect)
        prefix = ctx.config.anchor_prefix
        for begin_para, end_para in self._landscape_ranges(body, prefix):
            portrait_close = etree.Element(_W_P)
            begin_para.addprevious(portrait_close)
            self._close_section(portrait_close, deepcopy(body_sect))
            last = self._env_last_paragraph(begin_para, end_para, prefix)
            self._close_section(last, self._landscape_sectpr(body_sect))
            end_para.addnext(etree.Element(_W_P))  # opens portrait again

    # -- env location

    def _landscape_ranges(self, body: etree._Element,
                          prefix: str) -> list[tuple[etree._Element, etree._Element]]:
        """(begin, end) paragraph pair per landscape env, in document order.

        Tolerant stack pairing (mirrors the walker): mismatched nesting is
        ValidateAnchors' error, never this op's.
        """
        ranges = []
        stack: list[tuple[str, etree._Element]] = []
        for child in body:
            if child.tag != _W_P:
                continue
            marker = _anchor_marker(child, prefix)
            if marker is None:
                continue
            kind, _, env = marker.partition(":")
            if kind == "begin" and env:
                stack.append((env, child))
            elif kind == "end" and env:
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][0] == env:
                        begin_para = stack[i][1]
                        del stack[i:]
                        if env == _LANDSCAPE_ENV:
                            ranges.append((begin_para, child))
                        break
        return ranges

    def _env_last_paragraph(self, begin_para: etree._Element,
                            end_para: etree._Element,
                            prefix: str) -> etree._Element:
        """The paragraph that closes the landscape section: the env's last
        non-anchor body-level element when that is a paragraph; otherwise
        (the env ends on a table — or holds only anchors) an empty
        paragraph inserted just before the end anchor. Anchor paragraphs
        never carry the sectPr: StripAnchors removes them and the section
        break with them."""
        last = None
        for sibling in begin_para.itersiblings():
            if sibling is end_para:
                break
            if sibling.tag == _W_P and _anchor_marker(sibling, prefix) is not None:
                continue
            last = sibling
        if last is not None and last.tag == _W_P:
            return last
        close = etree.Element(_W_P)
        end_para.addprevious(close)
        return close

    # -- sectPr surgery

    def _close_section(self, para: etree._Element, sectpr: etree._Element) -> None:
        """Put ``sectpr`` on ``para``'s pPr, replacing any existing one."""
        ppr = para.find(_W_PPR)
        if ppr is None:
            ppr = etree.Element(_W_PPR)
            para.insert(0, ppr)
        old = ppr.find(_W_SECTPR)
        if old is not None:
            ppr.remove(old)
        ppr.append(sectpr)  # sectPr closes CT_PPr; nothing follows it here

    def _landscape_sectpr(self, body_sect: etree._Element) -> etree._Element:
        """Portrait body sectPr with the page box swapped to A4 landscape
        (margins and references copied verbatim)."""
        sect = deepcopy(body_sect)
        pgsz = sect.find(_W_PGSZ)
        if pgsz is None:  # _ensure_geometry already ran; stay safe anyway
            pgsz = etree.Element(_W_PGSZ)
            sect.append(pgsz)
        pgsz.set(_W_W, str(_A4_LONG_TWIPS))
        pgsz.set(_W_H, str(_A4_PGSZ_TWIPS))
        pgsz.set(_W_ORIENT, "landscape")
        return sect

    def _ensure_geometry(self, sectpr: etree._Element) -> None:
        """pandoc's body sectPr ships without pgSz/pgMar; fill explicit A4
        portrait geometry (only when absent — never rewrites real values),
        so pages before, inside and after the env are deterministic."""
        if sectpr.find(_W_PGSZ) is None:
            pgsz = etree.Element(_W_PGSZ)
            pgsz.set(_W_W, str(_A4_PGSZ_TWIPS))
            pgsz.set(_W_H, str(_A4_LONG_TWIPS))
            sectpr.append(pgsz)
        if sectpr.find(_W_PGMAR) is None:
            pgmar = etree.Element(_W_PGMAR)
            for name, value in _PGMAR_DEFAULTS:
                pgmar.set(qn(f"w:{name}"), str(value))
            sectpr.append(pgmar)  # pgSz then pgMar: CT_SectPr order holds


class StripAnchors:
    """Remove all anchor paragraphs/runs at XML level.

    Standalone anchor paragraphs (all text runs are anchors) lose the whole
    paragraph; inline anchors (e.g. an unsubstituted ``anchor:section`` span)
    lose only their run. Result: zero ``anchor:`` text in the final DOCX.
    """

    def __call__(self, doc: Document, ctx: Ctx) -> None:
        prefix = ctx.config.anchor_prefix
        body = doc.element.body
        for para in list(body.iter(_W_P)):
            runs = para.findall(_W_R)
            anchor_runs = [r for r in runs if _is_anchor_run(r, prefix)]
            if not anchor_runs:
                continue
            text_runs = [r for r in runs if _run_text(r)]
            if all(r in anchor_runs for r in text_runs):
                parent = para.getparent()
                if parent is not None:
                    parent.remove(para)
            else:
                for run in anchor_runs:
                    para.remove(run)


def ecepdi_docx_ops() -> list[DocxOp]:
    """docx_polish phase ops for ecepdi. StripAnchors is ALWAYS LAST."""
    return [CreateStyles(), SetParagraphStyle(),
            FixTable(), ClampImageWidths(), InsertSectionBreak(), StripAnchors()]
