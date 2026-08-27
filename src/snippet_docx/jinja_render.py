"""Jinja integration: anchor globals built from the strategy registries.

``build_anchor_globals`` (ticket 02) hands template authors
``{{ anchor.begin('table') }}`` macros that emit exactly the anchor grammar.
``render_template`` (ticket 08) runs a template file against YAML data with
those macros in scope, producing the markdown fed to the draft pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from jinja2 import Environment, StrictUndefined, TemplateError

if TYPE_CHECKING:
    from snippet_docx.strategy import Strategy


class TemplateRenderError(Exception):
    """Template rendering failed: syntax, bad data, or unknown env/global var."""


class _AnchorNamespace:
    """``anchor`` object exposed to jinja templates."""

    def __init__(self, env_names: tuple[str, ...], global_names: frozenset[str]) -> None:
        self._envs = env_names
        self._globals = global_names

    def _require_env(self, env: str) -> None:
        if env not in self._envs:
            raise ValueError(
                f"unknown env {env!r} (registered: {', '.join(self._envs)})")

    def begin(self, env: str) -> str:
        """Full-line anchor opening an env block."""
        self._require_env(env)
        return f"`anchor:begin:{env}`"

    def end(self, env: str) -> str:
        """Full-line anchor closing an env block."""
        self._require_env(env)
        return f"`anchor:end:{env}`"

    def inline(self, name: str) -> str:
        """Inline anchor span for a registered global var (e.g. section)."""
        if name not in self._globals:
            raise ValueError(
                f"unknown global var {name!r} (registered: {', '.join(sorted(self._globals))})")
        return f"`anchor:{name}`"


def build_anchor_globals(strategy: Strategy) -> dict:
    """{"anchor": <obj>} with begin/end/inline methods driven by the strategy."""
    return {
        "anchor": _AnchorNamespace(
            tuple(strategy.envs), frozenset(strategy.global_vars),
        ),
    }


def render_template(template: Path, data: Path, strategy: Strategy) -> str:
    """Render ``template`` with YAML ``data`` + the strategy's jinja globals.

    The result is the markdown text handed to ``pipeline.draft``. Any failure
    (unreadable file, bad YAML, template syntax error, undefined data key,
    unknown env/global var in an anchor macro) raises TemplateRenderError with
    a clear message so the CLI can fail the build.
    """
    try:
        template_text = template.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateRenderError(f"cannot read template {template}: {exc}") from exc

    try:
        with data.open(encoding="utf-8") as fh:
            payload = yaml.safe_load(fh)
    except OSError as exc:
        raise TemplateRenderError(f"cannot read data file {data}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise TemplateRenderError(f"invalid YAML in data file {data}: {exc}") from exc
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise TemplateRenderError(
            f"data file {data} must be a YAML mapping at top level, "
            f"got {type(payload).__name__}")

    # trim_blocks/lstrip_blocks: block tags on their own line vanish cleanly
    # instead of leaving blank lines that would split markdown tables.
    # StrictUndefined: a typo'd data key fails the render instead of emitting
    # silent empties into the document.
    env = Environment(
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.globals.update(strategy.jinja_globals())
    try:
        return env.from_string(template_text).render(payload)
    except TemplateError as exc:
        raise TemplateRenderError(
            f"template render failed ({template}): {exc}") from exc
    except ValueError as exc:
        # unknown env / global var from the anchor namespace
        raise TemplateRenderError(
            f"template render failed ({template}): {exc}") from exc
