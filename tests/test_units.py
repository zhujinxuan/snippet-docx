"""Pure-function tests (ToolSpec §8.1): anchor grammar parser (valid/invalid
corpus), validator policy, config validation, strategy data, pandoc helpers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from snippet_docx.anchors import parse_anchors, validate_anchors
from snippet_docx.config import Config, ConfigError, load_config
from snippet_docx.ops_docx import StripAnchors, ecepdi_docx_ops
from snippet_docx.ops_md import (
    NumberCaptions,
    SetHeadingNumber,
    SubstituteGlobalVar,
    ValidateAnchors,
    ecepdi_md_ops,
)
from snippet_docx.pandoc_ast import (
    ast_to_md,
    blocks,
    code_paragraph_payload,
    inline_code_spans,
    make_code_paragraph,
    make_para,
    md_to_ast,
    paragraph_starts_with_code,
    plain_text,
)
from snippet_docx.pipeline import Ctx, run_phase
from snippet_docx.strategies.ecepdi import EcepdiStrategy
from snippet_docx.strategy import EnvSpec, get_strategy, registered_strategies
from snippet_docx.styles import deep_merge, load_packaged_defaults

DATA = Path(__file__).parent / "data"
STRATEGY = EcepdiStrategy()

GRAMMAR_MD = """prose with `anchor:section` inline.

`anchor:begin:table`

`anchor:env:table:paper=a4`

`anchor:end:table`

`anchor:ref:tab1`
"""


# ---------------------------------------------------------------------------
# pandoc_ast helpers
# ---------------------------------------------------------------------------

def test_code_paragraph_payload_roundtrip() -> None:
    para = make_code_paragraph("`anchor:begin:table`"[1:-1])  # anchor:begin:table
    assert code_paragraph_payload(para, "anchor:") == "begin:table"
    assert code_paragraph_payload(para, "marker:") is None


def test_code_paragraph_payload_rejects_non_standalone() -> None:
    glued = {"t": "Para", "c": [
        {"t": "Code", "c": [["", [], []], "anchor:begin:table"]},
        {"t": "Space"},
        {"t": "Str", "c": "prose"},
    ]}
    assert code_paragraph_payload(glued, "anchor:") is None
    assert paragraph_starts_with_code(glued, "anchor:") == "begin:table"


def test_paragraph_starts_with_code_standalone_is_none() -> None:
    para = make_code_paragraph("anchor:end:figure")
    assert paragraph_starts_with_code(para, "anchor:") is None


def test_inline_code_spans_finds_nested() -> None:
    para = {"t": "Para", "c": [
        {"t": "Str", "c": "see"},
        {"t": "Space"},
        {"t": "Code", "c": [["", [], []], "anchor:section"]},
        {"t": "Emph", "c": [
            {"t": "Code", "c": [["", [], []], "anchor:other"]},
        ]},
    ]}
    spans = inline_code_spans(para, "anchor:")
    assert [payload for _el, payload in spans] == ["section", "other"]


def test_plain_text_flattens() -> None:
    para = make_para("hello world")
    assert plain_text(para["c"]) == "hello world"
    mixed = {"t": "Para", "c": [
        {"t": "Str", "c": "表"},
        {"t": "Space"},
        {"t": "Emph", "c": [{"t": "Str", "c": "重点"}]},
        {"t": "Code", "c": [["", [], []], "x=1"]},
    ]}
    assert plain_text(mixed["c"]) == "表 重点x=1"


def test_md_to_ast_and_back() -> None:
    ast = md_to_ast("`anchor:begin:table`\n")
    para = blocks(ast)[0]
    assert code_paragraph_payload(para, "anchor:") == "begin:table"
    md = ast_to_md(ast)
    assert "`anchor:begin:table`" in md


# ---------------------------------------------------------------------------
# anchor parsing (BNF corpus)
# ---------------------------------------------------------------------------

def test_parse_anchors_corpus() -> None:
    anchors = parse_anchors(md_to_ast(GRAMMAR_MD))
    by_attr = [(a.kind, a.env, a.key, a.value, a.name, a.inline) for a in anchors]
    assert by_attr == [
        ("global_var", None, None, None, "section", True),
        ("begin", "table", None, None, None, False),
        ("env_var", "table", "paper", "a4", None, False),
        ("end", "table", None, None, None, False),
        ("ref", None, None, None, "tab1", False),
    ]
    assert [a.block_index for a in anchors] == [0, 1, 2, 3, 4]


def test_parse_anchors_custom_prefix() -> None:
    ast = md_to_ast("`mark:begin:widget`\n")
    assert parse_anchors(ast, "mark:")[0].env == "widget"
    assert parse_anchors(ast, "anchor:") == []


def test_parse_anchors_malformed_env_var_is_global_var() -> None:
    ast = md_to_ast("`anchor:env:table`\n")
    assert parse_anchors(ast)[0].kind == "global_var"


# ---------------------------------------------------------------------------
# validation policy
# ---------------------------------------------------------------------------

def _codes(ast: dict, strategy=STRATEGY) -> list[tuple[str, str]]:
    findings = validate_anchors(parse_anchors(ast), ast, strategy)
    return [(f.code, f.severity) for f in findings]


def test_valid_document_has_no_findings() -> None:
    assert _codes(md_to_ast((DATA / "anchored.md").read_text(encoding="utf-8"))) == []


def test_error_classes_and_messages() -> None:
    md = """`anchor:begin:mystery`

