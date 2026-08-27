"""Plugin-seam contract tests (ticket 09, ToolSpec §5).

Proves the acceptance test of the whole design: a second house style
(``testhouse``, shipped as a fixture package that registers ONLY through
the ``snippet_docx.strategies`` entry-point group) produces its style
through the SAME pipeline with zero edits to the pipeline, validator, or
anchor parser. The strategy surface itself (registries, format functions,
op lists, severities, jinja globals, wrap_phase) is asserted for every
strategy, parametrized over ecepdi and testhouse.
"""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from snippet_docx import styles
from snippet_docx.cli import main
from snippet_docx.config import ConfigError, load_config
from snippet_docx.pipeline import Ctx, run_phase
from snippet_docx.strategy import EnvSpec, get_strategy, registered_strategies
from snippet_docx_testhouse import TESTHOUSE
from snippet_docx_testhouse import TesthouseStrategy as _TesthouseStrategy

DATA = Path(__file__).parent / "data"
SNIPPET = DATA / "snippet.yaml"            # strategy: ecepdi
TESTHOUSE_SNIPPET = DATA / "testhouse.yaml"  # strategy: testhouse
TESTHOUSE_MD = DATA / "testhouse.md"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: expected surface values per strategy — the two house styles must diverge
#: through data and pure functions only
_EXPECTED = {
    "ecepdi": {
        "sections": {(2,): "2", (2, 2, 3): "2.2.3", ("A", 1): "A.1"},
        "table_label": "表", "figure_label": "图",
        "table_placement": "above", "figure_placement": "below",
        "table_scope": "section", "figure_scope": "section",
        "table_caption": "表 2.2.3-1 电量表",
        "figure_caption": "图 2.2.3-4 布置图",
        "section_var": "2.2.3",
        "caption_font": "宋体",
    },
    "testhouse": {
        "sections": {(2,): "2", (2, 2, 3): "2-2-3", ("A", 1): "A-1"},
        "table_label": "Table", "figure_label": "Figure",
        "table_placement": "below", "figure_placement": "above",
        "table_scope": "chapter", "figure_scope": "chapter",
        "table_caption": "Table 2-1: 电量表",   # chapter-scope prefix + index
        "figure_caption": "Figure 2-4: 布置图",
        "section_var": "2-2-3",
        "caption_font": "仿宋",
    },
}

_REQUIRED_SEVERITIES = {
    "unpaired-anchor": "error",
    "non-standalone-anchor": "error",
    "unknown-env": "error",
    "unknown-global-var": "error",
    "reserved-ref": "error",
    "captionless-env": "warn",
    "cross-subsection": "warn",
    "heading-too-deep": "warn",
}


@dataclass
class _State:
    """Minimal NumberingState for global-var resolver tests."""

    section_path: tuple[int | str, ...]


# ------------------------------------------------- registration (the seam)


def test_testhouse_registers_via_entry_point_group() -> None:
    names = {ep.name for ep in entry_points(group="snippet_docx.strategies")}
    assert "testhouse" in names


def test_registry_holds_builtin_and_plugin() -> None:
    registry = registered_strategies()
    assert set(registry) >= {"ecepdi", "testhouse"}
    assert get_strategy("testhouse") is TESTHOUSE  # the entry-point instance


@pytest.mark.parametrize("name", ["ecepdi", "testhouse"])
def test_get_strategy_roundtrip(name: str) -> None:
    assert get_strategy(name).name == name


# ------------------------------------------- strategy surface (parametrized)


@pytest.mark.parametrize("name", ["ecepdi", "testhouse"])
def test_envs_registry(name: str) -> None:
    strategy = get_strategy(name)
    expected = _EXPECTED[name]
    assert set(strategy.envs) >= {"table", "figure"}
    for env_name, spec in strategy.envs.items():
        assert isinstance(spec, EnvSpec)
        assert spec.name == env_name
        assert spec.label
        assert spec.caption_placement in ("above", "below")
        assert spec.counter_scope in ("section", "chapter", "continuous")
    assert strategy.envs["table"].label == expected["table_label"]
    assert strategy.envs["figure"].label == expected["figure_label"]
    assert strategy.envs["table"].caption_placement == expected["table_placement"]
    assert strategy.envs["figure"].caption_placement == expected["figure_placement"]
    assert strategy.envs["table"].counter_scope == expected["table_scope"]
    assert strategy.envs["figure"].counter_scope == expected["figure_scope"]


@pytest.mark.parametrize("name", ["ecepdi", "testhouse"])
def test_global_vars_registry(name: str) -> None:
    strategy = get_strategy(name)
    assert "section" in strategy.global_vars
    resolver = strategy.global_vars["section"]
    assert callable(resolver)
    assert resolver(_State(section_path=(2, 2, 3))) == _EXPECTED[name]["section_var"]


