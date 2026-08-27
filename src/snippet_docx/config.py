"""snippet.yaml loading and validation (ToolSpec §4).

``load_config`` validates the tool-owned top-level shape (prefix elements,
section_start keys, landscape paper, strategy name), then delegates the
strategy slice to ``strategy.parse_config``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from snippet_docx.strategy import get_strategy

if TYPE_CHECKING:
    from snippet_docx.strategy import Strategy


class ConfigError(Exception):
    """Invalid snippet.yaml."""


@dataclass(frozen=True)
class Config:
    strategy: str
    prefix: tuple[int | str, ...]
    section_start: dict[int, int] = field(default_factory=dict)  # keys = doc level
    env_start: dict[str, int] = field(default_factory=dict)      # {"table": n, ...}
    caption_max_depth: int = 3
    styles: dict = field(default_factory=dict)   # raw overrides; merged in styles.py
    landscape_paper: str = "a4"                  # "a3" -> clear not-implemented error
    anchor_prefix: str = "anchor:"
    raw: dict = field(default_factory=dict)


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"snippet config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"snippet config must be a mapping: {path}")
    return data


def _validate_tool_slice(raw: dict) -> tuple[int, dict[int, int]]:
    """Validate tool-owned fields; return (len(prefix), section_start)."""
    section = raw.get("section")
    if not isinstance(section, dict) or "prefix" not in section:
        raise ConfigError("section.prefix is required (snippet context, e.g. [2, 2])")
    prefix = section["prefix"]
    if not isinstance(prefix, list) or not prefix:
        raise ConfigError("section.prefix must be a nonempty list of int|str")
    for element in prefix:
        if isinstance(element, bool) or not isinstance(element, (int, str)):
            raise ConfigError(f"section.prefix elements must be int|str, got {element!r}")

    numbering = raw.get("numbering") or {}
    sections = numbering.get("sections") or {}
    start = sections.get("start") or {}
    if not isinstance(start, dict):
        raise ConfigError("numbering.sections.start must be a mapping {level: start}")
    section_start: dict[int, int] = {}
    for key, value in start.items():
        if isinstance(key, bool) or not isinstance(key, int):
            raise ConfigError(f"numbering.sections.start keys must be ints, got {key!r}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"numbering.sections.start values must be ints, got {value!r}")
        if key <= len(prefix):
            raise ConfigError(
                f"numbering.sections.start keys must be deeper than the prefix "
                f"(> {len(prefix)}), got {key}")
        section_start[key] = value

    landscape = raw.get("landscape") or {}
    paper = landscape.get("paper", "a4")
    if paper != "a4":
        raise ConfigError(
            f"landscape paper {paper!r} is reserved and not implemented; only a4")
    return len(prefix), section_start


def load_config(path: Path, strategy_override: str | None) -> tuple[Config, Strategy]:
    """Read snippet.yaml, resolve the strategy, validate, build Config."""
    raw = _read_yaml(path)
    name = strategy_override or raw.get("strategy", "ecepdi")
    try:
        strategy = get_strategy(name)
    except KeyError as exc:
        raise ConfigError(str(exc.args[0])) from exc
    _validate_tool_slice(raw)
    config = strategy.parse_config(raw)
    return config, strategy
