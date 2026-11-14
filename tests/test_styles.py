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
from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from snippet_docx import styles
from snippet_docx.cli import main
from snippet_docx.config import Config
from snippet_docx.ops_docx import CreateStyles, SetParagraphStyle
from snippet_docx.pipeline import Ctx
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
    emitted = tmp_path / "anchored.md"
    rc = main(["draft", str(md), "--snippet", str(snippet), "--out", str(draft_docx),
               "--emit-md", str(emitted)])
    assert rc == 0
    rc2 = main(["polish", str(draft_docx), "--snippet", str(snippet),
                "--md", str(emitted), "--out", str(final)])
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
        line, rule = styles.line_spacing_attrs(
            spec["line_spacing_rule"], spec["line_spacing"])
        assert spacing.get(f"{W}line") == str(line)
        assert spacing.get(f"{W}lineRule") == rule
        chars = round(spec["first_line_indent_pt"] / spec["font_size_pt"] * 100)
        ind = ppr.find(f"{W}ind")
        if chars > 0 or spec.get("reset_indentation"):
            assert ind is not None and ind.get(f"{W}firstLineChars") == str(chars)
            if spec.get("reset_indentation"):
                for attr in ("left", "right", "start", "end", "hanging",
                             "leftChars", "rightChars", "hangingChars"):
                    assert ind.get(f"{W}{attr}") == "0"
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
    assert style_id != "figure_caption"
    # The independent image role is centered and explicitly indent-free.
    by_id = _styles_by_id(final)
    assert _attr(by_id[style_id], f"{W}pPr/{W}jc", "val") == "center"
    ind = by_id[style_id].find(f"{W}pPr/{W}ind")
    assert ind is not None
    assert all(value == "0" for value in ind.attrib.values())


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
    known = styles.load_packaged_defaults()["style"]
    # restyled body/caption/heading runs carry no direct rPr font overrides
    for p in _xml(final, "word/document.xml").iter(f"{W}p"):
        ppr = p.find(f"{W}pPr")
        if ppr is None or ppr.find(f"{W}pStyle") is None:
            continue
        if ppr.find(f"{W}pStyle").get(f"{W}val") not in known:
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
    assert entries == styles.load_packaged_defaults()["style"]
    for spec in entries.values():
        assert styles.first_line_chars(spec) >= 0
        styles.line_spacing_attrs(spec["line_spacing_rule"],
                                  spec["line_spacing"])


@pytest.mark.parametrize(("rule", "value", "expected"), [
    ("exact", 13.25, (265, "exact")),
    ("atLeast", 13.25, (265, "atLeast")),
    ("auto", 1.25, (300, "auto")),
])
def test_line_spacing_units(rule: str, value: float,
                            expected: tuple[int, str]) -> None:
    assert styles.line_spacing_attrs(rule, value) == expected


def test_unknown_leading_rule_rejected() -> None:
    with pytest.raises(ValueError, match="auto\\|exact\\|atLeast"):
        styles.line_spacing_attrs("minimum", 12)


@pytest.mark.parametrize("role", [
    "normal_text", "heading2", "list_item", "table_caption", "table",
])
def test_math_keeps_role_and_direct_properties_while_exact_grows(role: str) -> None:
    doc = Document()
    strategy = EcepdiStrategy()
    config = Config(strategy="ecepdi", prefix=(2,), styles={})
    ctx = Ctx(config=config, strategy=strategy)
    CreateStyles()(doc, ctx)
    para = (doc.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0]
            if role == "table" else doc.add_paragraph())
    para.add_run("mixed prose ")
    para._p.append(etree.Element(qn("m:oMath")))
    ppr = para._p.get_or_add_pPr()
    if role == "heading2":
        para.style = "Heading 2"
    elif role == "table_caption":
        para.style = role
    elif role == "list_item":
        numpr = ppr.get_or_add_numPr()
        etree.SubElement(numpr, qn("w:numId")).set(qn("w:val"), "4")
    spacing = ppr.get_or_add_spacing()
    for attr, value in {"before": "71", "after": "93", "line": "201",
                        "lineRule": "exact", "beforeAutospacing": "0"}.items():
        spacing.set(qn(f"w:{attr}"), value)
    sectpr = etree.SubElement(ppr, qn("w:sectPr"))
    etree.SubElement(sectpr, qn("w:type")).set(qn("w:val"), "continuous")
    preserved = etree.tostring(sectpr)
    SetParagraphStyle()(doc, ctx)
    assert ppr.find(qn("w:pStyle")).get(qn("w:val")) == role
    assert spacing.get(qn("w:line")) == "201"
    assert spacing.get(qn("w:lineRule")) == "atLeast"
    assert spacing.get(qn("w:before")) == "71"
    assert spacing.get(qn("w:after")) == "93"
    assert spacing.get(qn("w:beforeAutospacing")) == "0"
    assert etree.tostring(sectpr) == preserved
    assert para._p.find(qn("m:oMath")) is not None
    if role == "list_item":
        assert ppr.find(f"{qn('w:numPr')}/{qn('w:numId')}").get(qn("w:val")) == "4"


