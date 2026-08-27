"""Landscape env tests (ticket 07).

Registry + nesting validation (anchors.py), walker scoping (tables inside
a landscape env still number captions under the current section), and
docx-side InsertSectionBreak as XML assertions on the final DOCX: exactly
the env's pages carry a landscape pgSz with swapped w/h and the portrait
body's margins; pages before and after stay portrait; a wide repaired
table inside the env fits the landscape text width. The officecli visual
pass on the same fixture is run manually (ticket's one visual assertion).
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from snippet_docx.anchors import parse_anchors, validate_anchors
from snippet_docx.cli import main
from snippet_docx.config import ConfigError, load_config
from snippet_docx.ops_docx import ecepdi_docx_ops
from snippet_docx.pandoc_ast import md_to_ast
from snippet_docx.strategies.ecepdi import EcepdiStrategy
from snippet_docx.walker import build_annotations

DATA = Path(__file__).parent / "data"
LANDSCAPE_MD = DATA / "landscape.md"
SNIPPET = DATA / "snippet.yaml"
A3_YAML = DATA / "landscape-a3.yaml"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

STRATEGY = EcepdiStrategy()

A4_SHORT, A4_LONG = 11906, 16838
PORTRAIT_TEXT_TWIPS = A4_SHORT - 2 * 1440
LANDSCAPE_TEXT_TWIPS = A4_LONG - 2 * 1440

# ten numeric columns -> FixTable floor 1200 twips each
WIDE_TABLE_TWIPS = 10 * 1200


def _xml(docx: Path) -> ET.Element:
    with zipfile.ZipFile(docx) as zf:
        return ET.fromstring(zf.read("word/document.xml"))


def _sectprs(root: ET.Element) -> list[ET.Element]:
    """All sectPr elements in document order (paragraph-level, then body)."""
    return list(root.iter(f"{W}sectPr"))


def _pgsz(sect: ET.Element) -> ET.Element:
    return sect.find(f"{W}pgSz")


def _texts(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(f"{W}t"))


def _polished(md: Path | str, snippet: Path, tmp_path: Path,
              monkeypatch: pytest.MonkeyPatch) -> Path:
    workdir = tmp_path if isinstance(md, str) else DATA
    monkeypatch.chdir(workdir)
    source = tmp_path / "doc.md"
    source.write_text(md if isinstance(md, str) else md.read_text(encoding="utf-8"),
                      encoding="utf-8")
    draft = tmp_path / "draft.docx"
    final = tmp_path / "final.docx"
    rc = main(["draft", str(source), "--snippet", str(snippet), "--out", str(draft)])
    assert rc == 0
    rc = main(["polish", str(draft), "--snippet", str(snippet), "--out", str(final)])
    assert rc == 0
    return final


# ------------------------------------------------------------ registry

def test_landscape_env_spec_in_registry() -> None:
    spec = STRATEGY.envs["landscape"]
    assert spec.numbered is False
    assert spec.may_contain == ("table", "figure")
    assert spec.label                        # non-empty (strategy-seam contract)
    assert spec.caption_placement in ("above", "below")


def test_insert_section_break_registered_before_strip() -> None:
    names = [type(op).__name__ for op in ecepdi_docx_ops()]
    assert names[-1] == "StripAnchors"
    assert names[-2] == "InsertSectionBreak"


# -------------------------------------------------- nesting validation

def _findings(md: str) -> list[tuple[str, str]]:
    ast = md_to_ast(md)
    return [(f.code, f.severity) for f in
            validate_anchors(parse_anchors(ast), ast, STRATEGY)]


TABLE_ENV = ("`anchor:begin:table`\n\n表 电量表\n\n| a | b |\n|---|---|\n"
             "| 1 | 2 |\n\n`anchor:end:table`")


def test_landscape_wrapping_table_and_prose_is_valid() -> None:
    md = ("前文。\n\n`anchor:begin:landscape`\n\n" + TABLE_ENV +
          "\n\n横向说明文字。\n\n`anchor:end:landscape`\n\n后文。\n")
    assert _findings(md) == []


def test_bare_landscape_env_never_warns_captionless() -> None:
    md = "`anchor:begin:landscape`\n\n仅一段说明文字。\n\n`anchor:end:landscape`\n"
    assert _findings(md) == []          # unnumbered layout env: no caption rule


def test_landscape_may_not_nest_in_landscape() -> None:
    md = ("`anchor:begin:landscape`\n\n`anchor:begin:landscape`\n\n"
          "`anchor:end:landscape`\n\n`anchor:end:landscape`\n")
    assert ("nesting-violation", "error") in _findings(md)


def test_landscape_may_not_nest_in_table() -> None:
    md = ("`anchor:begin:table`\n\n表 电量表\n\n`anchor:begin:landscape`\n\n"
          "`anchor:end:landscape`\n\n`anchor:end:table`\n")
    assert ("nesting-violation", "error") in _findings(md)


def test_table_still_may_not_nest_in_table() -> None:
    md = "`anchor:begin:table`\n\n表 电量表\n\n" + TABLE_ENV + "\n\n`anchor:end:table`\n"
    assert ("nesting-violation", "error") in _findings(md)


# ------------------------------------------------------------- walker

def _walker_config(prefix: tuple = (2, 2)):
    from snippet_docx.config import Config
    return Config(strategy="ecepdi", prefix=prefix)


def test_walker_scopes_landscape_and_keeps_caption_numbering() -> None:
    md = ("## 数据节\n\n`anchor:begin:landscape`\n\n" + TABLE_ENV +
          "\n\n中间文字。\n\n" + TABLE_ENV + "\n\n`anchor:end:landscape`\n")
    nodes = build_annotations(md_to_ast(md), _walker_config(), STRATEGY)

    captions = [n for n in nodes if n.kind == "caption"]
    assert [n.caption_env for n in captions] == ["table", "table"]
    assert [n.caption_index for n in captions] == [1, 2]      # current section
    assert all(n.section_path == (2, 2, 1) for n in captions)

    prose = [n for n in nodes if n.kind == "block" and n.env_scope == "landscape"]
    assert _node_text(md, nodes, prose[0]) == "中间文字。"      # innermost scope

    tables = [n for n in nodes if n.kind == "table"]
    assert len(tables) == 2                                    # still table nodes
    assert all(n.env_scope == "table" for n in tables)


def _node_text(md: str, nodes, node) -> str:  # pragma: no cover - trivial helper
    from snippet_docx.pandoc_ast import blocks, plain_text
    blk = blocks(md_to_ast(md))[node.index]
    return plain_text(blk.get("c") or [])


# ------------------------------------------------------------ e2e XML

def test_landscape_pages_a4_swapped_portrait_around(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = _polished(LANDSCAPE_MD, SNIPPET, tmp_path, monkeypatch)
    sects = _sectprs(_xml(final))
    assert len(sects) == 3                       # portrait / landscape / portrait

    portrait_close, landscape_close, body_sect = sects
    assert _pgsz(portrait_close).get(f"{W}w") == str(A4_SHORT)
    assert _pgsz(portrait_close).get(f"{W}h") == str(A4_LONG)
    assert _pgsz(portrait_close).get(f"{W}orient") is None
    assert _pgsz(body_sect).get(f"{W}w") == str(A4_SHORT)   # after-page portrait

    pgsz = _pgsz(landscape_close)
    assert pgsz.get(f"{W}w") == str(A4_LONG)
    assert pgsz.get(f"{W}h") == str(A4_SHORT)
    assert pgsz.get(f"{W}orient") == "landscape"

    margins = [{k: v for k, v in s.find(f"{W}pgMar").attrib.items()} for s in sects]
    assert margins[0] == margins[1] == margins[2]            # same margins everywhere


def test_env_region_holds_multiple_tables_and_prose(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = _polished(LANDSCAPE_MD, SNIPPET, tmp_path, monkeypatch)
    root = _xml(final)
    children = list(root.find(f"{W}body"))

    def is_sect_para(el: ET.Element, which: int) -> bool:
        ppr = el.find(f"{W}pPr")
        return (el.tag == f"{W}p" and ppr is not None
                and ppr.find(f"{W}sectPr") is not None
                and _sectprs(root).index(ppr.find(f"{W}sectPr")) == which)

    portrait_close = next(i for i, el in enumerate(children) if is_sect_para(el, 0))
    landscape_close = next(i for i, el in enumerate(children) if is_sect_para(el, 1))
    tables = [i for i, el in enumerate(children) if el.tag == f"{W}tbl"]
    prose = [i for i, el in enumerate(children)
             if el.tag == f"{W}p" and "上表共十列" in _texts(el)]
    after = [i for i, el in enumerate(children)
             if el.tag == f"{W}p" and "后续章节" in _texts(el)]

    assert len(tables) == 2 and len(prose) == 1 and len(after) == 1
    assert portrait_close < tables[0] < prose[0] < tables[1] < landscape_close
    assert landscape_close < after[0]
    assert _texts(children[landscape_close]) == "横向段落收尾。"
    # an empty paragraph right after the env opens the following portrait page
    opener = children[landscape_close + 1]
    assert opener.tag == f"{W}p" and _texts(opener) == ""
    # the portrait break rides an inserted empty paragraph, not content
    assert _texts(children[portrait_close]) == ""
    assert "anchor:" not in _texts(root)                       # zero anchor residue


def test_tables_inside_landscape_still_numbered_under_section(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = _polished(LANDSCAPE_MD, SNIPPET, tmp_path, monkeypatch)
    root = _xml(final)
    children = list(root.find(f"{W}body"))
    text = _texts(root)
    assert "表 2.2-1 宽表示例" in text
    assert "表 2.2-2 第二张表" in text
    for caption, table in (("表 2.2-1 宽表示例", 0), ("表 2.2-2 第二张表", 1)):
        cap_i = next(i for i, el in enumerate(children) if caption in _texts(el))
        tbl_i = next(i for i, el in enumerate(children)
                     if el.tag == f"{W}tbl" and i > cap_i)
        assert cap_i < tbl_i                          # caption sits above the table
        assert tbl_i == [i for i, el in enumerate(children)
                         if el.tag == f"{W}tbl"][table]


def test_wide_table_fits_landscape_text_width(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = _polished(LANDSCAPE_MD, SNIPPET, tmp_path, monkeypatch)
    root = _xml(final)
    wide = root.findall(f".//{W}tbl")[0]              # the ten-column table
    cols = [int(c.get(f"{W}w")) for c in wide.iter(f"{W}gridCol")]
    assert sum(cols) == WIDE_TABLE_TWIPS
    assert sum(cols) > PORTRAIT_TEXT_TWIPS            # genuinely needs landscape
    assert sum(cols) <= LANDSCAPE_TEXT_TWIPS          # unclipped on the wide page
    tblw = wide.find(f"{W}tblPr/{W}tblW")
    assert (tblw.get(f"{W}w"), tblw.get(f"{W}type")) == ("5000", "pct")


# ------------------------------------------------------- paper: a3

def test_paper_a3_rejected_with_clear_message() -> None:
    with pytest.raises(ConfigError, match=r"landscape paper 'a3'.*not implemented.*only a4"):
        load_config(A3_YAML, None)


def test_paper_a3_rejected_at_cli(tmp_path: Path,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="not implemented"):
        main(["draft", str(LANDSCAPE_MD), "--snippet", str(A3_YAML),
              "--out", str(tmp_path / "never.docx")])
    assert not (tmp_path / "never.docx").exists()


# --------------------------------------------------- shape edge cases

def test_env_ending_on_a_table_gets_inserted_closing_paragraph(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md = ("前文。\n\n`anchor:begin:landscape`\n\n`anchor:begin:table`\n\n"
          "表 末尾表\n\n"
          "| 一 | 二 | 三 | 四 | 五 | 六 | 七 | 八 | 九 | 十 |\n"
          "|---|---|---|---|---|---|---|---|---|---|\n"
          "| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |\n\n"
          "`anchor:end:table`\n\n`anchor:end:landscape`\n\n后文。\n")
    final = _polished(md, SNIPPET, tmp_path, monkeypatch)
    root = _xml(final)
    assert len(_sectprs(root)) == 3
    children = list(root.find(f"{W}body"))
    landscape_close = _sectprs(root)[1]
    para = next(el for el in children if el.tag == f"{W}p"
                and el.find(f"{W}pPr/{W}sectPr") is landscape_close)
    i = children.index(para)
    assert _texts(para) == ""                               # inserted, empty
    assert children[i - 1].tag == f"{W}tbl"                 # right after the table
    assert "末尾表" in _texts(children[i - 2])               # caption above the table


def test_two_landscape_envs_get_separate_sections(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    small = ("`anchor:begin:table`\n\n表 甲表\n\n| a |\n|---|\n| 1 |\n\n"
             "`anchor:end:table`\n")
    md = ("前文。\n\n`anchor:begin:landscape`\n\n" + small + "\n\n"
          "`anchor:end:landscape`\n\n间隔正文。\n\n`anchor:begin:landscape`\n\n"
          + small + "\n\n`anchor:end:landscape`\n\n后文。\n")
    final = _polished(md, SNIPPET, tmp_path, monkeypatch)
    sects = _sectprs(_xml(final))
    assert len(sects) == 5
    orients = [(_pgsz(s).get(f"{W}orient") or "portrait") for s in sects]
    assert orients == ["portrait", "landscape", "portrait", "landscape", "portrait"]
