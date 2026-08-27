"""CLI-seam tests (ticket 02): draft parses/validates anchors, polish strips
them; error classes fail the build listing all findings; warnings don't."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
from snippet_docx.cli import main

DATA = Path(__file__).parent / "data"
PLAIN_MD = DATA / "plain.md"
ANCHORED_MD = DATA / "anchored.md"
ERRORS_MD = DATA / "errors.md"
WARN_MD = DATA / "warn.md"
SNIPPET_YAML = DATA / "snippet.yaml"
SNIPPET_NOSTRAT = DATA / "snippet-nostrat.yaml"


def _document_xml(docx: Path) -> str:
    with zipfile.ZipFile(docx) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def _plain_text(docx: Path) -> str:
    """Tag-stripped document text (adjacent runs concatenate)."""
    return re.sub(r"<[^>]+>", "", _document_xml(docx))


def _draft(md: Path, tmp_path: Path, snippet: Path = SNIPPET_YAML,
           emit: bool = False) -> tuple[int, Path, Path | None]:
    out = tmp_path / "draft.docx"
    emit_md = tmp_path / "anchored.md" if emit else None
    argv = ["draft", str(md), "--snippet", str(snippet), "--out", str(out)]
    if emit_md is not None:
        argv += ["--emit-md", str(emit_md)]
    return main(argv), out, emit_md


def test_draft_produces_docx_via_pandoc(tmp_path: Path) -> None:
    rc, out, _ = _draft(PLAIN_MD, tmp_path)
    assert rc == 0
    assert out.is_file()
    xml = _document_xml(out)
    assert "概述" in xml
    assert "机位数量" in xml


def test_draft_emit_md_roundtrips_content(tmp_path: Path) -> None:
    rc, _out, emit = _draft(PLAIN_MD, tmp_path, emit=True)
    assert rc == 0
    assert emit is not None and emit.is_file()
    emitted = emit.read_text(encoding="utf-8")
    assert "概述" in emitted
    assert "机位数量" in emitted


def test_anchored_roundtrip_zero_residue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(DATA)  # resolve figure.png relative to the fixture
    rc, draft_docx, emit = _draft(ANCHORED_MD, tmp_path, emit=True)
    assert rc == 0

    # block anchors survive pandoc md->docx as VerbatimChar runs (typst_ir
    # mechanism); the inline anchor:section is substituted md-side (ticket 03)
    draft_xml = _document_xml(draft_docx)
    assert "VerbatimChar" in draft_xml
    assert "anchor:begin:table" in draft_xml
    assert "anchor:section" not in draft_xml
    assert "2.2.1" in draft_xml

    # emitted md is the post-md-phase AST converted back to markdown
    assert emit is not None
    emitted = emit.read_text(encoding="utf-8")
    assert "anchor:begin:table" in emitted
    assert "anchor:end:figure" in emitted

    final = tmp_path / "final.docx"
    rc2 = main(["polish", str(draft_docx), "--snippet", str(SNIPPET_YAML),
                "--out", str(final)])
    assert rc2 == 0
    assert final.is_file()

    assert "anchor:" not in _document_xml(final)  # zero residue (raw XML)
    text = _plain_text(final)
    # content survives: captions (now numbered, ticket 04), table cells,
    # prose around the inline anchor
    assert "表 2.2.1-1 风机机位参数表" in text
    assert "图 2.2.1-1 机位布置示意" in text
    assert "T01" in text
    assert "编号下的表格与图示例" in text


def test_all_error_classes_fail_in_one_pass(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc, out, _ = _draft(ERRORS_MD, tmp_path)
    assert rc == 1
    assert not out.exists()  # errors: no outputs written
    err = capsys.readouterr().err
    for code in ("unpaired-anchor", "non-standalone-anchor", "unknown-env",
                 "unknown-global-var", "reserved-ref"):
        assert f"[ERROR] {code}:" in err, f"missing finding {code} in:\n{err}"
    # every finding is reported in the SAME pass (all present at once)
    assert err.count("[ERROR]") >= 6


def test_captionless_env_warns_without_failing(tmp_path: Path,
                                               capsys: pytest.CaptureFixture) -> None:
    rc, out, _ = _draft(WARN_MD, tmp_path)
    assert rc == 0
    assert out.is_file()
    err = capsys.readouterr().err
    assert "[WARN] captionless-env:" in err
    assert "[ERROR]" not in err

    final = tmp_path / "final.docx"
    rc2 = main(["polish", str(out), "--snippet", str(SNIPPET_YAML), "--out", str(final)])
    assert rc2 == 0
    assert "anchor:" not in _document_xml(final)


def test_strategy_flag_and_yaml_key_both_work(tmp_path: Path) -> None:
    # yaml without strategy key -> built-in default
    rc, out, _ = _draft(PLAIN_MD, tmp_path, snippet=SNIPPET_NOSTRAT)
    assert rc == 0 and out.is_file()
    # --strategy flag selects explicitly
    rc3 = main(["draft", str(PLAIN_MD), "--snippet", str(SNIPPET_NOSTRAT),
                "--strategy", "ecepdi", "--out", str(tmp_path / "f3" / "d.docx")])
    assert rc3 == 0


def test_unknown_strategy_fails(tmp_path: Path) -> None:
    snippet = tmp_path / "snippet.yaml"
    snippet.write_text("strategy: acme\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="unknown strategy"):
        main(["draft", str(PLAIN_MD), "--snippet", str(snippet),
              "--out", str(tmp_path / "o.docx")])


def test_missing_input_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="not found"):
        main(["draft", str(tmp_path / "nope.md"), "--snippet", str(SNIPPET_YAML),
              "--out", str(tmp_path / "o.docx")])


def test_polish_missing_docx_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="not found"):
        main(["polish", str(tmp_path / "nope.docx"), "--snippet", str(SNIPPET_YAML),
              "--out", str(tmp_path / "o.docx")])
