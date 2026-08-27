"""CLI-seam tests (ticket 08): jinja render + strategy anchor macros.

``draft --template t.md.j2 --data d.yaml`` renders the template (with the
strategy's jinja globals in scope) as its first phase; the rendered markdown
then flows through the whole existing pipeline. Caption NUMBERING is ticket
04 — these tests assert render -> validate -> docx, not final caption numbers.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import ClassVar

import pytest
from snippet_docx.cli import main
from snippet_docx.jinja_render import (
    TemplateRenderError,
    build_anchor_globals,
    render_template,
)
from snippet_docx.strategy import EnvSpec, get_strategy

DATA = Path(__file__).parent / "data"
TEMPLATE = DATA / "tables.md.j2"
TABLES_YAML = DATA / "tables.yaml"
SNIPPET_YAML = DATA / "snippet.yaml"
STRATEGY = get_strategy("ecepdi")


def _document_text(docx: Path) -> str:
    with zipfile.ZipFile(docx) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", xml)


def _draft(tmp_path: Path, emit: bool = True) -> tuple[int, Path, Path | None]:
    out = tmp_path / "draft.docx"
    emit_md = tmp_path / "anchored.md" if emit else None
    argv = ["draft", "--template", str(TEMPLATE), "--data", str(TABLES_YAML),
            "--snippet", str(SNIPPET_YAML), "--out", str(out)]
    if emit_md is not None:
        argv += ["--emit-md", str(emit_md)]
    return main(argv), out, emit_md


def test_template_data_renders_end_to_end(tmp_path: Path,
                                          capsys: pytest.CaptureFixture) -> None:
    rc, out, _emit = _draft(tmp_path)
    assert rc == 0
    assert out.is_file()
    assert "[ERROR]" not in capsys.readouterr().err
    rc = main(["polish", str(out), "--snippet", str(SNIPPET_YAML),
               "--out", str(tmp_path / "final.docx")])
    assert rc == 0
    text = _document_text(tmp_path / "final.docx")
    assert "数据驱动表格" in text          # data-driven heading
    assert "风机机位参数表" in text        # data-driven caption 1
    assert "回路 2" in text                # data-driven row content
    assert "anchor:" not in text           # stripped in polish (ticket 02 op)


def test_rendered_macros_emit_exact_grammar(tmp_path: Path,
                                            capsys: pytest.CaptureFixture) -> None:
    """Rendered anchors are exactly ticket-02 grammar and validate clean."""
    rc, _out, emit = _draft(tmp_path)
    assert rc == 0
    assert "[ERROR]" not in capsys.readouterr().err  # zero findings of error class
    rendered = emit.read_text(encoding="utf-8")
    lines = rendered.splitlines()
    # standalone anchor lines, exactly two of each, nothing else on the line
    assert [ln for ln in lines if "anchor:begin" in ln] == [
        "`anchor:begin:table`", "`anchor:begin:table`"]
    assert [ln for ln in lines if "anchor:end" in ln] == [
        "`anchor:end:table`", "`anchor:end:table`"]
    # the inline global-var anchor rides inside prose in the RENDERED markdown;
    # the md numbering phase (ticket 03) substitutes it pre-pandoc, so the
    # emitted anchored md shows the baked number instead
    rendered_raw = render_template(TEMPLATE, TABLES_YAML, STRATEGY)
    assert "`anchor:section`" in rendered_raw
    # no anchor forms outside the registered macros leaked
    assert set(re.findall(r"`anchor:[^`]+`", rendered_raw)) == {
        "`anchor:begin:table`", "`anchor:end:table`", "`anchor:section`"}


def test_repeated_tables_all_appear_in_docx(tmp_path: Path) -> None:
    rc, out, _emit = _draft(tmp_path, emit=False)
    assert rc == 0
    text = _document_text(out)
    for needle in ("T01", "T02", "LGJ-240", "LGJ-300",
                   "风机机位参数表", "集电线路参数表"):
        assert needle in text


def test_anchor_globals_built_from_registry() -> None:
    """Macros reflect the strategy's registries, not hardcoded env names."""
    class _StubStrategy:
        name = "stub"
        envs: ClassVar[dict] = {
            "widget": EnvSpec(name="widget", label="件", caption_placement="above"),
            "panel": EnvSpec(name="panel", label="板", caption_placement="below"),
        }
        global_vars: ClassVar[dict] = {"chap": lambda state: "C1"}

    anchor = build_anchor_globals(_StubStrategy())["anchor"]  # type: ignore[arg-type]
    assert anchor.begin("widget") == "`anchor:begin:widget`"
    assert anchor.end("panel") == "`anchor:end:panel`"
    assert anchor.inline("chap") == "`anchor:chap`"
    with pytest.raises(ValueError, match="unknown env"):
        anchor.begin("table")   # ecepdi name — not registered on the stub
    with pytest.raises(ValueError, match="unknown global var"):
        anchor.inline("section")


def test_render_template_missing_data_key_fails(tmp_path: Path) -> None:
    template = tmp_path / "t.md.j2"
    template.write_text("{{ tables }}", encoding="utf-8")
    data = tmp_path / "d.yaml"
    data.write_text("other: 1\n", encoding="utf-8")
    with pytest.raises(TemplateRenderError, match="'tables' is undefined"):
        render_template(template, data, STRATEGY)


def test_template_without_data_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="--template requires --data"):
        main(["draft", "--template", str(TEMPLATE),
              "--snippet", str(SNIPPET_YAML), "--out", str(tmp_path / "o.docx")])


def test_input_and_template_are_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="mutually exclusive"):
        main(["draft", str(DATA / "plain.md"), "--template", str(TEMPLATE),
              "--data", str(TABLES_YAML), "--snippet", str(SNIPPET_YAML),
              "--out", str(tmp_path / "o.docx")])


def test_data_without_template_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no input given"):
        main(["draft", "--data", str(TABLES_YAML), "--snippet", str(SNIPPET_YAML),
              "--out", str(tmp_path / "o.docx")])


def test_unknown_env_in_template_fails_build(tmp_path: Path) -> None:
    template = tmp_path / "bad.md.j2"
    template.write_text("{{ anchor.begin('mystery') }}\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="unknown env 'mystery'"):
        main(["draft", "--template", str(template), "--data", str(TABLES_YAML),
              "--snippet", str(SNIPPET_YAML), "--out", str(tmp_path / "o.docx")])
