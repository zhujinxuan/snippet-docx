"""Native-object preservation and effective allocation through draft -> polish.

These synthetic structural regressions do not claim rendered Word separation.
"""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from snippet_docx.cli import main
from snippet_docx.pandoc_ast import md_to_ast

DATA = Path(__file__).parent / "data"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _xml(path: Path, member: str = "word/document.xml") -> ET.Element:
    with zipfile.ZipFile(path) as package:
        return ET.fromstring(package.read(member))


def _tree(node: ET.Element) -> tuple:
    return (node.tag, tuple(sorted(node.attrib.items())), node.text or "",
            tuple(_tree(child) for child in node))


def _text(node: ET.Element) -> str:
    return "".join(child.text or "" for child in node.iter(f"{W}t"))


def _body(path: Path) -> list[ET.Element]:
    return list(_xml(path).find(f"{W}body"))


def _paragraphs(path: Path) -> list[ET.Element]:
    return list(_xml(path).iter(f"{W}p"))


def _style(paragraph: ET.Element) -> str:
    node = paragraph.find(f"{W}pPr/{W}pStyle")
    return node.get(f"{W}val", "") if node is not None else "Normal"


def _effective(path: Path, paragraph: ET.Element, tag: str) -> dict[str, str]:
    """Resolve individual attributes: defaults < basedOn chain < direct pPr."""
    root = _xml(path, "word/styles.xml")
    by_id = {s.get(f"{W}styleId"): s for s in root.findall(f"{W}style")}
    layers = [root.find(f"{W}docDefaults/{W}pPrDefault/{W}pPr")]
    chain = []
    name = _style(paragraph)
    while name:
        assert name not in [key for key, _ in chain], "style inheritance cycle"
        style = by_id.get(name)
        if style is None:
            break
        chain.append((name, style.find(f"{W}pPr")))
        parent = style.find(f"{W}basedOn")
        name = parent.get(f"{W}val") if parent is not None else None
    layers.extend(ppr for _, ppr in reversed(chain))
    layers.append(paragraph.find(f"{W}pPr"))
    result = {}
    for ppr in layers:
        node = ppr.find(f"{W}{tag}") if ppr is not None else None
        if node is not None:
            result.update({key.removeprefix(W): value for key, value in node.attrib.items()})
    return result


def _zero_indents(path: Path, paragraph: ET.Element) -> None:
    indents = _effective(path, paragraph, "ind")
    assert all(int(indents.get(key, "0")) == 0 for key in (
        "left", "right", "start", "end", "firstLine", "firstLineChars",
        "hanging", "hangingChars", "leftChars", "rightChars")), indents
    assert _effective(path, paragraph, "jc")["val"] == "center"


def _draft(tmp_path: Path, markdown: str, *, strategy: str = "ecepdi",
           overrides: str = "") -> tuple[Path, Path, Path]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    shutil.copyfile(DATA / "figure.png", inputs / "relative.png")
    source = inputs / "source.md"
    source.write_text(markdown, encoding="utf-8")
    snippet = inputs / "snippet.yaml"
    snippet.write_text(f"strategy: {strategy}\nsection:\n  prefix: [2, 2]\n{overrides}",
                       encoding="utf-8")
    draft = tmp_path / "draft.docx"
    emitted = tmp_path / "anchored.md"
    assert main(["draft", str(source), "--snippet", str(snippet),
                 "--out", str(draft), "--emit-md", str(emitted)]) == 0
    return draft, emitted, snippet


def _polish(draft: Path, emitted: Path, snippet: Path) -> Path:
    final = draft.parent / "final.docx"
    assert main(["polish", str(draft), "--snippet", str(snippet),
                 "--md", str(emitted), "--out", str(final)]) == 0
    return final


def _set(parent, tag: str, **attrs: str):
    node = parent.find(qn(tag))
    if node is None:
        node = OxmlElement(tag)
        parent.append(node)
    for key, value in attrs.items():
        node.set(qn(f"w:{key}"), value)
    return node


def _images(path: Path) -> list[ET.Element]:
    return [p for p in _paragraphs(path) if p.find(f".//{W}drawing") is not None]


