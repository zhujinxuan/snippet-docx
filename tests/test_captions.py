"""Consumer-visible caption contracts across draft and polish.

Native table captions and image ALT are preserved by draft; polish owns the
single final caption, numbering, placement and house style within anchor envs.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from snippet_docx.cli import main

DATA = Path(__file__).parent / "data"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/package/2006/relationships}"
IMAGE = (DATA / "figure.png").as_posix()


def _body_children(docx: Path) -> list[ET.Element]:
    with zipfile.ZipFile(docx) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    return list(root.find(f"{W}body"))


def _text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(f"{W}t"))


def _paragraphs(docx: Path) -> list[ET.Element]:
    return [el for el in _body_children(docx) if el.tag == f"{W}p"]


def _captions(docx: Path) -> list[str]:
    return [_text(p) for p in _paragraphs(docx)
            if re.match(r"^[表图] [\dA-Z.]+-\d+ ", _text(p))]


def _table(title: str | None = "电量表", *, legacy: str | None = None,
           marker: str = "Table:", cell: str = "T01") -> str:
    native = f"\n\n{marker} {title}" if title is not None else ""
    explicit = f"\n\n{legacy}" if legacy is not None else ""
    return ("`anchor:begin:table`\n\n"
            f"| 机位 |\n|------|\n| {cell} |{native}{explicit}\n\n"
            "`anchor:end:table`\n\n")


def _figure(title: str = "布置图", *, legacy: str | None = None,
            linked: bool = False, legacy_above: bool = False) -> str:
    image = f"![{title}]({IMAGE})"
    if linked:
        image = f"[{image}](https://example.com/layout)"
    explicit = f"{legacy}\n\n" if legacy is not None else ""
    content = explicit + image if legacy_above else image + "\n\n" + explicit
    return f"`anchor:begin:figure`\n\n{content}\n\n`anchor:end:figure`\n\n"


def _pipeline(tmp_path: Path, md: str, *, config: str = "",
              prefix: str = "[2, 2]", raw_context: bool = False) -> tuple[Path, Path, Path]:
    source = tmp_path / "source.md"
    source.write_text(md, encoding="utf-8")
    snippet = tmp_path / "snippet.yaml"
    snippet.write_text(f"strategy: ecepdi\nsection:\n  prefix: {prefix}\n{config}",
                       encoding="utf-8")
    draft = tmp_path / "draft.docx"
    emitted = tmp_path / "anchored.md"
    assert main(["draft", str(source), "--snippet", str(snippet),
                 "--out", str(draft), "--emit-md", str(emitted)]) == 0
    final = tmp_path / "final.docx"
    assert main(["polish", str(draft), "--snippet", str(snippet),
                 "--md", str(source if raw_context else emitted), "--out", str(final)]) == 0
    return draft, emitted, final


@pytest.mark.parametrize("marker", ["Table:", ":"])
def test_native_only_captions_are_finalized_by_polish(
        tmp_path: Path, capsys: pytest.CaptureFixture, marker: str) -> None:
    draft, emitted, final = _pipeline(
        tmp_path, _table(marker=marker) + _figure())
    # Draft retains the native caption inputs without baking final numbers.
    assert "电量表" in emitted.read_text(encoding="utf-8")
    assert "布置图" in emitted.read_text(encoding="utf-8")
    assert _captions(draft) == []
    assert _captions(final) == ["表 2.2-1 电量表", "图 2.2-1 布置图"]
    assert "captionless-env" not in capsys.readouterr().err
    children = _body_children(final)
    table = next(i for i, el in enumerate(children) if el.tag == f"{W}tbl")
    image = next(i for i, el in enumerate(children)
                 if el.find(f".//{W}drawing") is not None)
    assert _text(children[table - 1]) == "表 2.2-1 电量表"
    assert _text(children[image + 1]) == "图 2.2-1 布置图"
    for index, style in ((table - 1, "table_caption"),
                         (image + 1, "figure_caption")):
        assert children[index].find(f"{W}pPr/{W}pStyle").get(f"{W}val") == style
    assert "anchor:" not in "".join(_text(el) for el in children)
    assert all(p.find(f"{W}pPr/{W}pStyle") is None
               or p.find(f"{W}pPr/{W}pStyle").get(f"{W}val")
               not in {"TableCaption", "ImageCaption"}
               for p in _paragraphs(final))


@pytest.mark.parametrize("kind", ["table", "figure"])
def test_legacy_and_native_duplicates_consume_one_number(
        tmp_path: Path, capsys: pytest.CaptureFixture, kind: str) -> None:
    env = _table if kind == "table" else _figure
    label = "表" if kind == "table" else "图"
    md = env("同题", legacy=f"{label} 同题") + env("后题")
    _, _, final = _pipeline(tmp_path, md)
    assert _captions(final) == [f"{label} 2.2-1 同题", f"{label} 2.2-2 后题"]
    texts = [_text(p) for p in _paragraphs(final)]
    assert [text for text in texts if "同题" in text] == [f"{label} 2.2-1 同题"]
    assert "[WARN]" not in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["table", "figure"])
def test_differing_legacy_title_wins_and_warns(
        tmp_path: Path, capsys: pytest.CaptureFixture, kind: str) -> None:
    env = _table if kind == "table" else _figure
    label = "表" if kind == "table" else "图"
    _, _, final = _pipeline(tmp_path, env("原生标题", legacy=f"{label} 人工标题"))
    assert _captions(final) == [f"{label} 2.2-1 人工标题"]
    assert all("原生标题" not in _text(p) for p in _paragraphs(final))
    warning = capsys.readouterr().err
    assert "[WARN]" in warning
    assert "原生标题" in warning and "人工标题" in warning


@pytest.mark.parametrize("kind", ["table", "figure"])
@pytest.mark.parametrize("source", ["native", "native-number-only", "legacy", "both"])
def test_stale_labels_and_numbers_are_stripped(
        tmp_path: Path, capsys: pytest.CaptureFixture, kind: str, source: str) -> None:
    label = "表" if kind == "table" else "图"
    env = _table if kind == "table" else _figure
    title = ("4.3-7 旧编号标题" if source == "native-number-only"
             else f"{label} 4.3-7 旧编号标题")
    native = title if source != "legacy" else (None if kind == "table" else "")
    legacy = f"{label} A.2-9 旧编号标题" if not source.startswith("native") else None
    _, _, final = _pipeline(tmp_path, env(native, legacy=legacy))
    assert _captions(final) == [f"{label} 2.2-1 旧编号标题"]
    text = "".join(_text(el) for el in _body_children(final))
    assert "4.3-7" not in text and "A.2-9" not in text
    assert "[WARN]" not in capsys.readouterr().err


@pytest.mark.parametrize("kind,title,expected", [
    ("table", "表面粗糙度", "表面粗糙度"),
    ("figure", "图像布局", "图像布局"),
    ("table", "表 表面粗糙度", "表面粗糙度"),
    ("figure", "图 图像布局", "图像布局"),
    ("table", "表 9.9-7 表面粗糙度", "表面粗糙度"),
    ("figure", "图 9.9-7 图像布局", "图像布局"),
])
def test_native_label_normalization_respects_title_word_boundary(
        tmp_path: Path, kind: str, title: str, expected: str) -> None:
    env = _table if kind == "table" else _figure
    label = "表" if kind == "table" else "图"
    _, _, final = _pipeline(tmp_path, env(title))
    assert _captions(final) == [f"{label} 2.2-1 {expected}"]
    if kind == "figure":
        assert any(el.find(f".//{W}drawing") is not None
                   for el in _body_children(final))


@pytest.mark.parametrize("kind", ["table", "figure"])
def test_matching_titles_in_separate_envs_are_not_deduplicated(
        tmp_path: Path, kind: str) -> None:
    env = _table if kind == "table" else _figure
    label = "表" if kind == "table" else "图"
    _, _, final = _pipeline(tmp_path, env("同名") + env("同名"))
    assert _captions(final) == [f"{label} 2.2-1 同名", f"{label} 2.2-2 同名"]
    expected_content = f"{W}tbl" if kind == "table" else f"{W}drawing"
    assert sum(1 for el in _body_children(final) for node in el.iter()
               if node.tag == expected_content) == 2


@pytest.mark.parametrize("title,legacy", [
    ("图 布置图", None), ("图 9.9-8 布置图", None), ("", "图 布置图")])
def test_figure_alt_label_or_empty_alt_preserves_drawing(
        tmp_path: Path, title: str, legacy: str | None) -> None:
    _, _, final = _pipeline(tmp_path, _figure(title, legacy=legacy))
    assert _captions(final) == ["图 2.2-1 布置图"]
    assert sum(el.find(f".//{W}drawing") is not None
               for el in _body_children(final)) == 1


def test_linked_image_alt_supplies_caption_and_preserves_link(tmp_path: Path) -> None:
    _, _, final = _pipeline(tmp_path, _figure(linked=True))
    assert _captions(final) == ["图 2.2-1 布置图"]
    assert any(el.find(f".//{W}drawing") is not None for el in _body_children(final))
    with zipfile.ZipFile(final) as zf:
        rels = ET.fromstring(zf.read("word/_rels/document.xml.rels"))
    assert any(rel.get("Target") == "https://example.com/layout"
               and rel.get("TargetMode") == "External" for rel in rels.findall(f"{R}Relationship"))


def test_polish_moves_legacy_captions_to_final_placement(tmp_path: Path) -> None:
    _, _, final = _pipeline(
        tmp_path, _table(None, legacy="表 电量表")
        + _figure("", legacy="图 布置图", legacy_above=True))
    children = _body_children(final)
    table = next(i for i, el in enumerate(children) if el.tag == f"{W}tbl")
    image = next(i for i, el in enumerate(children)
                 if el.find(f".//{W}drawing") is not None)
    assert _text(children[table - 1]) == "表 2.2-1 电量表"
    assert _text(children[image + 1]) == "图 2.2-1 布置图"


def test_numbering_starts_and_independent_sequences(tmp_path: Path) -> None:
    _, _, final = _pipeline(
        tmp_path, _table() + _figure() + _table("第二表"),
        config="numbering:\n  table: {start: 2}\n  figure: {start: 4}\n")
    assert _captions(final) == ["表 2.2-2 电量表", "图 2.2-4 布置图", "表 2.2-3 第二表"]


@pytest.mark.parametrize("max_depth,expected", [
    (3, ["表 2.2.1-1 甲", "表 2.2.1-2 乙", "表 2.2.2-1 丙"]),
    (4, ["表 2.2.1-1 甲", "表 2.2.1.1-1 乙", "表 2.2.2-1 丙"]),
])
def test_numbering_scopes_follow_displayed_clamped_section(
        tmp_path: Path, max_depth: int, expected: list[str]) -> None:
    md = "## 第一节\n\n" + _table("甲") + "### 深一层\n\n" + _table("乙")
    md += "## 第二节\n\n" + _table("丙")
    _, _, final = _pipeline(tmp_path, md,
                            config=f"numbering:\n  caption: {{max_depth: {max_depth}}}\n")
    assert _captions(final) == expected


def test_prefix_alone_drives_numbering_without_headings(tmp_path: Path) -> None:
    _, _, final = _pipeline(tmp_path, _table(), prefix="[2, 2, 3]")
    assert _captions(final) == ["表 2.2.3-1 电量表"]


def test_native_captions_survive_landscape_and_continue_sequence(tmp_path: Path) -> None:
    md = "`anchor:begin:landscape`\n\n" + _table() + _figure()
    md += "`anchor:end:landscape`\n\n" + _table("竖向表")
    _, _, final = _pipeline(tmp_path, md)
    assert _captions(final) == ["表 2.2-1 电量表", "图 2.2-1 布置图", "表 2.2-2 竖向表"]
    sections = [node for el in _body_children(final) for node in el.iter(f"{W}sectPr")]
    assert len(sections) == 3
    assert [section.find(f"{W}pgSz").get(f"{W}orient", "portrait")
            for section in sections] == ["portrait", "landscape", "portrait"]


def test_captionless_table_warns_but_remains_unnumbered(
        tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _, _, final = _pipeline(tmp_path, _table(None, cell="裸表"))
    assert "[WARN] captionless-env:" in capsys.readouterr().err
    assert _captions(final) == []
    assert any(el.tag == f"{W}tbl" and "裸表" in _text(el) for el in _body_children(final))


def test_unanchored_native_captions_do_not_create_numbered_envs(tmp_path: Path) -> None:
    md = _table().replace("`anchor:begin:table`", "").replace("`anchor:end:table`", "")
    md += _figure().replace("`anchor:begin:figure`", "").replace("`anchor:end:figure`", "")
    _, _, final = _pipeline(tmp_path, md)
    assert _captions(final) == []
    assert any(el.tag == f"{W}tbl" for el in _body_children(final))
    assert any(el.find(f".//{W}drawing") is not None for el in _body_children(final))


@pytest.mark.parametrize("raw_context", [False, True], ids=["emitted-md", "source-md"])
@pytest.mark.parametrize("prefix,expected", [
    ("[2, 2]", "表 2.2.3-1 数据"),
    ("[2, 2, 3]", "表 2.2.3.3-1 数据"),
])
def test_heading_context_survives_draft_roundtrip_without_double_offset(
        tmp_path: Path, raw_context: bool, prefix: str, expected: str) -> None:
    md = "# 本节\n\n## 数据节\n\n" + _table("数据")
    level = 3 if prefix == "[2, 2]" else 4
    _, _, final = _pipeline(
        tmp_path, md, prefix=prefix, raw_context=raw_context,
        config=f"numbering:\n  sections:\n    start: {{{level}: 3}}\n"
               "  caption: {max_depth: 4}\n")
    assert _captions(final) == [expected]


@pytest.mark.parametrize("raw_context", [False, True], ids=["emitted-md", "source-md"])
def test_caption_inline_section_variable_matches_raw_and_emitted_context(
        tmp_path: Path, raw_context: bool) -> None:
    md = "# 本节\n\n" + _table(None, legacy="表 `anchor:section` 数据")
    _, _, final = _pipeline(tmp_path, md, raw_context=raw_context)
    assert _captions(final) == ["表 2.2-1 2.2 数据"]
    assert "anchor:" not in "".join(_text(el) for el in _body_children(final))


@pytest.mark.parametrize("title", ["数据", None], ids=["native-table-caption", "captionless-table"])
def test_table_env_ignores_logo_alt_as_caption_source(
        tmp_path: Path, capsys: pytest.CaptureFixture, title: str | None) -> None:
    table_with_logo = _table(title).replace(
        "`anchor:begin:table`\n\n",
        f"`anchor:begin:table`\n\n![标识]({IMAGE})\n\n", 1)
    _, _, final = _pipeline(tmp_path, table_with_logo + _table("后表"))
    expected = (["表 2.2-1 数据", "表 2.2-2 后表"] if title is not None
                else ["表 2.2-1 后表"])
    assert _captions(final) == expected
    children = _body_children(final)
    assert sum(el.find(f".//{W}drawing") is not None for el in children) == 1
    assert sum(el.tag == f"{W}tbl" for el in children) == 2
    warnings = capsys.readouterr().err
    assert "caption-conflict" not in warnings
    assert ("captionless-env" in warnings) == (title is None)


def test_figure_env_does_not_use_native_table_caption_as_figure_title(
        tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    md = (
        f"`anchor:begin:figure`\n\n![]({IMAGE})\n\n"
        "| 数据 |\n|------|\n| 1 |\n\nTable: 数据表\n\n"
        "`anchor:end:figure`\n\n") + _figure("后图")
    _, _, final = _pipeline(tmp_path, md)
    assert _captions(final) == ["图 2.2-1 后图"]
    children = _body_children(final)
    assert sum(el.find(f".//{W}drawing") is not None for el in children) == 2
    assert sum(el.tag == f"{W}tbl" for el in children) == 1
    warnings = capsys.readouterr().err
    assert "captionless-env" in warnings
    assert "caption-conflict" not in warnings
