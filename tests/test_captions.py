"""Caption numbering + placement tests (ticket 04, ToolSpec §3/§4).

Pure walker tests: per-(env, section) counters, clamped scope, env_start
offsets, independent table/figure sequences, caption detection by label
prefix. Op tests: NumberCaptions strips stale numbers, renumbers via
strategy.format_caption and moves captions to EnvSpec placement, keeping
ctx.annotations parallel to the blocks. CLI-seam tests: numbers visible in
the emitted anchored md before any DOCX exists, caption order in the final
DOCX XML, captionless table warns but builds.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
from snippet_docx.cli import main
from snippet_docx.config import Config
from snippet_docx.ops_md import NumberCaptions
from snippet_docx.pandoc_ast import ast_to_md, blocks, md_to_ast, plain_text
from snippet_docx.pipeline import Ctx
from snippet_docx.strategies.ecepdi import EcepdiStrategy
from snippet_docx.walker import build_annotations

STRATEGY = EcepdiStrategy()
DATA = Path(__file__).parent / "data"
CAPTIONS_MD = DATA / "captions.md"
CAPTIONS_YAML = DATA / "captions.yaml"
CAPTIONS_START_MD = DATA / "captions-start.md"
CAPTIONS_START_YAML = DATA / "captions-start.yaml"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


# ---------------------------------------------------------------- helpers


def _annotations(md: str, prefix: tuple[int | str, ...],
                 env_start: dict[str, int] | None = None,
                 section_start: dict[int, int] | None = None,
                 caption_max_depth: int = 3):
    config = Config(strategy="ecepdi", prefix=prefix,
                    section_start=section_start or {}, env_start=env_start or {},
                    caption_max_depth=caption_max_depth)
    return build_annotations(md_to_ast(md), config, STRATEGY)


def _captions(nodes):
    return [n for n in nodes if n.kind == "caption"]


def _run_op(md: str, prefix: tuple[int | str, ...],
            env_start: dict[str, int] | None = None,
            section_start: dict[int, int] | None = None,
            caption_max_depth: int = 3):
    """Walker + NumberCaptions over a fresh AST; returns (ast, annotations)."""
    config = Config(strategy="ecepdi", prefix=prefix,
                    section_start=section_start or {}, env_start=env_start or {},
                    caption_max_depth=caption_max_depth)
    ast = md_to_ast(md)
    nodes = build_annotations(ast, config, STRATEGY)
    ctx = Ctx(config=config, strategy=STRATEGY)
    ctx.annotations = nodes
    NumberCaptions()(ast, ctx)
    return ast, nodes


def _document_xml(docx: Path) -> str:
    with zipfile.ZipFile(docx) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def _plain_text(docx: Path) -> str:
    return re.sub(r"<[^>]+>", "", _document_xml(docx))


def _body_children(docx: Path) -> list[ET.Element]:
    with zipfile.ZipFile(docx) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    return list(root.find(f"{W}body"))


def _p_text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(f"{W}t"))


def _first_index(children: list[ET.Element], predicate) -> int:
    return next(i for i, el in enumerate(children) if predicate(el))


def _draft(md: Path, snippet: Path, tmp_path: Path, emit: bool = True):
    out = tmp_path / "draft.docx"
    emit_md = tmp_path / "anchored.md" if emit else None
    argv = ["draft", str(md), "--snippet", str(snippet), "--out", str(out)]
    if emit_md is not None:
        argv += ["--emit-md", str(emit_md)]
    return main(argv), out, emit_md


# ------------------------------------------------------- walker: counters

TABLE_ENV = """`anchor:begin:table`

表 电量表

| A |
|---|
| 1 |

`anchor:end:table`
"""

FIGURE_ENV = """`anchor:begin:figure`

![示意图](figure.png)

图 布置图