def _assert_image_payload(before: Path, after: Path) -> None:
    original, final = _images(before), _images(after)
    assert len(original) == len(final)
    for old, new in zip(original, final, strict=True):
        # Includes inline, both extent representations, docPr ALT and blip r:embed.
        assert [_tree(n) for n in old.iter(f"{W}drawing")] == [
            _tree(n) for n in new.iter(f"{W}drawing")]
        assert [_tree(n) for n in old.iter(f"{W}rPr")] == [
            _tree(n) for n in new.iter(f"{W}rPr")]
        assert [n.attrib for n in old.iter(f"{W}hyperlink")] == [
            n.attrib for n in new.iter(f"{W}hyperlink")]
        assert len(list(new.iter(f"{WP}inline"))) == 1
        assert new.find(f".//{WP}anchor") is None
        assert new.find(f".//{WP}extent") is not None
        assert new.find(f".//{A}xfrm/{A}ext") is not None
    for path in (before, after):
        assert _xml(path).find(f".//{W}tblpPr") is None
    with zipfile.ZipFile(before) as old_zip, zipfile.ZipFile(after) as new_zip:
        media = [name for name in old_zip.namelist() if name.startswith("word/media/")]
        assert media
        assert {name: old_zip.read(name) for name in media} == {
            name: new_zip.read(name) for name in media}
    old_rels = _xml(before, "word/_rels/document.xml.rels")
    new_rels = _xml(after, "word/_rels/document.xml.rels")
    def relevant(root: ET.Element) -> set[tuple]:
        return {tuple(sorted(n.attrib.items())) for n in root
                if n.get("Type", "").endswith(("/image", "/hyperlink"))}
    assert relevant(old_rels) == relevant(new_rels)
    assert any(n.get("Target") == "https://example.com/layout"
               and n.get("TargetMode") == "External" for n in new_rels)


IMAGE_MD = """Plain image control.

`anchor:begin:table`

| Boundary |
|----------|
| lower border |

Table: Boundary table

`anchor:end:table`

`anchor:begin:figure`

![Boundary caption](relative.png){width=3cm}

`anchor:end:figure`

`anchor:begin:figure`

![](relative.png){width=3cm}

`anchor:end:figure`

`anchor:begin:landscape`

`anchor:begin:figure`

[![Linked caption](relative.png){width=3cm}](https://example.com/layout)

`anchor:end:figure`

`anchor:end:landscape`

After landscape.
"""


@pytest.mark.parametrize("strategy", ["ecepdi", "testhouse"])
def test_image_caption_overrides_are_independent_and_payload_survives(
        tmp_path: Path, strategy: str) -> None:
    markdown = IMAGE_MD
    if strategy == "testhouse":
        # This plugin deliberately registers only table and figure environments.
        markdown = markdown.replace("`anchor:begin:landscape`\n", "").replace(
            "`anchor:end:landscape`\n", "")
    draft, emitted, snippet = _draft(tmp_path, markdown, strategy=strategy, overrides="""
styles:
  style:
    figure_image:
      space_before_pt: 11
      space_after_pt: 13
      line_spacing_rule: atLeast
      line_spacing: 29
    figure_caption:
      space_before_pt: 17
      space_after_pt: 19
      line_spacing_rule: exact
      line_spacing: 21
""")
    doc = Document(draft)
    for p in doc.element.body.iter(qn("w:p")):
        if p.find(f".//{qn('w:drawing')}") is not None:
            _set(p.get_or_add_pPr(), "w:ind", left="720", right="360",
                 firstLine="240", firstLineChars="200", hanging="120", hangingChars="100")
            for run in p.iter(qn("w:r")):
                _set(run.get_or_add_rPr(), "w:b")
                _set(run.get_or_add_rPr(), "w:color", val="1267AB")
    doc.save(draft)
    final = _polish(draft, emitted, snippet)
    _assert_image_payload(draft, final)
    images = _images(final)
    captions = [p for p in _paragraphs(final)
                if _text(p).endswith(("Boundary caption", "Linked caption"))
                and p.find(f".//{W}drawing") is None]
    assert len(captions) == 2  # the captionless image consumes no number
    for image in images:
        _zero_indents(final, image)
        assert _effective(final, image, "spacing") == {
            "before": "220", "after": "260", "line": "580", "lineRule": "atLeast"}
        assert _style(image) not in {_style(p) for p in captions}
    for caption in captions:
        assert _effective(final, caption, "spacing") == {
            "before": "340", "after": "380", "line": "420", "lineRule": "exact"}
    children = _body(final)
    table_at = next(i for i, p in enumerate(children) if p.tag == f"{W}tbl")
    first_image_at = next(i for i, p in enumerate(children)
                          if p.find(f".//{W}drawing") is not None)
    if strategy == "ecepdi":
        assert first_image_at == table_at + 1  # no blank table/image spacer
        assert _text(children[first_image_at + 1]) == "图 2.2-1 Boundary caption"
        assert [_text(p) for p in captions] == [
            "图 2.2-1 Boundary caption", "图 2.2-2 Linked caption"]
    else:
        assert _text(children[table_at + 1]) == "Table 2-1: Boundary table"
        assert _text(children[first_image_at - 1]) == "Figure 2-1: Boundary caption"
        assert [_text(p) for p in captions] == [
            "Figure 2-1: Boundary caption", "Figure 2-2: Linked caption"]
    def nonstructural_blanks(path: Path) -> list[ET.Element]:
        return [p for p in _body(path) if p.tag == f"{W}p"
                and not _text(p).strip()
                and p.find(f".//{W}drawing") is None
                and p.find(f".//{M}oMath") is None
                and p.find(f"{W}pPr/{W}sectPr") is None]

    # Section carriers are structural; any preexisting Pandoc blank is not a
    # license for polish to add another visual spacer at an object boundary.
    assert len(nonstructural_blanks(final)) <= len(nonstructural_blanks(draft)), [
        ET.tostring(p, encoding="unicode") for p in nonstructural_blanks(final)]
    if strategy == "ecepdi":
        linked_at = next(i for i, p in enumerate(children)
                         if p.find(f".//{W}hyperlink") is not None)
        carrier = next(p for p in children[linked_at:]
                       if p.find(f"{W}pPr/{W}sectPr") is not None)
        assert carrier.find(f"{W}pPr/{W}sectPr/{W}pgSz").get(f"{W}orient") == "landscape"