`anchor:end:mystery`

`anchor:nope`

`anchor:ref:x`
"""
    codes = _codes(md_to_ast(md))
    assert codes.count(("unknown-env", "error")) == 2
    assert ("unknown-global-var", "error") in codes
    assert ("reserved-ref", "error") in codes


def test_unpaired_and_mismatch() -> None:
    unpaired = _codes(md_to_ast("`anchor:begin:table`\n"))
    assert unpaired == [("unpaired-anchor", "error")]

    stray_end = _codes(md_to_ast("`anchor:end:table`\n"))
    assert stray_end == [("unpaired-anchor", "error")]

    mismatch = _codes(md_to_ast("`anchor:begin:table`\n\n`anchor:end:figure`\n"))
    # mismatched end + leftover begin
    assert mismatch.count(("unpaired-anchor", "error")) == 2


def test_non_standalone_begin_end() -> None:
    codes = _codes(md_to_ast("`anchor:begin:table` glued prose\n"))
    assert ("non-standalone-anchor", "error") in codes
    # the glued begin also stays unpaired
    assert ("unpaired-anchor", "error") in codes


def test_nesting_violation_table_in_figure() -> None:
    md = "`anchor:begin:figure`\n\n`anchor:begin:table`\n\n`anchor:end:table`\n\n`anchor:end:figure`\n"
    codes = _codes(md_to_ast(md))
    assert ("nesting-violation", "error") in codes


def test_env_var_outside_block() -> None:
    codes = _codes(md_to_ast("`anchor:env:table:paper=a4`\n"))
    assert ("env-var-outside-block", "error") in codes


def test_captionless_env_is_warning_with_caption_required_false() -> None:
    md = "`anchor:begin:table`\n\n| A |\n|---|\n| 1 |\n\n`anchor:end:table`\n"
    assert _codes(md_to_ast(md)) == [("captionless-env", "warn")]


def test_caption_found_by_label_prefix() -> None:
    md = "`anchor:begin:table`\n\n表 参数表\n\n| A |\n|---|\n| 1 |\n\n`anchor:end:table`\n"
    assert _codes(md_to_ast(md)) == []


def test_caption_required_promotes_to_error() -> None:
    strict = replace(STRATEGY, envs={
        "table": EnvSpec(name="table", label="表", caption_placement="above",
                         caption_required=True)})
    md = "`anchor:begin:table`\n\n`anchor:end:table`\n"
    assert _codes(md_to_ast(md), strict) == [("captionless-env", "error")]


def test_env_registry_is_strategy_data_not_hardcoded() -> None:
    widget = replace(STRATEGY, envs={"widget": EnvSpec(name="widget", label="件",
                                                       caption_placement="above")})
    md = "`anchor:begin:widget`\n\n件 一号件\n\n`anchor:end:widget`\n"
    assert _codes(md_to_ast(md), widget) == []          # widget is valid now
    codes = _codes(md_to_ast(md), STRATEGY)             # and unknown to ecepdi
    assert ("unknown-env", "error") in codes


def test_severities_table() -> None:
    sev = STRATEGY.severities()
    for code in ("unpaired-anchor", "non-standalone-anchor", "unknown-env",
                 "unknown-global-var", "reserved-ref"):
        assert sev[code] == "error"
    for code in ("captionless-env", "cross-subsection", "heading-too-deep"):
        assert sev[code] == "warn"


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def test_load_config_defaults() -> None:
    config, strategy = load_config(DATA / "snippet.yaml", None)
    assert strategy.name == "ecepdi"
    assert config.strategy == "ecepdi"
    assert config.prefix == (2, 2)
    assert config.section_start == {}
    assert config.env_start == {}
    assert config.caption_max_depth == 3
    assert config.landscape_paper == "a4"
    assert config.anchor_prefix == "anchor:"
    assert config.styles == {}


def test_load_config_full() -> None:
    snippet = DATA / "full-snippet.yaml"
    config, _ = load_config(snippet, None)
    assert config.prefix == (2, 2)
    assert config.section_start == {3: 3}
    assert config.env_start == {"table": 2, "figure": 5}
    assert config.caption_max_depth == 4
    assert config.anchor_prefix == "mark:"
    assert config.styles == {"style": {"heading1": {"font_size_pt": 14}}}


def test_load_config_strategy_override_wins() -> None:
    config, strategy = load_config(DATA / "snippet.yaml", "ecepdi")
    assert config.strategy == "ecepdi" and strategy.name == "ecepdi"


def _bad_config(tmp_path: Path, text: str) -> None:
    snippet = tmp_path / "snippet.yaml"
    snippet.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(snippet, None)


def test_config_prefix_required(tmp_path: Path) -> None:
    _bad_config(tmp_path, "strategy: ecepdi\n")


def test_config_prefix_bad_element(tmp_path: Path) -> None:
    _bad_config(tmp_path, "section:\n  prefix: [2, 2.5]\n")


def test_config_section_start_too_shallow(tmp_path: Path) -> None:
    _bad_config(tmp_path, "section:\n  prefix: [2, 2]\nnumbering:\n  sections:\n    start: {2: 5}\n")


def test_config_landscape_a3_not_implemented(tmp_path: Path) -> None:
    _bad_config(tmp_path, "section:\n  prefix: [2, 2]\nlandscape:\n  paper: a3\n")


def test_config_bad_caption_depth(tmp_path: Path) -> None:
    _bad_config(tmp_path, "section:\n  prefix: [2, 2]\nnumbering:\n  caption:\n    max_depth: 3.5\n")


def test_unknown_strategy_lists_registered_names(tmp_path: Path) -> None:
    snippet = tmp_path / "snippet.yaml"
    snippet.write_text("section:\n  prefix: [2, 2]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="available.*ecepdi"):
        load_config(snippet, "acme")


def test_missing_snippet_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml", None)


# ---------------------------------------------------------------------------
# strategy data / formats / jinja globals
# ---------------------------------------------------------------------------

def test_registered_strategies_and_get() -> None:
    registry = registered_strategies()
    assert "ecepdi" in registry
    assert get_strategy("ecepdi") is registry["ecepdi"]
    with pytest.raises(KeyError, match="available"):
        get_strategy("nope")


def test_ecepdi_env_registry() -> None:
    assert set(STRATEGY.envs) == {"table", "figure", "landscape"}
    assert STRATEGY.envs["table"].label == "表"
    assert STRATEGY.envs["table"].caption_placement == "above"
    assert STRATEGY.envs["figure"].label == "图"
    assert STRATEGY.envs["figure"].caption_placement == "below"
    assert STRATEGY.envs["landscape"].numbered is False


def test_format_section_and_caption_clamp() -> None:
    assert STRATEGY.format_section((2, 2, 3)) == "2.2.3"
    assert STRATEGY.format_section(("A", 1)) == "A.1"
    spec = STRATEGY.envs["table"]
    assert STRATEGY.format_caption(spec, (2, 2, 3), 1, "参数表") == "表 2.2.3-1 参数表"
    # format_caption formats the path verbatim — clamping to
    # config.caption_max_depth is owned by NumberCaptions (ops_md), not the
    # strategy (contract §5: tool clamps, strategy formats)
    assert STRATEGY.format_caption(spec, (2, 2, 3, 1), 2, "参数表") == "表 2.2.3.1-2 参数表"


def test_global_var_section_uses_state() -> None:
    state = type("State", (), {"section_path": (2, 2, 3)})()
    assert STRATEGY.global_vars["section"](state) == "2.2.3"


def test_jinja_anchor_globals_grammar() -> None:
    anchor = STRATEGY.jinja_globals()["anchor"]
    assert anchor.begin("table") == "`anchor:begin:table`"
    assert anchor.end("figure") == "`anchor:end:figure`"
    assert anchor.inline("section") == "`anchor:section`"
    with pytest.raises(ValueError, match="unknown env"):
        anchor.begin("mystery")
    with pytest.raises(ValueError, match="unknown global var"):
        anchor.inline("nope")


def test_op_lists() -> None:
    md_ops = ecepdi_md_ops()
    assert len(md_ops) == 4
    assert isinstance(md_ops[0], ValidateAnchors)      # validate before numbering
    assert isinstance(md_ops[1], SetHeadingNumber)
    assert isinstance(md_ops[2], NumberCaptions)       # captions numbered before vars
    assert isinstance(md_ops[3], SubstituteGlobalVar)
    docx_ops = ecepdi_docx_ops()
    assert isinstance(docx_ops[-1], StripAnchors)   # StripAnchors always last
    normalize_ops = STRATEGY.md_normalize_ops()    # ticket 06 seam: wired
    assert [type(op).__name__ for op in normalize_ops] == \
        ["NormalizeTables", "NormalizeImages"]


def test_wrap_phase_transparent() -> None:
    config, strategy = load_config(DATA / "snippet.yaml", None)
    ctx = Ctx(config=config, strategy=strategy)
    seen: list[str] = []

    def proceed(c: Ctx) -> Ctx:
        seen.append("ran")
        return c

    out = run_phase("md_number", ctx, proceed)
    assert seen == ["ran"] and out is ctx


def test_run_phase_enforces_proceed_once() -> None:
    config, _strategy = load_config(DATA / "snippet.yaml", None)

    class NeverCalls:
        name = "never"

        def wrap_phase(self, phase, ctx, proceed):
            return ctx  # defect: proceed never called

    class TwiceCalls:
        name = "twice"

        def wrap_phase(self, phase, ctx, proceed):
            proceed(ctx)
            proceed(ctx)
            return ctx

    for bad in (NeverCalls(), TwiceCalls()):
        ctx = Ctx(config=config, strategy=bad)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="exactly 1"):
            run_phase("md_number", ctx, lambda c: c)


def test_validate_op_through_ctx() -> None:
    config, strategy = load_config(DATA / "snippet.yaml", None)
    ctx = Ctx(config=config, strategy=strategy)
    ast = md_to_ast("`anchor:begin:mystery`\n")
    findings = ValidateAnchors()(ast, ctx)
    assert [(f.code, f.severity) for f in findings] == [("unknown-env", "error")]


# ---------------------------------------------------------------------------
# styles
# ---------------------------------------------------------------------------

def test_load_packaged_defaults() -> None:
    defaults = load_packaged_defaults()
    assert defaults["style"]["heading1"]["chinese_font"] == "宋体"
    assert defaults["style"]["table"]["font_size_pt"] == 9


def test_deep_merge() -> None:
    base = {"a": 1, "nested": {"x": 1, "y": 2}, "keep": "base"}
    override = {"b": 2, "nested": {"y": 3, "z": 4}}
    assert deep_merge(base, override) == {
        "a": 1, "b": 2, "keep": "base", "nested": {"x": 1, "y": 3, "z": 4},
    }
    assert base["nested"] == {"x": 1, "y": 2}   # base untouched


def test_default_styles_delegates_to_packaged() -> None:
    assert STRATEGY.default_styles() == load_packaged_defaults()


def test_config_is_frozen() -> None:
    config = Config(strategy="ecepdi", prefix=(1,))
    with pytest.raises(AttributeError):
        config.strategy = "other"  # type: ignore[misc]
