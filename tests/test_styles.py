"""Styles engine tests (ticket 05): CLI seam + XML assertions on final DOCX.

Covers: default output matches every packaged ecepdi-default.yaml value,
snippet overrides deep-merge without disturbing siblings, named-style
(pStyle) assignment per anchor-delimited range, image paragraphs centered
with indent suppressed, headings H1-H5 carrying their configured styles.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
from snippet_docx import styles
from snippet_docx.cli import main
from snippet_docx.config import Config
from snippet_docx.strategies.ecepdi import EcepdiStrategy

DATA = Path(__file__).parent / "data"
STYLES_MD = DATA / "styles.md"
SNIPPET = DATA / "snippet-styles.yaml"
SNIPPET_OVERRIDE = DATA / "snippet-styles-override.yaml"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ALIGNMENT_VALS = {"justify": "both", "center": "center",
                  "left": "left", "right": "right"}


def _xml(docx: Path, member: str) -> ET.Element:
    with zipfile.ZipFile(docx) as zf:
        return ET.fromstring(zf.read(member))


def _styles_by_id(docx: Path) -> dict[str, ET.Element]:
    return {s.get(f"{W}styleId"): s
            for s in _xml(docx, "word/styles.xml").findall(f"{W}style")}


def _paragraphs(docx: Path) -> list[tuple[str, str, bool]]:
    """(pStyle val, concatenated text, has drawing) for every paragraph."""
    out = []
    for p in _xml(docx, "word/document.xml").iter(f"{W}p"):
        ppr = p.find(f"{W}pPr")
        pstyle = ppr.find(f"{W}pStyle") if ppr is not None else None
        val = pstyle.get(f"{W}val") if pstyle is not None else ""
        text = "".join(t.text or "" for t in p.iter(f"{W}t"))
        drawing = p.find(f".//{W}drawing") is not None
        out.append((val or "", text, drawing))
    return out


def _polished(md: Path, snippet: Path, tmp_path: Path,
              monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(DATA)  # figure.png resolves relative to the fixture
    draft_docx = tmp_path / "draft.docx"
    final = tmp_path / "final.docx"
    rc = main(["draft", str(md), "--snippet", str(snippet), "--out", str(draft_docx)])
    assert rc == 0
    rc2 = main(["polish", str(draft_docx), "--snippet", str(snippet),
                "--out", str(final)])
    assert rc2 == 0
    return final


def _attr(el: ET.Element | None, path: str, attr: str) -> str | None:
    if el is None:
        return None
    child = el.find(path)
    return child.get(f"{W}{attr}") if child is not None else None


# ---------------------------------------------------------------- defaults

def test_default_output_matches_every_packaged_value(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = _polished(STYLES_MD, SNIPPET, tmp_path, monkeypatch)
    by_id = _styles_by_id(final)
    defaults = styles.load_packaged_defaults()["style"]

    for name, spec in defaults.items():
        st = by_id.get(name)
        assert st is not None, f"named style {name!r} missing from styles.xml"
        assert st.get(f"{W}type") == "paragraph"
        rpr = st.find(f"{W}rPr")
        assert rpr is not None
        rfonts = rpr.find(f"{W}rFonts")
        assert rfonts.get(f"{W}ascii") == spec["english_font"]
        assert rfonts.get(f"{W}hAnsi") == spec["english_font"]
        assert rfonts.get(f"{W}eastAsia") == spec["chinese_font"]
        assert rpr.find(f"{W}sz").get(f"{W}val") == str(int(spec["font_size_pt"] * 2))
        assert rpr.find(f"{W}szCs").get(f"{W}val") == str(int(spec["font_size_pt"] * 2))
        # <w:b/> with no w:val means on; our engine writes val="0" for off
        b = rpr.find(f"{W}b")
        assert (b is not None and (b.get(f"{W}val") or "1") != "0") == spec["bold"]
        i = rpr.find(f"{W}i")
        assert (i is not None and (i.get(f"{W}val") or "1") != "0") == spec["italic"]

        ppr = st.find(f"{W}pPr")
        assert ppr is not None
        assert ppr.find(f"{W}jc").get(f"{W}val") == ALIGNMENT_VALS[spec["alignment"]]
        spacing = ppr.find(f"{W}spacing")
        assert spacing.get(f"{W}before") == str(int(spec["space_before_pt"] * 20))
        assert spacing.get(f"{W}after") == str(int(spec["space_after_pt"] * 20))
        if spec["line_spacing_rule"] == "exact":
            assert spacing.get(f"{W}line") == str(int(spec["line_spacing"] * 20))
            assert spacing.get(f"{W}lineRule") == "exact"
        else:
            assert spacing.get(f"{W}line") == str(round(spec["line_spacing"] * 240))
            assert spacing.get(f"{W}lineRule") == "auto"
        chars = round(spec["first_line_indent_pt"] / spec["font_size_pt"] * 100)
        ind = ppr.find(f"{W}ind")
        if chars > 0:
            assert ind is not None and ind.get(f"{W}firstLineChars") == str(chars)
        else:
            assert ind is None
        if name.startswith("heading") and name[-1].isdigit():
            assert ppr.find(f"{W}outlineLvl").get(f"{W}val") == str(int(name[-1]) - 1)

    # measured house-standard anchors, stated explicitly
    normal = by_id["normal_text"]
    assert _attr(normal, f"{W}rPr/{W}rFonts", "eastAsia") == "宋体"
    assert _attr(normal, f"{W}rPr/{W}rFonts", "ascii") == "Times New Roman"
    assert _attr(normal, f"{W}rPr/{W}sz", "val") == "24"          # 12 pt
    assert _attr(normal, f"{W}pPr/{W}spacing", "line") == "460"   # 23 pt exact
    assert _attr(normal, f"{W}pPr/{W}spacing", "lineRule") == "exact"
    assert _attr(normal, f"{W}pPr/{W}ind", "firstLineChars") == "200"  # 2 chars
    table_cap = by_id["table_caption"]
    assert _attr(table_cap, f"{W}pPr/{W}spacing", "before") == "100"  # 5 pt
    assert _attr(table_cap, f"{W}pPr/{W}spacing", "after") == "0"
    figure_cap = by_id["figure_caption"]
    assert _attr(figure_cap, f"{W}pPr/{W}spacing", "before") == "0"
    assert _attr(figure_cap, f"{W}pPr/{W}spacing", "after") == "100"  # 5 pt
    table = by_id["table"]
    assert _attr(table, f"{W}rPr/{W}sz", "val") == "18"            # 9 pt
    assert _attr(table, f"{W}pPr/{W}jc", "val") == "center"


def test_override_deep_merges_without_disturbing_siblings(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = _polished(STYLES_MD, SNIPPET_OVERRIDE, tmp_path, monkeypatch)
    by_id = _styles_by_id(final)
    assert _attr(by_id["heading2"], f"{W}rPr/{W}sz", "val") == "32"     # 16 pt
    assert _attr(by_id["heading2"], f"{W}rPr/{W}szCs", "val") == "32"
    # everything the override did not mention is untouched
    assert _attr(by_id["heading2"], f"{W}rPr/{W}rFonts", "eastAsia") == "宋体"
    assert by_id["heading2"].find(f"{W}rPr/{W}b") is not None           # still bold
    assert _attr(by_id["heading1"], f"{W}rPr/{W}sz", "val") == "24"
    assert _attr(by_id["normal_text"], f"{W}pPr/{W}spacing", "line") == "460"
    assert _attr(by_id["normal_text"], f"{W}pPr/{W}spacing", "lineRule") == "exact"
    assert _attr(by_id["table"], f"{W}rPr/{W}sz", "val") == "18"
    assert _attr(by_id["table_caption"], f"{W}pPr/{W}spacing", "before") == "100"
    # and the override is visible on the real heading paragraph
    h2 = next(v for v, t, _d in _paragraphs(final) if "二级标题" in t)
    assert h2 == "heading2"


# ------------------------------------------------------------ range assign

def test_pstyle_assignment_per_anchor_delimited_range(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = _polished(STYLES_MD, SNIPPET, tmp_path, monkeypatch)
    paras = _paragraphs(final)

    def style_of(substr: str) -> str:
        matches = [v for v, t, _d in paras if substr in t]
        assert matches, f"no paragraph contains {substr!r}"
        return matches[0]

    # body paragraphs -> normal_text
    assert style_of("正文第一段") == "normal_text"
    assert style_of("结尾正文段落") == "normal_text"
    # captions: table env (above its table) vs figure env (below its image)
    assert style_of("机位参数表") == "table_caption"
    assert style_of("机位布置") == "figure_caption"
    # table cell paragraphs -> table content style
    assert style_of("T01") == "table"
    assert style_of("7.7") == "table"
    assert style_of("容量") == "table"
    # list paragraphs -> list_item (numbering survives the restyle)
    assert style_of("列表项甲") == "list_item"
    assert style_of("列表项乙") == "list_item"
    # zero anchor residue
    assert not any("anchor:" in t for _v, t, _d in paras)


def test_headings_carry_configured_styles_h1_to_h5(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = _polished(STYLES_MD, SNIPPET, tmp_path, monkeypatch)
    paras = _paragraphs(final)

    def style_of(substr: str) -> str:
        matches = [v for v, t, _d in paras if substr in t]
        assert matches, f"no paragraph contains {substr!r}"
        return matches[0]

    assert style_of("一级标题") == "heading1"
    assert style_of("二级标题") == "heading2"
    assert style_of("三级标题") == "heading3"
    assert style_of("四级标题") == "heading4"
    assert style_of("五级标题") == "heading5"
    # no paragraph keeps a raw pandoc HeadingN reference
    assert not any(v.startswith("Heading") for v, _t, _d in paras)


def test_image_paragraph_centered_with_indent_suppressed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = _polished(STYLES_MD, SNIPPET, tmp_path, monkeypatch)
    paras = _paragraphs(final)
    images = [(v, t) for v, t, d in paras if d]
    assert len(images) == 1
    style_id, text = images[0]
    assert not text.strip()
    assert style_id == "figure_caption"
    # the assigned style is centered with no first-line indent
    by_id = _styles_by_id(final)
    assert _attr(by_id[style_id], f"{W}pPr/{W}jc", "val") == "center"
    assert by_id[style_id].find(f"{W}pPr/{W}ind") is None


def test_list_paragraphs_keep_numbering(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = _polished(STYLES_MD, SNIPPET, tmp_path, monkeypatch)
    for p in _xml(final, "word/document.xml").iter(f"{W}p"):
        ppr = p.find(f"{W}pPr")
        if ppr is None or ppr.find(f"{W}pStyle") is None:
            continue
        if ppr.find(f"{W}pStyle").get(f"{W}val") != "list_item":
            continue
        text = "".join(t.text or "" for t in p.iter(f"{W}t"))
        assert "列表项" in text
        assert ppr.find(f"{W}numPr") is not None  # bullet/number survives


def test_styles_are_named_pstyle_not_direct_run_formatting(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = _polished(STYLES_MD, SNIPPET, tmp_path, monkeypatch)
    # restyled body/caption/heading runs carry no direct rPr font overrides
    for p in _xml(final, "word/document.xml").iter(f"{W}p"):
        ppr = p.find(f"{W}pPr")
        if ppr is None or ppr.find(f"{W}pStyle") is None:
            continue
        if ppr.find(f"{W}pStyle").get(f"{W}val") not in {
                "normal_text", "table_caption", "figure_caption", "table",
                "heading1", "heading2", "heading3", "heading4", "heading5",
                "list_item"}:
            continue
        for run in p.findall(f"{W}r"):
            rpr = run.find(f"{W}rPr")
            if rpr is None:
                continue
            # pandoc may leave <w:rFonts w:hint="eastAsia"/> (no font names);
            # actual font/size names on the run would fight the named style
            rfonts = rpr.find(f"{W}rFonts")
            if rfonts is not None:
                assert not [a for a in rfonts.attrib if a != f"{W}hint"], \
                    "direct rFonts on styled run"
            assert rpr.find(f"{W}sz") is None, "direct sz on styled run"


# ----------------------------------------------------------- merge seam

def test_resolve_styles_wraps_bare_entry_overrides() -> None:
    strategy = EcepdiStrategy()
    config = Config(strategy="ecepdi", prefix=(2,),
                    styles={"heading2": {"font_size_pt": 16}})
    entries = styles.resolve_styles(strategy, config)
    assert entries["heading2"]["font_size_pt"] == 16
    assert entries["heading2"]["chinese_font"] == "宋体"   # sibling value kept
    assert entries["normal_text"]["line_spacing"] == 23    # other entry kept


def test_resolve_styles_merges_wrapped_overrides() -> None:
    strategy = EcepdiStrategy()
    config = Config(strategy="ecepdi", prefix=(2,),
                    styles={"style": {"heading2": {"font_size_pt": 16}}})
    entries = styles.resolve_styles(strategy, config)
    assert entries["heading2"]["font_size_pt"] == 16
    assert entries["heading1"]["font_size_pt"] == 12


def test_packaged_defaults_roundtrip_through_engine() -> None:
    # every packaged entry converts to a full style spec without error
    strategy = EcepdiStrategy()
    config = Config(strategy="ecepdi", prefix=(2,), styles={})
    entries = styles.resolve_styles(strategy, config)
    assert set(entries) == {"heading1", "heading2", "heading3", "heading4",
                            "heading5", "normal_text", "table_caption",
                            "figure_caption", "table", "list_item"}
    for spec in entries.values():
        assert styles.first_line_chars(spec) >= 0
        styles.line_spacing_attrs(spec["line_spacing_rule"],
                                  spec["line_spacing"])