def test_default_image_separation_and_direct_exact_floor(tmp_path: Path) -> None:
    draft, emitted, snippet = _draft(tmp_path, IMAGE_MD)
    doc = Document(draft)
    for p in doc.element.body.iter(qn("w:p")):
        if p.find(f".//{qn('w:drawing')}") is not None:
            _set(p.get_or_add_pPr(), "w:spacing", line="200", lineRule="exact")
    doc.save(draft)
    final = _polish(draft, emitted, snippet)
    for p in _images(final):
        spacing = _effective(final, p, "spacing")
        assert (spacing["line"], spacing["lineRule"]) == ("200", "atLeast")
        assert int(spacing["before"]) > 0 and int(spacing["after"]) > 0
        _zero_indents(final, p)
    plain = next(p for p in _paragraphs(final) if _text(p) == "Plain image control.")
    assert _effective(final, plain, "spacing")["lineRule"] == "exact"


MATH_MD = r"""# Heading $h^{2}$

Plain control before.

Inline fraction $\frac{a+b}{c+d}$ ends here.

Wrapped superscript $x^{n+1}+y^{2}$ shares ordinary prose with enough repeated
words to wrap naturally in a report: ordinary prose ordinary prose ordinary
prose ordinary prose ordinary prose ordinary prose ordinary prose.

1. List math $\frac{u}{v}$.
2. Plain list control.

`anchor:begin:table`

| Role | Formula |
|------|---------|
| Cell math | $\frac{p}{q}$ |
| Plain cell control | plain |

Table: Native table title $\frac{s}{t}$

`anchor:end:table`

Before display.

$$\frac{a+b}{c+d}$$

Between displays.

$$\begin{pmatrix}a & b \\ c & d\end{pmatrix}$$

$$\sum_{i=1}^{n} x_i + \int_{0}^{1} f(x)\,dx$$

`anchor:begin:figure`

![Native figure title $z^{3}$](relative.png){width=3cm}

`anchor:end:figure`

Plain control after.
"""


def _math_ast(node) -> list[tuple[str, str]]:
    if isinstance(node, dict):
        if node.get("t") == "Math":
            return [(node["c"][0]["t"], node["c"][1])]
        return [value for child in node.values() for value in _math_ast(child)]
    if isinstance(node, list):
        return [value for child in node for value in _math_ast(child)]
    return []


