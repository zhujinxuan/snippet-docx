"""End-to-end smoke test (ticket 10, ToolSpec §8.3): the Q18 fixture.

One snippet exercises the whole pipeline — draft (anchors parsed/validated,
numbering executed md-side, anchored md emitted) then polish (named styles,
pandoc-defect repair, landscape section break, anchor strip) — and is
asserted at the CLI seam, on the emitted markdown, and on the final DOCX
XML. The officecli visual pass on the same final DOCX (wide page rendered
horizontal, table unclipped) is run manually and recorded in the ticket
report; here the geometry is proven via sectPr + tblGrid.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from snippet_docx.cli import main

DATA = Path(__file__).parent / "data"
E2E_MD = DATA / "e2e.md"
E2E_YAML = DATA / "e2e.yaml"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A4_SHORT, A4_LONG = 11906, 16838
SIX_EDGES = ("top", "left", "bottom", "right", "insideH", "insideV")


# ---------------------------------------------------------------- helpers


def _document_xml(docx: Path) -> str:
    with zipfile.ZipFile(docx) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def _plain_text(docx: Path) -> str:
    """Tag-stripped document text (adjacent runs concatenate)."""
    return re.sub(r"<[^>]+>", "", _document_xml(docx))


def _xml(docx: Path, member: str = "word/document.xml") -> ET.Element:
    with zipfile.ZipFile(docx) as zf:
        return ET.fromstring(zf.read(member))


def _texts(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(f"{W}t"))


def _sectprs(root: ET.Element) -> list[ET.Element]:
    """All sectPr elements in document order (paragraph-level, then body)."""
    return list(root.iter(f"{W}sectPr"))


def _styles_by_id(docx: Path) -> dict[str, ET.Element]:
    return {s.get(f"{W}styleId"): s
            for s in _xml(docx, "word/styles.xml").findall(f"{W}style")}


def _attr(el: ET.Element | None, path: str, attr: str) -> str | None:
    if el is None:
        return None
    child = el.find(path)
    return child.get(f"{W}{attr}") if child is not None else None


def _body_children(docx: Path) -> list[ET.Element]:
    return list(_xml(docx).find(f"{W}body"))


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
         emit: bool = True) -> tuple[Path, Path, Path | None]:
    """draft + polish the e2e fixture through the CLI seam."""
    monkeypatch.chdir(DATA)  # e2e-figure.png resolves relative to the fixture
    draft_docx = tmp_path / "draft.docx"
    emit_md = tmp_path / "anchored.md" if emit else None
    argv = ["draft", str(E2E_MD), "--snippet", str(E2E_YAML),
            "--out", str(draft_docx)]
    if emit_md is not None:
        argv += ["--emit-md", str(emit_md)]
    assert main(argv) == 0
    final = tmp_path / "final.docx"
    assert main(["polish", str(draft_docx), "--snippet", str(E2E_YAML),
                 "--out", str(final)]) == 0
    return draft_docx, final, emit_md


# ------------------------------------------------------- CLI run + warnings


def test_run_exits_zero_with_both_expected_warnings(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    draft_docx, final, emit_md = _run(tmp_path, monkeypatch)
    assert draft_docx.is_file() and final.is_file()
    assert emit_md is not None and emit_md.is_file()
    err = capsys.readouterr().err
    assert "[WARN] captionless-env:" in err      # 裸表 table env, no caption
    assert "[WARN] cross-subsection:" in err     # second root-level heading
    assert "[ERROR]" not in err                  # warnings don't fail the build


# --------------------------------------------------------- emitted md


def test_anchored_md_numbers_placement_and_substitution(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _draft_docx, _final, emit_md = _run(tmp_path, monkeypatch)
    assert emit_md is not None
    emitted = emit_md.read_text(encoding="utf-8")

    # captions renumbered: stale 表 9.9-9 replaced, second table follows at -2
    assert "表 2.2-1 月度发电量对比" in emitted
    assert "表 2.2-2 常规参数表" in emitted
    assert "9.9-9" not in emitted
    # figure numbered below its section, caption placed below the image
    assert "图 2.2-1 风机布置示意" in emitted

    # placement visible in the md: table captions above their rows, figure
    # caption below the image (both were typed elsewhere in the fixture)
    assert emitted.index("表 2.2-1 月度发电量对比") < emitted.index("101")
    assert emitted.index("表 2.2-2 常规参数表") < emitted.index("T01")
    assert emitted.index("](e2e-figure.png)") < emitted.index("图 2.2-1 风机布置示意")

    # headings baked: root fixed at the prefix, level-3 counter starts at 3
    assert "2.2 风资源分析" in emitted
    assert "2.2.3 湍流强度" in emitted

    # inline global var substituted with the current section number
    assert "本小节为 2.2.3 编号下的端到端冒烟段落。" in emitted
    assert "anchor:section" not in emitted


# ------------------------------------------------------ final DOCX: content


def test_final_docx_captions_and_placement(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _draft_docx, final, _emit = _run(tmp_path, monkeypatch)
    children = _body_children(final)

    wide_tbl = next(i for i, el in enumerate(children)
                    if el.tag == f"{W}tbl" and "101" in _texts(el))
    normal_tbl = next(i for i, el in enumerate(children)
                      if el.tag == f"{W}tbl" and "T01" in _texts(el))
    bare_tbl = next(i for i, el in enumerate(children)
                    if el.tag == f"{W}tbl" and "裸表" in _texts(el))
    wide_cap = next(i for i, el in enumerate(children)
                    if "表 2.2-1 月度发电量对比" in _texts(el))
    normal_cap = next(i for i, el in enumerate(children)
                      if "表 2.2-2 常规参数表" in _texts(el))
    image = next(i for i, el in enumerate(children)
                 if el.tag == f"{W}p" and el.find(f".//{W}drawing") is not None)
    figure_cap = next(i for i, el in enumerate(children)
                      if "图 2.2-1 风机布置示意" in _texts(el))

    # table captions immediately above their tables; the figure caption sits
    # below the image (pandoc emits the alt text as an intervening Image
    # Caption paragraph, so ordering — not adjacency — is the contract)
    assert wide_cap == wide_tbl - 1
    assert normal_cap == normal_tbl - 1
    assert image < figure_cap
    # the captionless table is still there, unnumbered
    assert "裸表" in _texts(children[bare_tbl])
    assert "9.9-9" not in _document_xml(final)

    # headings baked in the document text
    text = _plain_text(final)
    assert "2.2 风资源分析" in text
    assert "2.2.3 湍流强度" in text


# ---------------------------------------------------- final DOCX: sections


def test_final_docx_landscape_page_between_portrait_pages(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _draft_docx, final, _emit = _run(tmp_path, monkeypatch)
    root = _xml(final)
    sects = _sectprs(root)
    assert len(sects) == 3                       # portrait / landscape / portrait

    portrait_close, landscape_close, body_sect = sects
    assert _attr(portrait_close, f"{W}pgSz", "w") == str(A4_SHORT)
    assert _attr(portrait_close, f"{W}pgSz", "h") == str(A4_LONG)
    assert _attr(portrait_close, f"{W}pgSz", "orient") is None
    assert _attr(body_sect, f"{W}pgSz", "w") == str(A4_SHORT)  # after portrait

    assert _attr(landscape_close, f"{W}pgSz", "w") == str(A4_LONG)   # swapped
    assert _attr(landscape_close, f"{W}pgSz", "h") == str(A4_SHORT)
    assert _attr(landscape_close, f"{W}pgSz", "orient") == "landscape"

    margins = [dict(s.find(f"{W}pgMar").attrib) for s in sects]
    assert margins[0] == margins[1] == margins[2]              # same margins

    # the wide table and its caption sit INSIDE the landscape section
    children = list(root.find(f"{W}body"))
    wide_tbl = next(i for i, el in enumerate(children)
                    if el.tag == f"{W}tbl" and "101" in _texts(el))
    portrait_i = children.index(next(
        el for el in children if el.find(f"{W}pPr/{W}sectPr") is not None
        and el.find(f"{W}pPr/{W}sectPr") is portrait_close))
    landscape_i = children.index(next(
        el for el in children if el.find(f"{W}pPr/{W}sectPr") is not None
        and el.find(f"{W}pPr/{W}sectPr") is landscape_close))
    assert portrait_i < wide_tbl < landscape_i
    # pages before and after stay portrait: the normal table follows the break
    normal_tbl = next(i for i, el in enumerate(children)
                      if el.tag == f"{W}tbl" and "T01" in _texts(el))
    assert normal_tbl > landscape_i


def test_wide_table_needs_and_fits_landscape_width(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _draft_docx, final, _emit = _run(tmp_path, monkeypatch)
    root = _xml(final)
    sects = _sectprs(root)
    portrait, landscape, _body = sects

    def text_width(sect: ET.Element) -> int:
        sz, mar = sect.find(f"{W}pgSz"), sect.find(f"{W}pgMar")
        return (int(sz.get(f"{W}w"))
                - int(mar.get(f"{W}left")) - int(mar.get(f"{W}right")))

    wide = next(el for el in root.iter(f"{W}tbl") if "101" in _texts(el))
    cols = [int(c.get(f"{W}w")) for c in wide.iter(f"{W}gridCol")]
    assert sum(cols) > text_width(portrait)      # genuinely needs landscape
    assert sum(cols) <= text_width(landscape)    # unclipped on the wide page


# ---------------------------------------------------- final DOCX: residue


def test_final_docx_zero_anchor_residue_and_no_numpr(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _draft_docx, final, _emit = _run(tmp_path, monkeypatch)
    xml = _document_xml(final)
    assert "anchor:" not in xml                  # zero residue (raw XML)
    assert "numPr" not in xml                    # numbers are baked text, Q5
    # block anchors DID survive draft (transport mechanism), then were stripped
    assert "anchor:begin:table" in _document_xml(_draft_docx)


# ------------------------------------------------------ final DOCX: styles


def test_final_docx_styles_match_merged_config(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _draft_docx, final, _emit = _run(tmp_path, monkeypatch)
    by_id = _styles_by_id(final)

    # body: 12 pt 宋体 / Times New Roman, 23 pt exact leading, 2-char indent
    normal = by_id["normal_text"]
    assert _attr(normal, f"{W}rPr/{W}rFonts", "eastAsia") == "宋体"
    assert _attr(normal, f"{W}rPr/{W}rFonts", "ascii") == "Times New Roman"
    assert _attr(normal, f"{W}rPr/{W}rFonts", "hAnsi") == "Times New Roman"
    assert _attr(normal, f"{W}rPr/{W}sz", "val") == "24"
    assert _attr(normal, f"{W}pPr/{W}spacing", "line") == "460"
    assert _attr(normal, f"{W}pPr/{W}spacing", "lineRule") == "exact"
    assert _attr(normal, f"{W}pPr/{W}ind", "firstLineChars") == "200"

    # caption spacing asymmetry: table caption hugs its table from above,
    # figure caption from below
    assert _attr(by_id["table_caption"], f"{W}pPr/{W}spacing", "before") == "100"
    assert _attr(by_id["table_caption"], f"{W}pPr/{W}spacing", "after") == "0"
    assert _attr(by_id["figure_caption"], f"{W}pPr/{W}spacing", "before") == "0"
    assert _attr(by_id["figure_caption"], f"{W}pPr/{W}spacing", "after") == "100"

    # 9 pt table cells
    assert _attr(by_id["table"], f"{W}rPr/{W}sz", "val") == "18"

    # ranges: named styles actually assigned to the right paragraphs
    children = _body_children(final)

    def pstyle_at(text: str) -> str:
        el = next(c for c in children if text in _texts(c))
        return el.find(f"{W}pPr/{W}pStyle").get(f"{W}val")

    assert pstyle_at("表 2.2-1 月度发电量对比") == "table_caption"
    assert pstyle_at("图 2.2-1 风机布置示意") == "figure_caption"
    assert pstyle_at("2.2 风资源分析") == "heading2"
    assert pstyle_at("2.2.3 湍流强度") == "heading3"
    assert pstyle_at("端到端冒烟夹具") == "normal_text"
    # table cell paragraphs carry the 9 pt content style
    wide = next(el for el in children if el.tag == f"{W}tbl" and "101" in _texts(el))
    cell_p = wide.find(f"{W}tr/{W}tc/{W}p")
    assert cell_p.find(f"{W}pPr/{W}pStyle").get(f"{W}val") == "table"


def test_final_docx_table_borders_all_six_edges(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _draft_docx, final, _emit = _run(tmp_path, monkeypatch)
    root = _xml(final)
    tables = [el for el in root.find(f"{W}body") if el.tag == f"{W}tbl"]
    assert len(tables) == 3                      # wide + normal + captionless
    for tbl in tables:
        borders = tbl.find(f"{W}tblPr/{W}tblBorders")
        assert borders is not None
        for edge in SIX_EDGES:
            el = borders.find(f"{W}{edge}")
            assert el is not None, f"{edge} border missing"
            assert el.get(f"{W}val") == "single"
            assert el.get(f"{W}sz") == "4"
            assert el.get(f"{W}color") == "000000"