`anchor:end:figure`
"""


def test_caption_detected_with_env_and_index() -> None:
    nodes = _annotations(TABLE_ENV, (2, 2))
    caps = _captions(nodes)
    assert len(caps) == 1
    assert caps[0].caption_env == "table"
    assert caps[0].caption_index == 1
    assert caps[0].section_path == (2, 2)
    assert caps[0].env_scope == "table"


def test_no_headings_numbers_from_prefix_alone() -> None:
    nodes = _annotations(TABLE_ENV, (2, 2, 3))
    cap = _captions(nodes)[0]
    assert cap.section_path == (2, 2, 3)
    assert cap.caption_index == 1


def test_env_start_offsets_and_independent_counters() -> None:
    md = TABLE_ENV + "\n" + FIGURE_ENV + "\n" + TABLE_ENV
    nodes = _annotations(md, (2, 2), env_start={"table": 2, "figure": 1})
    got = [(n.caption_env, n.caption_index) for n in _captions(nodes)]
    assert got == [("table", 2), ("figure", 1), ("table", 3)]


def test_counters_restart_per_enclosing_section() -> None:
    md = "## 甲\n\n" + TABLE_ENV + "\n## 乙\n\n" + TABLE_ENV
    nodes = _annotations(md, (2, 2))
    caps = _captions(nodes)
    assert [n.section_path for n in caps] == [(2, 2, 1), (2, 2, 2)]
    assert [n.caption_index for n in caps] == [1, 1]


def test_clamped_scope_continues_displayed_sequence() -> None:
    # second table sits under a depth-4 heading (2.2.1.1); its caption shares
    # the DISPLAYED (clamped to 3) 2.2.1 sequence -> 表 2.2.1-2, never a
    # duplicate 表 2.2.1-1
    md = "## 甲\n\n" + TABLE_ENV + "\n### 乙\n\n" + TABLE_ENV
    nodes = _annotations(md, (2, 2))
    caps = _captions(nodes)
    assert [n.section_path for n in caps] == [(2, 2, 1), (2, 2, 1, 1)]
    assert [n.caption_index for n in caps] == [1, 2]


def test_config_max_depth_4_numbers_at_depth_4() -> None:
    # numbering.caption.max_depth loosens the clamp (ToolSpec §4): captions
    # display the depth-4 section and counters scope per depth-4 section
    md = "## 甲\n\n" + TABLE_ENV + "\n### 乙\n\n" + TABLE_ENV
    ast, nodes = _run_op(md, (2, 2), caption_max_depth=4)
    caps = _captions(nodes)
    assert [n.caption_index for n in caps] == [1, 1]  # scope = depth-4 section
    out = ast_to_md(ast)
    assert "表 2.2.1-1 电量表" in out
    assert "表 2.2.1.1-1 电量表" in out


def test_stale_numbered_paragraph_is_still_a_caption() -> None:
    stale = TABLE_ENV.replace("表 电量表", "表 4.3-7 电量表")
    cap = _captions(_annotations(stale, (2, 2)))[0]
    assert cap.caption_env == "table"
    assert cap.caption_index == 1  # counted fresh; the stale number is ignored


def test_caption_needs_matching_label_inside_env() -> None:
    # a figure label inside a table env is nobody's caption
    nodes = _annotations(TABLE_ENV.replace("表 电量表", "图 布置图"), (2, 2))
    assert _captions(nodes) == []
    # and the same text outside any env is plain prose
    assert _captions(_annotations("图 布置图\n", (2, 2))) == []


def test_captionless_env_yields_no_caption_node() -> None:
    md = "`anchor:begin:table`\n\n| A |\n|---|\n| 1 |\n\n`anchor:end:table`\n"
    assert _captions(_annotations(md, (2, 2))) == []
    # (the captionless-env WARNING is ValidateAnchors' finding, ticket 02)


def test_env_scope_and_content_kinds() -> None:
    md = "段落。\n\n| A |\n|---|\n| 1 |\n\n![裸图](figure.png)\n\n" + FIGURE_ENV
    nodes = _annotations(md, (2, 2))
    kinds = [n.kind for n in nodes]
    # bare table / image outside any env; figure env: begin, image, caption, end
    assert kinds == ["block", "table", "image_para",
                     "anchor", "image_para", "caption", "anchor"]
    assert [n.env_scope for n in nodes] == [
        None, None, None, "figure", "figure", "figure", "figure"]


# ------------------------------------------------- op: NumberCaptions


def test_stale_number_replaced_numberless_preserved() -> None:
    stale = TABLE_ENV.replace("表 电量表", "表 4.3-7 电量表")
    ast, nodes = _run_op(stale + "\n" + TABLE_ENV, (2, 2))
    texts = [plain_text(blocks(ast)[n.index]["c"])
             for n in _captions(nodes)]
    assert texts == ["表 2.2-1 电量表", "表 2.2-2 电量表"]
    assert "4.3-7" not in ast_to_md(ast)


def test_placement_moves_caption_both_directions() -> None:
    # caption typed BELOW the table, and a figure caption typed ABOVE the image
    below = """`anchor:begin:table`

| A |
|---|
| 1 |

表 电量表

`anchor:end:table`

`anchor:begin:figure`