def _assert_native_math(before: Path, after: Path) -> None:
    old, new = _xml(before), _xml(after)
    # Caption placement legitimately changes document order, not equation content.
    assert Counter(_tree(n) for n in old.iter(f"{M}oMath")) == Counter(
        _tree(n) for n in new.iter(f"{M}oMath"))
    assert len(list(new.iter(f"{M}oMathPara"))) == 3
    for tag in ("f", "sSup", "m", "nary"):
        assert new.find(f".//{M}{tag}") is not None
    old_settings, new_settings = (_xml(p, "word/settings.xml") for p in (before, after))
    assert [_tree(n) for n in old_settings.iter(f"{M}mathPr")] == [
        _tree(n) for n in new_settings.iter(f"{M}mathPr")]
    for p in _paragraphs(after):
        if p.find(f".//{M}oMath") is not None:
            assert _effective(after, p, "spacing").get("lineRule", "auto") in {"auto", "atLeast"}


@pytest.mark.parametrize("strategy", ["ecepdi", "testhouse"])
def test_native_inline_display_and_early_roles_keep_editable_math(
        tmp_path: Path, strategy: str) -> None:
    draft, emitted, snippet = _draft(tmp_path, MATH_MD, strategy=strategy)
    source_math = _math_ast(md_to_ast(MATH_MD))
    # The same expression is intentionally authored both inline and displayed.
    # Pandoc may repeat native figure ALT math in its caption AST, so raw Math
    # node counts do not describe the editable formulas a DOCX consumer sees.
    assert {kind for kind, _ in source_math} == {"InlineMath", "DisplayMath"}
    assert {kind for kind, tex in source_math if tex == r"\frac{a+b}{c+d}"} == {
        "InlineMath", "DisplayMath"}
    assert _math_ast(md_to_ast(emitted.read_text(encoding="utf-8"))) == source_math
    final = _polish(draft, emitted, snippet)
    _assert_native_math(draft, final)
    for path in (draft, final):
        native_paragraphs = _paragraphs(path)
        for marker, native_tag in (
                ("Heading", "sSup"), ("Inline fraction", "f"),
                ("Wrapped superscript", "sSup"), ("List math", "f"),
                ("Native table title", "f"), ("Native figure title", "sSup")):
            paragraph = next(p for p in native_paragraphs if marker in _text(p))
            assert paragraph.find(f"{M}oMath") is not None, (path, marker)
            assert paragraph.find(f".//{M}{native_tag}") is not None, (path, marker)
            assert paragraph.find(f"{M}oMathPara") is None, (path, marker)
        # Cell math has no ordinary text in its own paragraph.
        table = next(n for n in _body(path) if n.tag == f"{W}tbl")
        cell_math = next(p for p in table.iter(f"{W}p")
                         if p.find(f"{M}oMath") is not None)
        assert cell_math.find(f".//{M}f") is not None
        assert cell_math.find(f"{M}oMathPara") is None
        displays = [p for p in native_paragraphs if p.find(f"{M}oMathPara") is not None]
        assert any(p.find(f".//{M}f") is not None for p in displays)
        assert any(p.find(f".//{M}m") is not None for p in displays)
        assert any(p.find(f".//{M}nary") is not None for p in displays)
    paragraphs = _paragraphs(final)
    plain = next(p for p in paragraphs if _text(p) == "Plain control before.")
    inline = next(p for p in paragraphs if _text(p).startswith("Inline fraction"))
    wrapped = next(p for p in paragraphs if _text(p).startswith("Wrapped superscript"))
    assert _style(inline) == _style(wrapped) == _style(plain)
    assert _effective(final, plain, "spacing")["lineRule"] == "exact"
    assert _effective(final, plain, "spacing")["line"] == "460"
    assert _effective(final, inline, "ind") == _effective(final, plain, "ind")
    displays = [p for p in paragraphs if p.find(f"{M}oMathPara") is not None]
    assert len(displays) == 3
    assert all(_style(p) != _style(plain) for p in displays)
    for p in displays:
        _zero_indents(final, p)
        spacing = _effective(final, p, "spacing")
        assert int(spacing["before"]) > 0 and int(spacing["after"]) > 0
    heading = next(p for p in paragraphs if "Heading" in _text(p))
    assert _style(heading).startswith("heading")
    list_math = next(p for p in paragraphs if _text(p).startswith("List math"))
    list_plain = next(p for p in paragraphs if _text(p) == "Plain list control.")
    assert _style(list_math) == _style(list_plain)
    assert list_math.find(f"{W}pPr/{W}numPr") is not None
    table = next(n for n in _body(final) if n.tag == f"{W}tbl")
    cells = list(table.iter(f"{W}p"))
    assert len({_style(p) for p in cells}) == 1
    prefixes = (("表 2.2-1 ", "图 2.2-1 ") if strategy == "ecepdi"
                else ("Table 2-1: ", "Figure 2-1: "))
    for marker, prefix in zip(("Native table title", "Native figure title"), prefixes, strict=True):
        caption = next(p for p in paragraphs if marker in _text(p))
        assert _text(caption).startswith(prefix)
        assert caption.find(f".//{M}oMath") is not None
        assert _style(caption) not in {_style(plain), _style(displays[0])}


