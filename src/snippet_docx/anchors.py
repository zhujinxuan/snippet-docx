"""Anchor grammar (ToolSpec §3): parse from the pandoc JSON AST, validate
against the strategy's env/global-var registries.

Anchors ride pandoc as inline-code spans: `` `anchor:begin:table` `` as a
standalone paragraph (md->docx: VerbatimChar run); `` `anchor:section` ``
inline in prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from snippet_docx.findings import Finding
from snippet_docx.pandoc_ast import (
    blocks,
    code_paragraph_payload,
    inline_code_spans,
    paragraph_starts_with_code,
    plain_text,
)

if TYPE_CHECKING:
    from snippet_docx.strategy import Strategy

Kind = Literal["begin", "end", "env_var", "global_var", "ref"]


@dataclass(frozen=True)
class Anchor:
    kind: Kind
    env: str | None          # begin/end/env_var
    key: str | None          # env_var
    value: str | None        # env_var
    name: str | None         # global_var / ref
    block_index: int
    inline: bool             # True: code span inside a prose paragraph (global_var only)

    def text(self, prefix: str = "anchor:") -> str:
        """Reconstruct the anchor's code-span text (for finding messages)."""
        payload = {
            "begin": f"begin:{self.env}",
            "end": f"end:{self.env}",
            "env_var": f"env:{self.env}:{self.key}={self.value}",
            "global_var": f"{self.name}",
            "ref": f"ref:{self.name}",
        }[self.kind]
        return f"`{prefix}{payload}`"


def _anchor_from_payload(payload: str, block_index: int, inline: bool) -> Anchor:
    if payload.startswith("begin:"):
        return Anchor("begin", env=payload[len("begin:"):], key=None, value=None,
                      name=None, block_index=block_index, inline=inline)
    if payload.startswith("end:"):
        return Anchor("end", env=payload[len("end:"):], key=None, value=None,
                      name=None, block_index=block_index, inline=inline)
    if payload.startswith("env:"):
        env, sep, kv = payload[len("env:"):].partition(":")
        key, _eq, value = kv.partition("=")
        if sep and key and value:
            return Anchor("env_var", env=env, key=key, value=value,
                          name=None, block_index=block_index, inline=inline)
    if payload.startswith("ref:"):
        return Anchor("ref", env=None, key=None, value=None,
                      name=payload[len("ref:"):], block_index=block_index, inline=inline)
    return Anchor("global_var", env=None, key=None, value=None,
                  name=payload, block_index=block_index, inline=inline)


def parse_anchors(ast: dict, prefix: str = "anchor:") -> list[Anchor]:
    """Every code span carrying the anchor prefix, in block order.

    Standalone anchor paragraphs (whole Para = one Code span) parse with
    inline=False; spans sharing a paragraph with prose parse with inline=True.
    """
    result: list[Anchor] = []
    for index, block in enumerate(blocks(ast)):
        if block.get("t") != "Para":
            continue
        payload = code_paragraph_payload(block, prefix)
        if payload is not None:
            result.append(_anchor_from_payload(payload, index, inline=False))
            continue
        for _elem, inline_payload in inline_code_spans(block, prefix):
            result.append(_anchor_from_payload(inline_payload, index, inline=True))
    return result


def validate_anchors(anchors: list[Anchor], ast: dict, strategy: Strategy) -> list[Finding]:
    """One pass, every finding collected.

    Errors (severity per strategy.severities()): unpaired begin/end (stack
    discipline), begin/end not standalone, unknown env, unknown global var,
    anchor:ref:* used, env_var outside its block, nesting violation
    (outer.may_contain must include inner env). Warning-class: captionless env.
    """
    severities = strategy.severities()
    envs = strategy.envs
    global_vars = strategy.global_vars
    block_list = blocks(ast)

    def sev(code: str, default: Literal["error", "warn"]) -> Literal["error", "warn"]:
        return severities.get(code, default)

    findings: list[Finding] = []

    def add(code: str, message: str, default: Literal["error", "warn"] = "error") -> None:
        findings.append(Finding(code=code, severity=sev(code, default), message=message))

    stack: list[Anchor] = []
    for anchor in anchors:
        text = anchor.text()
        where = f"block {anchor.block_index}"

        if anchor.kind in ("begin", "end", "env_var") and anchor.inline:
            glued = (paragraph_starts_with_code(block_list[anchor.block_index], "anchor:")
                     if anchor.block_index < len(block_list) else None)
            position = ("starts a prose paragraph" if glued is not None
                        else "appears inside a prose paragraph")
            add("non-standalone-anchor",
                f"{text} at {where} {position}; begin/end/env anchors must be "
                "standalone paragraphs")

        if anchor.kind in ("begin", "end", "env_var") and anchor.env not in envs:
            add("unknown-env", f"{text} at {where}: env {anchor.env!r} not in strategy registry "
                               f"{{{', '.join(sorted(envs))}}}")
            continue

        if anchor.kind == "ref":
            add("reserved-ref", f"{text} at {where}: anchor:ref:* is reserved for later "
                                "(cross-references are out of scope in v1)")
            continue

        if anchor.kind == "global_var":
            if anchor.name not in global_vars:
                add("unknown-global-var",
                    f"{text} at {where}: global var {anchor.name!r} not in strategy registry "
                    f"{{{', '.join(sorted(global_vars))}}}")
            continue

        if anchor.kind == "env_var":
            if not stack or stack[-1].env != anchor.env:
                open_env = stack[-1].env if stack else None
                add("env-var-outside-block",
                    f"{text} at {where}: must sit inside its own env block "
                    f"(innermost open env: {open_env!r})")
            continue

        if anchor.kind == "begin":
            if stack and anchor.env not in envs[stack[-1].env].may_contain:
                add("nesting-violation",
                    f"{text} at {where}: env {anchor.env!r} may not nest inside "
                    f"{stack[-1].env!r} (block {stack[-1].block_index})")
            stack.append(anchor)
            continue

        # anchor.kind == "end"
        if not stack:
            add("unpaired-anchor", f"{text} at {where}: end without a matching begin")
            continue
        if stack[-1].env != anchor.env:
            add("unpaired-anchor",
                f"{text} at {where}: does not match open begin {stack[-1].text()} "
                f"(block {stack[-1].block_index})")
            continue
        begin = stack.pop()
        spec = envs[anchor.env]
        if not spec.numbered:
            continue  # unnumbered layout envs (landscape) take no caption
        has_caption = any(
            blk.get("t") == "Para"
            and plain_text(blk.get("c") or []).startswith(f"{spec.label} ")
            for blk in block_list[begin.block_index + 1:anchor.block_index]
        )
        if not has_caption:
            severity: Literal["error", "warn"] = (
                "error" if spec.caption_required else sev("captionless-env", "warn"))
            findings.append(Finding(
                code="captionless-env",
                severity=severity,
                message=f"{anchor.env} env (blocks {begin.block_index}..{anchor.block_index}) "
                        f"has no caption paragraph starting with {spec.label!r} "
                        "(styled but not numbered)",
            ))

    for begin in stack:
        add("unpaired-anchor",
            f"{begin.text()} at block {begin.block_index}: begin without a matching end")

    return findings