@pytest.mark.parametrize("name", ["ecepdi", "testhouse"])
def test_format_section_pure_and_house_shaped(name: str) -> None:
    strategy = get_strategy(name)
    envs_before = dict(strategy.envs)
    vars_before = dict(strategy.global_vars)
    for path, expected in _EXPECTED[name]["sections"].items():
        first = strategy.format_section(path)
        assert first == expected
        assert strategy.format_section(path) == first  # same inputs, same output
    assert dict(strategy.envs) == envs_before      # no registry mutation
    assert dict(strategy.global_vars) == vars_before


@pytest.mark.parametrize("name", ["ecepdi", "testhouse"])
def test_format_caption_pure_and_house_shaped(name: str) -> None:
    strategy = get_strategy(name)
    expected = _EXPECTED[name]
    for env_key, key in (("table", "table_caption"), ("figure", "figure_caption")):
        env = strategy.envs[env_key]
        first = strategy.format_caption(env, (2, 2, 3), 4 if env_key == "figure" else 1,
                                        "电量表" if env_key == "table" else "布置图")
        assert first == expected[key]
        again = strategy.format_caption(env, (2, 2, 3), 4 if env_key == "figure" else 1,
                                        "电量表" if env_key == "table" else "布置图")
        assert again == first  # same inputs, same output


@pytest.mark.parametrize("name", ["ecepdi", "testhouse"])
def test_op_lists_are_callables(name: str) -> None:
    strategy = get_strategy(name)
    for ops in (strategy.md_ops(), strategy.docx_ops(), strategy.md_normalize_ops()):
        assert isinstance(ops, list)
        assert all(callable(op) for op in ops)
    assert strategy.md_ops()          # numbering ops always present
    assert strategy.docx_ops()        # styling/strip ops always present


@pytest.mark.parametrize("name", ["ecepdi", "testhouse"])
def test_severities_cover_validation_policy(name: str) -> None:
    severities = get_strategy(name).severities()
    for code, severity in _REQUIRED_SEVERITIES.items():
        assert severities[code] == severity
    assert set(severities.values()) <= {"error", "warn"}


@pytest.mark.parametrize("name", ["ecepdi", "testhouse"])
def test_jinja_globals_built_from_envs(name: str) -> None:
    anchor = get_strategy(name).jinja_globals()["anchor"]
    assert anchor.begin("table") == "`anchor:begin:table`"
    assert anchor.end("figure") == "`anchor:end:figure`"
    assert anchor.inline("section") == "`anchor:section`"
    with pytest.raises(ValueError, match="unknown env"):
        anchor.begin("no-such-env")
    with pytest.raises(ValueError, match="unknown global"):
        anchor.inline("no-such-var")


@pytest.mark.parametrize("name", ["ecepdi", "testhouse"])
def test_default_styles_mergeable_with_house_fonts(name: str) -> None:
    defaults = get_strategy(name).default_styles()
    entries = defaults["style"]
    for style_name in ("heading1", "heading5", "normal_text", "table_caption",
                       "figure_caption", "table", "list_item"):
        assert style_name in entries
    assert entries["table_caption"]["chinese_font"] == _EXPECTED[name]["caption_font"]
    merged = styles.deep_merge(defaults, {"style": {"heading2": {"bold": False}}})
    assert merged["style"]["heading2"]["bold"] is False
    assert merged["style"]["heading1"] == entries["heading1"]  # siblings untouched


@pytest.mark.parametrize("name", ["ecepdi", "testhouse"])
def test_parse_config_strategy_slice(name: str) -> None:
    strategy = get_strategy(name)
    config = strategy.parse_config({
        "section": {"prefix": [2, 2]},
        "numbering": {"table": {"start": 5}, "caption": {"max_depth": 2}},
    })
    assert config.strategy == name
    assert config.prefix == (2, 2)
    assert config.env_start == {"table": 5}
    assert config.caption_max_depth == 2
    with pytest.raises(ConfigError, match="max_depth"):
        strategy.parse_config({"section": {"prefix": [2, 2]},
                               "numbering": {"caption": {"max_depth": "x"}}})


# ------------------------------------------------------- wrap_phase (L3)


@pytest.mark.parametrize("name", ["ecepdi", "testhouse"])
def test_wrap_phase_default_transparent_proceeds_once(name: str) -> None:
    strategy = get_strategy(name)
    ctx = Ctx(config=strategy.parse_config({"section": {"prefix": [2, 2]}}),
              strategy=strategy)
    ran: list[str] = []

    def proceed(c: Ctx) -> Ctx:
        ran.append(c.strategy.name)
        return c

    assert run_phase("md_number", ctx, proceed) is ctx
    assert ran == [name]