图 布置图

![示意图](figure.png)

`anchor:end:figure`
"""
    ast, nodes = _run_op(below, (2, 2))
    bs = blocks(ast)
    order = [n.kind for n in nodes]
    # table env: caption directly above the table; figure env: caption below
    assert order == ["anchor", "caption", "table", "anchor",
                     "anchor", "image_para", "caption", "anchor"]
    assert plain_text(bs[nodes.index(next(n for n in nodes if n.kind == "caption"))]["c"]) == "表 2.2-1 电量表"


def test_annotations_parallel_after_move() -> None:
    ast, nodes = _run_op(TABLE_ENV + "\n" + FIGURE_ENV, (2, 2))
    bs = blocks(ast)
    assert len(nodes) == len(bs)
    assert all(node.index == i for i, node in enumerate(nodes))
    assert all((node.kind == "caption") == (b.get("t") == "Para"
                and plain_text(b.get("c") or []).startswith(("表 ", "图 ")))
               for node, b in zip(nodes, bs))


# ----------------------------------------------------------- CLI seam


def test_caption_numbers_and_placement_in_md_and_docx(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(DATA)  # figure.png resolves relative to the fixture
    rc, draft_docx, emit_md = _draft(CAPTIONS_MD, CAPTIONS_YAML, tmp_path)
    assert rc == 0
    assert emit_md is not None

    # numbers are final in the emitted anchored md BEFORE any DOCX is read:
    # stale 表 4.3-7 replaced; 2.2 / 2.2.3 prefixes; depth-4 clamp to 2.2.3
    emitted = emit_md.read_text(encoding="utf-8")
    for needle in ("表 2.2-1 电量表", "图 2.2-1 布置示意",
                   "表 2.2.3-1 汇总表", "图 2.2.3-1 深层示意"):
        assert needle in emitted, f"{needle} missing from emitted md"
    assert "4.3-7" not in emitted
    # placement visible in the md: caption above its table rows, below image
    assert emitted.index("表 2.2-1 电量表") < emitted.index("T01")
    assert emitted.index("表 2.2.3-1 汇总表") < emitted.index("平均")
    assert emitted.index("](figure.png)") < emitted.index("图 2.2-1 布置示意")

    final = tmp_path / "final.docx"
    rc2 = main(["polish", str(draft_docx), "--snippet", str(CAPTIONS_YAML),
                "--out", str(final)])
    assert rc2 == 0
    text = _plain_text(final)
    for needle in ("表 2.2-1 电量表", "图 2.2-1 布置示意",
                   "表 2.2.3-1 汇总表", "图 2.2.3-1 深层示意"):
        assert needle in text, f"{needle} missing from final docx"
    assert "4.3-7" not in text

    # order in the DOCX body: caption paragraph precedes its table; the
    # figure caption follows the image paragraph
    children = _body_children(final)
    caption_at = _first_index(children, lambda el: "电量表" in _p_text(el))
    table_at = _first_index(children, lambda el: el.tag == f"{W}tbl")
    assert caption_at < table_at
    image_at = _first_index(
        children, lambda el: el.tag == f"{W}p" and el.find(f".//{W}drawing") is not None)
    figure_caption_at = _first_index(children, lambda el: "图 2.2-1 布置示意" in _p_text(el))
    assert image_at < figure_caption_at


def test_captionless_table_warns_but_builds(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    monkeypatch.chdir(DATA)
    rc, draft_docx, _emit = _draft(CAPTIONS_MD, CAPTIONS_YAML, tmp_path, emit=False)
    assert rc == 0 and draft_docx.is_file()
    err = capsys.readouterr().err
    assert "[WARN] captionless-env:" in err
    assert "[ERROR]" not in err

    final = tmp_path / "final.docx"
    rc2 = main(["polish", str(draft_docx), "--snippet", str(CAPTIONS_YAML),
                "--out", str(final)])
    assert rc2 == 0
    # the captionless table is still there, unnumbered
    assert "裸表" in _plain_text(final)


def test_env_start_offsets_at_cli(tmp_path: Path,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(DATA)
    rc, _out, emit_md = _draft(CAPTIONS_START_MD, CAPTIONS_START_YAML, tmp_path)
    assert rc == 0
    emitted = emit_md.read_text(encoding="utf-8")
    # table start 2: first table is 表 <sec>-2, next -3; figure counts from 1
    assert "表 2.2-2 甲表" in emitted
    assert "表 2.2-3 乙表" in emitted
    assert "图 2.2-1 甲图" in emitted