@pytest.mark.parametrize("source", ["style", "base", "defaults"])
def test_math_resolves_partial_direct_spacing_and_inherited_floor(source: str) -> None:
    doc = Document()
    strategy = EcepdiStrategy()
    ctx = Ctx(config=Config(strategy="ecepdi", prefix=(2,), styles={}),
              strategy=strategy)
    CreateStyles()(doc, ctx)
    para = doc.add_paragraph("inline ")
    para._p.append(etree.Element(qn("m:oMath")))
    direct = para._p.get_or_add_pPr().get_or_add_spacing()
    direct.set(qn("w:before"), "77")
    normal = doc.styles["normal_text"].element
    normal_ppr = normal.find(qn("w:pPr"))
    normal_spacing = normal_ppr.find(qn("w:spacing"))
    normal_spacing.attrib.pop(qn("w:line"))
    normal_spacing.attrib.pop(qn("w:lineRule"))
    if source == "style":
        inherited = normal_spacing
    elif source == "base":
        inherited = doc.styles["Normal"].element.get_or_add_pPr().get_or_add_spacing()
    else:
        inherited = doc.styles.element.find(
            f"{qn('w:docDefaults')}/{qn('w:pPrDefault')}/{qn('w:pPr')}"
            f"/{qn('w:spacing')}")
    inherited.set(qn("w:line"), "317")
    inherited.set(qn("w:lineRule"), "exact")
    # Direct rule and inherited numeric floor must resolve independently.
    direct.set(qn("w:lineRule"), "exact")
    SetParagraphStyle()(doc, ctx)
    assert direct.get(qn("w:lineRule")) == "atLeast"
    assert direct.get(qn("w:line")) == "317"
    assert direct.get(qn("w:before")) == "77"


@pytest.mark.parametrize("rule", ["auto", "atLeast"])
def test_safe_math_leading_and_plain_exact_paragraph_unchanged(rule: str) -> None:
    doc = Document()
    strategy = EcepdiStrategy()
    ctx = Ctx(config=Config(strategy="ecepdi", prefix=(2,), styles={}),
              strategy=strategy)
    CreateStyles()(doc, ctx)
    math = doc.add_paragraph("math ")
    math._p.append(etree.Element(qn("m:oMath")))
    spacing = math._p.get_or_add_pPr().get_or_add_spacing()
    spacing.set(qn("w:line"), "333")
    spacing.set(qn("w:lineRule"), rule)
    plain = doc.add_paragraph("plain")
    plain_spacing = plain._p.get_or_add_pPr().get_or_add_spacing()
    plain_spacing.set(qn("w:line"), "222")
    plain_spacing.set(qn("w:lineRule"), "exact")
    before = etree.tostring(plain_spacing)
    SetParagraphStyle()(doc, ctx)
    assert spacing.get(qn("w:line")) == "333"
    assert spacing.get(qn("w:lineRule")) == rule
    assert etree.tostring(plain_spacing) == before


def test_configured_side_indents_override_character_aliases_consistently() -> None:
    doc = Document()
    styles.define_paragraph_style(doc, "object_layout", {
        "font_size_pt": 12, "reset_indentation": True,
        "left_indent_pt": 12, "right_indent_pt": 6,
        "first_line_indent_pt": 0,
    })
    ind = doc.styles["object_layout"].element.find(
        f"{qn('w:pPr')}/{qn('w:ind')}")
    for alias in ("left", "start"):
        assert ind.get(qn(f"w:{alias}")) == "240"
        assert ind.get(qn(f"w:{alias}Chars")) == "100"
    for alias in ("right", "end"):
        assert ind.get(qn(f"w:{alias}")) == "120"
        assert ind.get(qn(f"w:{alias}Chars")) == "50"
    assert ind.get(qn("w:firstLineChars")) == "0"
    assert ind.get(qn("w:hangingChars")) == "0"


def test_positive_first_line_override_reaches_reset_image_paragraph(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snippet = tmp_path / "snippet.yaml"
    snippet.write_text(
        "strategy: ecepdi\n"
        "section:\n"
        "  prefix: [2]\n"
        "styles:\n"
        "  figure_image:\n"
        "    first_line_indent_pt: 12\n"
        "    left_indent_pt: 12\n"
        "    right_indent_pt: 6\n",
        encoding="utf-8",
    )
    final = _polished(STYLES_MD, snippet, tmp_path, monkeypatch)
    image = next(p for p in _xml(final, "word/document.xml").iter(f"{W}p")
                 if p.find(f".//{W}drawing") is not None)
    ppr = image.find(f"{W}pPr")
    style_id = ppr.find(f"{W}pStyle").get(f"{W}val")
    ind = _styles_by_id(final)[style_id].find(f"{W}pPr/{W}ind")
    assert ind is not None
    assert ind.get(f"{W}firstLineChars") == "100"
    # Even zero hanging values take precedence over the first-line override.
    for attr in ("hanging", "hangingChars"):
        assert ind.get(f"{W}{attr}") is None
    for alias, twips, chars in (("left", "240", "100"),
                                ("start", "240", "100"),
                                ("right", "120", "50"),
                                ("end", "120", "50")):
        assert ind.get(f"{W}{alias}") == twips
        assert ind.get(f"{W}{alias}Chars") == chars
    # The consumer copies the role's indentation onto the actual image paragraph.
    direct_ind = ppr.find(f"{W}ind")
    assert direct_ind is not None
    assert direct_ind.attrib == ind.attrib