@pytest.mark.parametrize("rule,line", [("exact", "200"), ("auto", "336"), ("atLeast", "620")])
def test_winning_direct_math_spacing_keeps_floor_and_unrelated_properties(
        tmp_path: Path, rule: str, line: str) -> None:
    draft, emitted, snippet = _draft(tmp_path, MATH_MD)
    doc = Document(draft)
    for p in doc.element.body.iter(qn("w:p")):
        if p.find(f".//{qn('m:oMath')}") is None:
            continue
        ppr = p.get_or_add_pPr()
        _set(ppr, "w:spacing", line=line, lineRule=rule, before="71", after="93",
             beforeAutospacing="0")
        if p.find(qn("m:oMathPara")) is None:
            _set(ppr, "w:ind", left="137", right="91", firstLineChars="117")
        # Real section properties on an existing paragraph must not be rebuilt away.
        if "Wrapped superscript" in "".join(p.itertext()):
            section = _set(ppr, "w:sectPr")
            _set(section, "w:pgSz", w="11906", h="16838")
    doc.save(draft)
    before_math = [p for p in _paragraphs(draft) if p.find(f".//{M}oMath") is not None]
    final = _polish(draft, emitted, snippet)
    _assert_native_math(draft, final)
    after_math = [p for p in _paragraphs(final) if p.find(f".//{M}oMath") is not None]
    def key(p: ET.Element) -> tuple:
        return (p.find(f"{M}oMathPara") is not None,
                tuple(_tree(n) for n in p.iter(f"{M}oMath")))

    by_math = {key(p): p for p in after_math}
    assert len(by_math) == len(before_math)
    for old in before_math:
        new = by_math[key(old)]
        spacing = _effective(final, new, "spacing")
        assert (spacing["line"], spacing["lineRule"]) == (line, "atLeast" if rule == "exact" else rule)
        assert spacing["before"] == "71" and spacing["after"] == "93"
        assert spacing["beforeAutospacing"] == "0"
        for tag in ("numPr", "sectPr"):
            old_node, new_node = old.find(f"{W}pPr/{W}{tag}"), new.find(f"{W}pPr/{W}{tag}")
            assert (None if old_node is None else _tree(old_node)) == (
                None if new_node is None else _tree(new_node))
        if old.find(f"{M}oMathPara") is None:
            old_indents = _effective(draft, old, "ind")
            new_indents = _effective(final, new, "ind")
            assert all(int(old_indents.get(key, "0")) == int(new_indents.get(key, "0"))
                       for key in old_indents.keys() | new_indents.keys())


@pytest.mark.parametrize("inherited_from", ["Normal", "docDefaults"])
def test_inherited_exact_math_floor_does_not_change_plain_control(
        tmp_path: Path, inherited_from: str) -> None:
    draft, emitted, snippet = _draft(tmp_path, "Inline $\\frac{a}{b}$ text.\n\nPlain control.\n",
                                      overrides="""
styles:
  normal_text:
    line_spacing_rule: null
    line_spacing: null
""")
    doc = Document(draft)
    normal = doc.styles["Normal"].element.get_or_add_pPr()
    existing = normal.find(qn("w:spacing"))
    if existing is not None:
        normal.remove(existing)
    if inherited_from == "Normal":
        target = normal
    else:
        defaults = _set(doc.styles.element, "w:docDefaults")
        target = _set(_set(defaults, "w:pPrDefault"), "w:pPr")
    _set(target, "w:spacing", line="540", lineRule="exact")
    doc.save(draft)
    final = _polish(draft, emitted, snippet)
    math = next(p for p in _paragraphs(final) if p.find(f".//{M}oMath") is not None)
    plain = next(p for p in _paragraphs(final) if _text(p) == "Plain control.")
    assert _style(math) == _style(plain)
    assert (_effective(final, math, "spacing")["line"],
            _effective(final, math, "spacing")["lineRule"]) == ("540", "atLeast")
    assert (_effective(final, plain, "spacing")["line"],
            _effective(final, plain, "spacing")["lineRule"]) == ("540", "exact")