@dataclass(frozen=True)
class _BrokenWrapStrategy(_TesthouseStrategy):
    """Full strategy surface, wrap_phase defective: calls proceed ``calls`` times."""

    calls: int = 0
    name: str = "broken-wrap"

    def wrap_phase(self, phase, ctx, proceed):  # type: ignore[override]
        for _ in range(self.calls):
            ctx = proceed(ctx)
        return ctx


@pytest.mark.parametrize("calls", [0, 2])
def test_wrap_phase_wrong_proceed_count_raises(calls: int) -> None:
    strategy = _BrokenWrapStrategy(calls=calls)
    ctx = Ctx(config=get_strategy("ecepdi").parse_config({"section": {"prefix": [2, 2]}}),
              strategy=strategy)
    with pytest.raises(RuntimeError,
                       match=rf"broken-wrap.*proceed {calls} times"):
        run_phase("md_number", ctx, lambda c: c)


# ------------------------------------------------------ unknown strategy


def test_get_strategy_unknown_lists_registered() -> None:
    with pytest.raises(KeyError, match=r"unknown strategy.*ecepdi, testhouse"):
        get_strategy("no-such-style")


def test_load_config_unknown_strategy_yaml_key(tmp_path: Path) -> None:
    snippet = tmp_path / "snippet.yaml"
    snippet.write_text("strategy: no-such-style\nsection:\n  prefix: [2, 2]\n",
                       encoding="utf-8")
    with pytest.raises(ConfigError, match=r"unknown strategy.*ecepdi, testhouse"):
        load_config(snippet, None)


def test_cli_draft_unknown_strategy_flag_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match=r"unknown strategy: 'no-such-style'"):
        main(["draft", str(DATA / "plain.md"), "--snippet", str(SNIPPET),
              "--strategy", "no-such-style", "--out", str(tmp_path / "o.docx")])
    assert not (tmp_path / "o.docx").exists()


def test_cli_polish_unknown_strategy_flag_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match=r"unknown strategy: 'no-such-style'"):
        main(["polish", str(tmp_path / "nope.docx"), "--snippet", str(SNIPPET),
              "--strategy", "no-such-style", "--out", str(tmp_path / "o.docx")])


def test_cli_draft_unknown_strategy_yaml_key_fails(tmp_path: Path) -> None:
    snippet = tmp_path / "snippet.yaml"
    snippet.write_text("strategy: no-such-style\nsection:\n  prefix: [2, 2]\n",
                       encoding="utf-8")
    with pytest.raises(SystemExit, match=r"unknown strategy.*ecepdi, testhouse"):
        main(["draft", str(DATA / "plain.md"), "--snippet", str(snippet),
              "--out", str(tmp_path / "o.docx")])


# --------------------------------------- selection: yaml key and CLI flag


def test_load_config_yaml_key_selects_plugin(tmp_path: Path) -> None:
    config, strategy = load_config(TESTHOUSE_SNIPPET, None)
    assert config.strategy == "testhouse"
    assert strategy is TESTHOUSE


def test_load_config_flag_overrides_yaml(tmp_path: Path) -> None:
    config, strategy = load_config(SNIPPET, "testhouse")
    assert config.strategy == "testhouse"
    assert strategy is TESTHOUSE


# ------------------- same pipeline, second house style (end to end)


def _body_children(docx: Path) -> list[ET.Element]:
    with zipfile.ZipFile(docx) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    return list(root.find(f"{W}body"))


def _p_text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(f"{W}t"))


def _pstyle(el: ET.Element) -> str:
    ppr = el.find(f"{W}pPr")
    pstyle = ppr.find(f"{W}pStyle") if ppr is not None else None
    return pstyle.get(f"{W}val") if pstyle is not None else ""


def _styles_by_id(docx: Path) -> dict[str, ET.Element]:
    with zipfile.ZipFile(docx) as zf:
        root = ET.fromstring(zf.read("word/styles.xml"))
    return {s.get(f"{W}styleId"): s for s in root.findall(f"{W}style")}


def _attr(el: ET.Element | None, path: str, attr: str) -> str | None:
    if el is None:
        return None
    child = el.find(path)
    return child.get(attr) if child is not None else None


def _draft_and_polish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                      snippet: Path, strategy_flag: str | None,
                      ) -> tuple[Path, Path]:
    monkeypatch.chdir(DATA)  # figure.png resolves relative to the fixture
    flag = ["--strategy", strategy_flag] if strategy_flag else []
    draft_docx = tmp_path / "draft.docx"
    final_docx = tmp_path / "final.docx"
    emit_md = tmp_path / "anchored.md"
    rc = main(["draft", str(TESTHOUSE_MD), "--snippet", str(snippet), *flag,
               "--out", str(draft_docx), "--emit-md", str(emit_md)])
    assert rc == 0
    rc = main(["polish", str(draft_docx), "--snippet", str(snippet), *flag,
               "--out", str(final_docx)])
    assert rc == 0
    assert final_docx.is_file()
    return emit_md, final_docx


