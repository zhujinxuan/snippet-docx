"""Validation findings: one item per problem, severity-classified.

All findings from a pass are collected and reported together; any
error-severity finding fails the build before outputs are written.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Literal["error", "warn"]
    message: str  # human-readable, include location context (block index / anchor text)


def report_stderr(findings: list[Finding]) -> None:
    """Print every finding to stderr, one ``[SEVERITY] code: message`` line each."""
    for f in findings:
        sys.stderr.write(f"[{f.severity.upper()}] {f.code}: {f.message}\n")


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity == "error" for f in findings)