@pytest.mark.parametrize("strategy", ["ecepdi", "testhouse"])
def test_selected_rich_caption_math_survives_precedence_and_strategy(
        tmp_path: Path, strategy: str) -> None:
    table_label, figure_label = (("表", "图") if strategy == "ecepdi"
                                 else ("Table", "Figure"))
    markdown = rf"""
`anchor:begin:table`

| Value |
|-------|
| Native table |

Table: **Kept native** [reference](https://example.com/caption) $\frac{{k}}{{l}}$

`anchor:end:table`

`anchor:begin:table`

| Value |
|-------|
| Legacy table |

Table: Discarded table $d^{{9}}$

{table_label} **Kept legacy** [reference](https://example.com/caption) $w^{{4}}$

`anchor:end:table`

`anchor:begin:figure`

![Discarded figure $j^{{8}}$](relative.png){{width=3cm}}

{figure_label} **Kept figure** [reference](https://example.com/caption) $v^{{5}}$

`anchor:end:figure`
"""
    draft, emitted, snippet = _draft(tmp_path, markdown, strategy=strategy)
    markers = ("Kept native", "Kept legacy", "Kept figure")
    originals = {marker: next(p for p in _paragraphs(draft) if marker in _text(p))
                 for marker in markers}
    final = _polish(draft, emitted, snippet)
    all_paragraphs = _paragraphs(final)
    for index, marker in enumerate(markers):
        selected = [p for p in all_paragraphs if marker in _text(p)]
        assert len(selected) == 1
        caption = selected[0]
        original = originals[marker]
        assert [_tree(n) for n in caption.iter(f"{M}oMath")] == [
            _tree(n) for n in original.iter(f"{M}oMath")]
        assert caption.find(f".//{W}b") is not None
        assert [_tree(n) for n in caption.iter(f"{W}hyperlink")] == [
            _tree(n) for n in original.iter(f"{W}hyperlink")]
        assert _effective(final, caption, "spacing").get("lineRule", "auto") != "exact"
        if strategy == "ecepdi":
            prefix = f"{'表' if index < 2 else '图'} 2.2-{index + 1 if index < 2 else 1} "
        else:
            prefix = f"{'Table' if index < 2 else 'Figure'} 2-{index + 1 if index < 2 else 1}: "
        assert _text(caption).startswith(prefix)
    assert not any("Discarded" in _text(p) for p in all_paragraphs)
    kept_math = Counter(_tree(n) for p in originals.values() for n in p.iter(f"{M}oMath"))
    assert Counter(_tree(n) for n in _xml(final).iter(f"{M}oMath")) == kept_math
    # The losing figure's ALT is accessibility data, not a competing final caption.
    assert len(_images(final)) == 1
    assert [_tree(n) for n in _xml(draft).iter(f"{W}drawing")] == [
        _tree(n) for n in _xml(final).iter(f"{W}drawing")]


def test_display_override_uses_point_based_atleast_and_keeps_plain_leading(tmp_path: Path) -> None:
    draft, emitted, snippet = _draft(
        tmp_path, "Before.\n\n$$\\frac{a}{b}$$\n\nAfter.\n",
        overrides="""
styles:
  display_equation:
    space_before_pt: 7
    space_after_pt: 9
    line_spacing_rule: atLeast
    line_spacing: 31
""")
    final = _polish(draft, emitted, snippet)
    display = next(p for p in _paragraphs(final) if p.find(f"{M}oMathPara") is not None)
    spacing = _effective(final, display, "spacing")
    assert {key: spacing[key] for key in ("before", "after", "line", "lineRule")} == {
        "before": "140", "after": "180", "line": "620", "lineRule": "atLeast"}
    _zero_indents(final, display)
    plain = [p for p in _paragraphs(final) if _text(p) in {"Before.", "After."}]
    assert len(plain) == 2
    assert all(_style(p) != _style(display) for p in plain)
    assert all(_effective(final, p, "spacing")["lineRule"] == "exact" for p in plain)