def test_yaml_key_produces_testhouse_style_through_same_pipeline(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    emit_md, final_docx = _draft_and_polish(tmp_path, monkeypatch,
                                            TESTHOUSE_SNIPPET, None)
    md = emit_md.read_text(encoding="utf-8")

    # captions: chapter-scope numbering, stale number stripped, own labels
    assert "Table 2-1: Stale chapter-scope first table" in md
    assert "Table 2-2: Second table typed above" in md   # 2-2-1 did NOT reset
    assert "Figure 2-1: Layout sketch" in md
    assert "4.3-7" not in md

    # section format: dash-joined, headings baked, inline section substituted
    assert "## 2-2 Overview" in md
    assert "### 2-2-1 Wind data" in md
    assert "This snippet lives in section 2-2." in md

    # placement from EnvSpec data: table captions BELOW, figure caption ABOVE
    assert md.index("Turbine") < md.index("Table 2-1:")
    assert md.index("Figure 2-1:") < md.index("![Layout]")
    assert md.index("Item") < md.index("Table 2-2:")


    # final DOCX: same order, named styles, house fonts, zero anchor residue
    children = _body_children(final_docx)
    with zipfile.ZipFile(final_docx) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")
    assert "anchor:" not in document_xml

    tables = [i for i, el in enumerate(children) if el.tag == f"{W}tbl"]
    caption_at = {text: next(i for i, el in enumerate(children) if text in _p_text(el))
                  for text in ("Table 2-1:", "Table 2-2:", "Figure 2-1:")}
    assert tables[0] < caption_at["Table 2-1:"]
    assert tables[1] < caption_at["Table 2-2:"]
    image_at = next(i for i, el in enumerate(children)
                    if el.find(f".//{W}drawing") is not None)
    assert caption_at["Figure 2-1:"] < image_at

    assert _pstyle(children[caption_at["Table 2-1:"]]) == "table_caption"
    assert _pstyle(children[caption_at["Table 2-2:"]]) == "table_caption"
    assert _pstyle(children[caption_at["Figure 2-1:"]]) == "figure_caption"
    assert _pstyle(children[image_at]) == "figure_caption"  # centered image
    overview = next(i for i, el in enumerate(children)
                    if "Overview" in _p_text(el))
    wind = next(i for i, el in enumerate(children) if "Wind data" in _p_text(el))
    assert _pstyle(children[overview]) == "heading2"
    assert _pstyle(children[wind]) == "heading3"

    # style defaults are strategy-owned: 仿宋 captions, bold table captions
    by_id = _styles_by_id(final_docx)
    table_caption = by_id["table_caption"]
    assert _attr(table_caption, f"{W}rPr/{W}rFonts", f"{W}eastAsia") == "仿宋"
    assert table_caption.find(f"{W}rPr/{W}b") is not None
    assert _attr(by_id["normal_text"], f"{W}rPr/{W}rFonts", f"{W}eastAsia") == "仿宋"

    plain = re.sub(r"<[^>]+>", "", document_xml)
    assert "Table 2-1: Stale chapter-scope first table" in plain
    assert "Figure 2-1: Layout sketch" in plain


def test_flag_overrides_yaml_and_selects_plugin(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # snippet.yaml says ecepdi; the --strategy flag wins
    emit_md, final_docx = _draft_and_polish(tmp_path, monkeypatch,
                                            SNIPPET, "testhouse")
    md = emit_md.read_text(encoding="utf-8")
    assert "Table 2-1: Stale chapter-scope first table" in md
    assert "Table 2-2: Second table typed above" in md
    assert final_docx.is_file()


# --------------------------------------------- subprocess CLI (fresh env)


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "snippet_docx.cli", *args],
                          cwd=DATA, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def test_subprocess_unknown_strategy_lists_registered(
        tmp_path: Path) -> None:
    result = _run_cli(["draft", str(TESTHOUSE_MD), "--snippet", str(SNIPPET),
                       "--strategy", "no-such-style",
                       "--out", str(tmp_path / "o.docx")])
    assert result.returncode == 1
    assert "unknown strategy" in result.stderr
    assert "ecepdi, testhouse" in result.stderr


def test_subprocess_draft_with_plugin_strategy(tmp_path: Path) -> None:
    emit_md = tmp_path / "anchored.md"
    result = _run_cli(["draft", str(TESTHOUSE_MD), "--snippet", str(SNIPPET),
                       "--strategy", "testhouse", "--out", str(tmp_path / "d.docx"),
                       "--emit-md", str(emit_md)])
    assert result.returncode == 0, result.stderr
    assert "Table 2-1: Stale chapter-scope first table" in emit_md.read_text(
        encoding="utf-8")
