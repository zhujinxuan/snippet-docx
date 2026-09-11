"""ecepdi strategy: the built-in house standard (ToolSpec §5 contract).

Env registry (data, not code): table (label 表, caption above), figure
(label 图, caption below), landscape (unnumbered layout env wrapping
table/figure/prose on A4 landscape pages, ticket 07).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from snippet_docx import jinja_render, styles
from snippet_docx.config import Config, ConfigError
from snippet_docx.ops_docx import DocxOp, ecepdi_docx_ops
from snippet_docx.ops_md import MdOp, ecepdi_md_ops
from snippet_docx.ops_md_normalize import ecepdi_normalize_ops
from snippet_docx.pipeline import Ctx
from snippet_docx.strategy import EnvSpec, NumberingState, Phase


def _section_var(state: NumberingState) -> str:
    """global var ``section`` -> current section number (e.g. 2.2.3)."""
    return ".".join(str(e) for e in state.section_path)


def _ecepdi_envs() -> dict[str, EnvSpec]:
    return {
        "table": EnvSpec(name="table", label="表", caption_placement="above"),
        "figure": EnvSpec(name="figure", label="图", caption_placement="below"),
        # unnumbered layout env: A4 landscape pages via InsertSectionBreak;
        # may wrap table/figure envs and arbitrary prose (ToolSpec §3)
        "landscape": EnvSpec(name="landscape", label="横向", numbered=False,
                             caption_placement="above",
                             may_contain=("table", "figure")),
    }


Severity = Literal["error", "warn"]

_SEVERITIES: dict[str, Severity] = {
    # ToolSpec §7 table
    "unpaired-anchor": "error",
    "non-standalone-anchor": "error",
    "unknown-env": "error",
    "unknown-global-var": "error",
    "reserved-ref": "error",
    "captionless-env": "warn",
    "cross-subsection": "warn",
    "heading-too-deep": "warn",
    # structural violations checked by validate_anchors (contract §anchors)
    "env-var-outside-block": "error",
    "nesting-violation": "error",
}


@dataclass(frozen=True)
class EcepdiStrategy:
    name: str = "ecepdi"
    envs: dict[str, EnvSpec] = field(default_factory=_ecepdi_envs)
    global_vars: dict[str, Callable[[NumberingState], str]] = field(
        default_factory=lambda: {"section": _section_var})

    # numbering (pure functions; the walker owns counters)

    def format_section(self, path: tuple[int | str, ...]) -> str:
        return ".".join(str(e) for e in path)

    def format_caption(self, env: EnvSpec, path: tuple[int | str, ...],
                       index: int, text: str) -> str:
        # path arrives pre-clamped by the md op (config.caption_max_depth);
        # strategies format, the tool owns clamping (contract §5)
        clamped = self.format_section(path)
        return f"{env.label} {clamped}-{index} {text}"

    # op pipelines (L2)

    def md_ops(self) -> list[MdOp]:
        return ecepdi_md_ops()

    def md_normalize_ops(self) -> list[MdOp]:
        return ecepdi_normalize_ops()

    def docx_ops(self) -> list[DocxOp]:
        return ecepdi_docx_ops()

    # phase continuations (L3): transparent

    def wrap_phase(self, phase: Phase, ctx: Ctx,
                   proceed: Callable[[Ctx], Ctx]) -> Ctx:
        return proceed(ctx)

    # defaults & config

    def default_styles(self) -> dict:
        return styles.load_packaged_defaults()

    def parse_config(self, raw: dict) -> Config:
        section = raw.get("section") or {}
        prefix = tuple(section.get("prefix") or ())

        numbering = raw.get("numbering") or {}
        sections = numbering.get("sections") or {}
        section_start = {int(k): int(v)
                         for k, v in (sections.get("start") or {}).items()}
        env_start: dict[str, int] = {}
        for env in self.envs:
            env_cfg = numbering.get(env) or {}
            if isinstance(env_cfg, dict) and "start" in env_cfg:
                start = env_cfg["start"]
                if isinstance(start, bool) or not isinstance(start, int):
                    raise ConfigError(f"numbering.{env}.start must be an int")
                env_start[env] = start

        caption = numbering.get("caption") or {}
        max_depth = caption.get("max_depth", 3)
        if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 1:
            raise ConfigError(f"numbering.caption.max_depth must be a positive int, "
                              f"got {max_depth!r}")

        landscape = raw.get("landscape") or {}
        anchors = raw.get("anchors") or {}
        styles_raw = raw.get("styles") or {}
        if not isinstance(styles_raw, dict):
            raise ConfigError("styles must be a mapping")

        return Config(
            strategy=self.name,
            prefix=prefix,
            section_start=section_start,
            env_start=env_start,
            caption_max_depth=max_depth,
            styles=styles_raw,
            landscape_paper=landscape.get("paper", "a4"),
            anchor_prefix=anchors.get("prefix", "anchor:"),
            raw=raw,
        )

    def severities(self) -> dict[str, Severity]:
        return dict(_SEVERITIES)

    # jinja

    def jinja_globals(self) -> dict:
        return jinja_render.build_anchor_globals(self)
