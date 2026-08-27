"""Strategy contract (ToolSpec §5): the pluggability seam.

Tool-owned: anchor syntax, pipeline skeleton, op executors, the numbering
walker. Strategy-owned: env/global-var registries, number & caption
formatting, op lists, style defaults, validation severities, jinja globals.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from snippet_docx.config import Config
    from snippet_docx.ops_docx import DocxOp
    from snippet_docx.ops_md import MdOp
    from snippet_docx.pipeline import Ctx

Phase = Literal["md_number", "md_normalize", "docx_polish"]


@dataclass(frozen=True)
class EnvSpec:
    name: str                                   # "table"
    label: str                                  # "表"
    caption_placement: Literal["above", "below"]
    numbered: bool = True
    caption_required: bool = False              # False -> missing caption = warning
    counter_scope: Literal["section", "chapter", "continuous"] = "section"
    caption_max_depth: int = 3
    may_contain: tuple[str, ...] = ()           # nesting: landscape contains table/figure
    caption_style: str = "Caption"
    content_style: str = "TableContent"


class NumberingState(Protocol):
    """State supplied by the walker (ticket 03) to global-var resolvers."""

    section_path: tuple[int | str, ...]


@runtime_checkable
class Strategy(Protocol):
    name: str

    # registries (data)
    envs: dict[str, EnvSpec]
    global_vars: dict[str, Callable[[NumberingState], str]]

    # numbering (pure functions; the walker owns counters)
    def format_section(self, path: tuple[int | str, ...]) -> str: ...

    def format_caption(self, env: EnvSpec, path: tuple[int | str, ...],
                       index: int, text: str) -> str: ...

    # op pipelines (L2 escape hatch: swap/extend ops without forking pipeline)
    def md_ops(self) -> list[MdOp]: ...

    def md_normalize_ops(self) -> list[MdOp]: ...

    def docx_ops(self) -> list[DocxOp]: ...

    # phase continuations (L3: scoped CPS - wrap whole phases, never per-node)
    def wrap_phase(self, phase: Phase, ctx: Ctx,
                   proceed: Callable[[Ctx], Ctx]) -> Ctx: ...

    # defaults & config
    def default_styles(self) -> dict: ...

    def parse_config(self, raw: dict) -> Config: ...

    def severities(self) -> dict[str, Literal["error", "warn"]]: ...

    # jinja (auto-built from envs: anchor.begin/end/inline; strategy may add more)
    def jinja_globals(self) -> dict: ...


_ENTRY_POINT_GROUP = "snippet_docx.strategies"
_REGISTRY: dict[str, Strategy] | None = None


def registered_strategies() -> dict[str, Strategy]:
    """Built-in ecepdi + entry-point group ``snippet_docx.strategies``."""
    global _REGISTRY
    if _REGISTRY is None:
        from snippet_docx.strategies.ecepdi import EcepdiStrategy

        registry: dict[str, Strategy] = {"ecepdi": EcepdiStrategy()}
        for ep in entry_points(group=_ENTRY_POINT_GROUP):
            loaded: Any = ep.load()
            strategy = loaded() if isinstance(loaded, type) else loaded
            registry[ep.name] = strategy
        _REGISTRY = registry
    return _REGISTRY


def get_strategy(name: str) -> Strategy:
    registry = registered_strategies()
    if name not in registry:
        available = ", ".join(sorted(registry))
        raise KeyError(
            f"unknown strategy: {name!r} (available: {available})",
        )
    return registry[name]
