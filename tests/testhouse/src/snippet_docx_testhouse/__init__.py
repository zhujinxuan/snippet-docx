"""testhouse: the ticket-09 plugin-seam proof strategy.

A second, deliberately minimal house style registered ONLY through the
``snippet_docx.strategies`` entry-point group (declared in this package's
pyproject; nothing under ``snippet_docx`` knows this module exists). Every
difference from ecepdi is expressed through the strategy surface alone
(ToolSpec §5 control levels):

- L0 EnvSpec data: table label ``Table`` with captions BELOW the table and
  figure label ``Figure`` with captions ABOVE the image — the exact mirror
  of ecepdi's placements; chapter-scope counters
  (``counter_scope="chapter"``: the caption prefix is the TOP-level
  section element only and the counter does not reset per subsection).
- L1 format functions: sections render dash-joined (``2.2.1`` -> ``2-2-1``);
  captions render ``Table 2-1: Foo`` (chapter, chapter-scoped index, colon).
- L0 style defaults: 仿宋 body/caption fonts deep-merged over the packaged
  baseline (the customer-X sketch from ToolSpec §5).

The pipeline skeleton, numbering walker, op executors, validator, and
anchor parser are the tool-owned ones, reused unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from snippet_docx import jinja_render, styles
from snippet_docx.config import Config
from snippet_docx.ops_docx import DocxOp, ecepdi_docx_ops
from snippet_docx.ops_md import MdOp, ecepdi_md_ops
from snippet_docx.pipeline import Ctx
from snippet_docx.strategies.ecepdi import EcepdiStrategy, Severity
from snippet_docx.strategy import EnvSpec, NumberingState, Phase

__all__ = ["TESTHOUSE", "TesthouseStrategy"]


def _section_var(state: NumberingState) -> str:
    """global var ``section`` -> current section number (e.g. 2-2-1)."""
    return "-".join(str(e) for e in state.section_path)


def _testhouse_envs() -> dict[str, EnvSpec]:
    return {
        "table": EnvSpec(name="table", label="Table", caption_placement="below",
                         counter_scope="chapter"),
        "figure": EnvSpec(name="figure", label="Figure", caption_placement="above",
                          counter_scope="chapter"),
    }


#: L0 style defaults: 仿宋 for body text and captions (plus bold table
#: captions), deep-merged over the packaged baseline by ``default_styles``.
_TESTHOUSE_STYLES: dict = {
    "style": {
        "normal_text": {"chinese_font": "仿宋"},
        "table_caption": {"chinese_font": "仿宋", "bold": True},
        "figure_caption": {"chinese_font": "仿宋"},
    },
}


@dataclass(frozen=True)
class TesthouseStrategy:
    name: str = "testhouse"
    envs: dict[str, EnvSpec] = field(default_factory=_testhouse_envs)
    global_vars: dict[str, Callable[[NumberingState], str]] = field(
        default_factory=lambda: {"section": _section_var})

    # numbering (L1, pure functions; the walker owns the counters)

    def format_section(self, path: tuple[int | str, ...]) -> str:
        return "-".join(str(e) for e in path)

    def format_caption(self, env: EnvSpec, path: tuple[int | str, ...],
                       index: int, text: str) -> str:
        chapter = f"{path[0]}-" if path else ""
        return f"{env.label} {chapter}{index}: {text}"

    # op pipelines (L2): the tool-owned executors, driven by EnvSpec data

    def md_ops(self) -> list[MdOp]:
        return ecepdi_md_ops()

    def md_normalize_ops(self) -> list[MdOp]:
        return []

    def docx_ops(self) -> list[DocxOp]:
        return ecepdi_docx_ops()

    # phase continuations (L3): transparent

    def wrap_phase(self, phase: Phase, ctx: Ctx,
                   proceed: Callable[[Ctx], Ctx]) -> Ctx:
        return proceed(ctx)

    # defaults & config

    def default_styles(self) -> dict:
        return styles.deep_merge(styles.load_packaged_defaults(), _TESTHOUSE_STYLES)

    def parse_config(self, raw: dict) -> Config:
        # same snippet.yaml slice as ecepdi; only the selected name differs
        return replace(EcepdiStrategy().parse_config(raw), strategy=self.name)

    def severities(self) -> dict[str, Severity]:
        return EcepdiStrategy().severities()

    # jinja

    def jinja_globals(self) -> dict:
        return jinja_render.build_anchor_globals(self)


#: Entry-point target (an instance; the loader also accepts a class).
TESTHOUSE = TesthouseStrategy()
