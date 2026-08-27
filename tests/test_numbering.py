"""CLI-seam tests (ticket 03): baked heading numbers reach the emitted
anchored markdown and the final DOCX; ``anchor:section`` substitutes inline;
cross-subsection / heading-too-deep warn without failing; string prefixes
format via the strategy; no Word numPr anywhere."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
from snippet_docx.cli import main

DATA = Path(__file__).parent / "data"
NUMBERING_MD = DATA / "numbering.md"
WARNINGS_MD = DATA / "numbering-warnings.md"
SNIPPET_YAML = DATA / "snippet.yaml"           # prefix [2, 2]
START_YAML = DATA / "numbering-start.yaml"     # prefix [2, 2], start {3: 3}
APPENDIX_YAML = DATA / "appendix.yaml"         # prefix ["A"]


def _document_xml(docx: Path) -> str:
    with zipfile.ZipFile(docx) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def _plain_text(docx: Path) -> str:
    """Tag-stripped document text (adjacent runs concatenate)."""
    return re.sub(r"<[^>]+>", "", _document_xml(docx))


def _draft_and_polish(md: Path, snippet: Path, tmp_path: Path) -> tuple[int, Path, str, Path]:
    out = tmp_path / "draft.docx"
    emit_md = tmp_path / "anchored.md"
    rc = main(["draft", str(md), "--snippet", str(snippet), "--out", str(out),
               "--emit-md", str(emit_md)])
    final = tmp_path / "final.docx"
    rc2 = main(["polish", str(out), "--snippet", str(snippet), "--out", str(final)])
    assert rc2 == 0
    return rc, out, emit_md.read_text(encoding="utf-8"), final


def test_baked_numbers_in_md_and_docx(tmp_path: Path) -> None:
    rc, draft_docx, emitted, final = _draft_and_polish(
        NUMBERING_MD, SNIPPET_YAML, tmp_path)
    assert rc == 0

    # emitted anchored md: number baked AND header level rewritten to doc level
    assert "## 2.2 风资源条件" in emitted
    assert "### 2.2.1 测风塔数据" in emitted
    assert "### 2.2.2 数据质量控制" in emitted
    assert "#### 2.2.2.1 更深一级" in emitted

    # both draft and final DOCX carry the baked numbers as literal text
    for docx in (draft_docx, final):
        text = _plain_text(docx)
        assert "2.2 风资源条件" in text
        assert "2.2.1 测风塔数据" in text
        assert "2.2.2.1 更深一级" in text

    # literal text, no Word numPr anywhere; pandoc emits Heading N at the
    # doc level (the rewritten header level, not the author's hashes)
    for docx in (draft_docx, final):
        xml = _document_xml(docx)
        assert "<w:numPr>" not in xml
    # draft keeps pandoc's built-in Heading N pStyles...
    xml = _document_xml(draft_docx)
    assert 'w:val="Heading2"' in xml
    assert 'w:val="Heading3"' in xml
    assert 'w:val="Heading4"' in xml
    # ...polish (ticket 05) restyles them to the named headingN styles
    xml = _document_xml(final)
    assert 'w:val="heading2"' in xml
    assert 'w:val="heading3"' in xml
    assert 'w:val="heading4"' in xml


def test_section_start_offset_continues_numbering(tmp_path: Path) -> None:
    rc, _draft_docx, emitted, final = _draft_and_polish(
        NUMBERING_MD, START_YAML, tmp_path)
    assert rc == 0
    assert "### 2.2.3 测风塔数据" in emitted
    assert "### 2.2.4 数据质量控制" in emitted
    assert "#### 2.2.4.1 更深一级" in emitted
    assert "2.2.3 测风塔数据" in _plain_text(final)
    assert "2.2.4 数据质量控制" in _plain_text(final)


def test_anchor_section_substituted_inline(tmp_path: Path) -> None:
    rc, draft_docx, emitted, final = _draft_and_polish(
        NUMBERING_MD, SNIPPET_YAML, tmp_path)
    assert rc == 0
    # before any heading -> the prefix itself; after a heading -> its number
    assert "本小节编号为 2.2，验证行内编号替换。" in emitted
    assert "本段位于 2.2.1 之后。" in emitted
    assert "anchor:section" not in emitted
    for docx in (draft_docx, final):
        text = _plain_text(docx)
        assert "anchor:section" not in text
        assert "本小节编号为 2.2，验证行内编号替换。" in text
        assert "本段位于 2.2.1 之后。" in text


def test_warnings_do_not_fail_the_build(tmp_path: Path,
                                        capsys: pytest.CaptureFixture) -> None:
    rc, draft_docx, emitted, final = _draft_and_polish(
        WARNINGS_MD, SNIPPET_YAML, tmp_path)
    assert rc == 0
    assert draft_docx.is_file() and final.is_file()
    # the too-deep heading still bakes its number
    assert "2.2.1.1.1.1 过深标题" in emitted
    assert "2.2.1.1.1.1 过深标题" in _plain_text(final)
    err = capsys.readouterr().err
    assert "[WARN] cross-subsection:" in err
    assert "[WARN] heading-too-deep:" in err
    assert "[ERROR]" not in err


def test_string_prefix_appends_via_format_section(tmp_path: Path) -> None:
    rc, _draft_docx, emitted, final = _draft_and_polish(
        NUMBERING_MD, APPENDIX_YAML, tmp_path)
    assert rc == 0
    assert "# A 风资源条件" in emitted
    assert "## A.1 测风塔数据" in emitted
    assert "## A.2 数据质量控制" in emitted
    assert "### A.2.1 更深一级" in emitted
    assert "A 风资源条件" in _plain_text(final)
    assert "A.2.1 更深一级" in _plain_text(final)
