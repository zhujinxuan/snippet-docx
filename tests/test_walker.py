"""Pure walker tests (ticket 03, ToolSpec §8.1): the section state machine —
doc-level mapping, offsets, skipped levels, string path elements, and the
cross-subsection / heading-too-deep warnings carried as NodeInfo findings."""

from __future__ import annotations

from snippet_docx.config import Config
from snippet_docx.pandoc_ast import md_to_ast
from snippet_docx.strategies.ecepdi import EcepdiStrategy
from snippet_docx.walker import NodeInfo, build_annotations

STRATEGY = EcepdiStrategy()


def _walk(md: str, prefix: tuple[int | str, ...],
          start: dict[int, int] | None = None) -> list[NodeInfo]:
    config = Config(strategy="ecepdi", prefix=prefix, section_start=start or {})
    return build_annotations(md_to_ast(md), config, STRATEGY)


def _headings(nodes: list[NodeInfo]) -> list[NodeInfo]:
    return [n for n in nodes if n.kind == "heading"]


def test_hashes_map_to_doc_levels() -> None:
    nodes = _walk("# 甲\n\n## 乙\n\n### 丙\n", (2, 2))
    assert [(n.doc_level, n.section_path) for n in _headings(nodes)] == [
        (2, (2, 2)), (3, (2, 2, 1)), (4, (2, 2, 1, 1)),
    ]


def test_deeper_levels_count_and_reset() -> None:
    nodes = _walk("## 甲\n\n## 乙\n\n### 丙\n\n## 丁\n", (2, 2))
    assert [n.section_path for n in _headings(nodes)] == [
        (2, 2, 1), (2, 2, 2), (2, 2, 2, 1), (2, 2, 3),
    ]


def test_section_start_offset() -> None:
    nodes = _walk("## 甲\n\n## 乙\n\n### 丙\n", (2, 2), start={3: 3})
    assert [n.section_path for n in _headings(nodes)] == [
        (2, 2, 3), (2, 2, 4), (2, 2, 4, 1),
    ]


def test_skipped_intermediate_level_initializes_at_start() -> None:
    # level 3 skipped -> lazily its start value; level 4 heading counts from 1
    nodes = _walk("# 甲\n\n### 乙\n", (2, 2), start={3: 5})
    assert _headings(nodes)[1].section_path == (2, 2, 5, 1)


def test_root_heading_resets_deeper_counters() -> None:
    nodes = _walk("## 甲\n\n## 乙\n\n# 丙\n\n## 丁\n", (2, 2))
    assert [n.section_path for n in _headings(nodes)] == [
        (2, 2, 1), (2, 2, 2), (2, 2), (2, 2, 1),
    ]


def test_cross_subsection_second_root_warns() -> None:
    nodes = _walk("# 甲\n\n# 乙\n", (2, 2))
    first, second = _headings(nodes)
    assert first.findings == []
    assert [(f.code, f.severity) for f in second.findings] == [
        ("cross-subsection", "warn")]
    assert "undefined" in second.findings[0].message
    assert second.section_path == (2, 2)  # build continues; root counter fixed


def test_heading_too_deep_warns_but_still_numbers() -> None:
    nodes = _walk("##### 甲\n", (2, 2))
    (heading,) = _headings(nodes)
    assert heading.doc_level == 6
    assert heading.section_path == (2, 2, 1, 1, 1, 1)
    assert [(f.code, f.severity) for f in heading.findings] == [
        ("heading-too-deep", "warn")]


def test_string_path_elements() -> None:
    nodes = _walk("# 附录\n\n## 附录子\n", ("A",))
    assert [n.section_path for n in _headings(nodes)] == [("A",), ("A", 1)]
    assert STRATEGY.format_section(("A", 1)) == "A.1"


def test_anchor_before_any_heading_gets_the_prefix() -> None:
    nodes = _walk("开篇 `anchor:section` 引用。\n\n# 甲\n", (2, 2))
    prose, heading = nodes[0], nodes[1]
    assert prose.kind == "anchor"
    assert prose.section_path == (2, 2)
    assert prose.anchor is not None and prose.anchor.name == "section"
    assert heading.kind == "heading"


def test_anchor_after_heading_gets_enclosing_section() -> None:
    nodes = _walk("# 甲\n\n## 乙\n\n位于 `anchor:section` 处。\n", (2, 2))
    prose = nodes[-1]
    assert prose.kind == "anchor"
    assert prose.section_path == (2, 2, 1)


def test_every_block_annotated_exactly_once() -> None:
    nodes = _walk("段落一。\n\n# 甲\n\n```\ncode\n```\n", (2, 2))
    assert [n.index for n in nodes] == list(range(len(nodes)))
    assert [n.kind for n in nodes] == ["block", "heading", "block"]
    assert all(n.section_path == (2, 2) for n in nodes)


def test_default_nodeinfo_is_a_plain_block() -> None:
    node = NodeInfo(index=3)
    assert node.kind == "block"
    assert node.section_path == ()
    assert node.findings == []
