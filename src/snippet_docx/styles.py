"""Styles engine: packaged defaults, deep merge, named DOCX style construction.

Ticket 02 shipped the two loaders; ticket 05 adds the engine: resolving the
merged style config (packaged ecepdi defaults deep-merged with snippet
``styles:`` overrides) and turning each entry into a named paragraph style
with the settled OOXML conventions:

- ``w:rFonts`` ascii=hAnsi=english_font, eastAsia=chinese_font
- ``w:sz`` = pt * 2 (half-points)
- exact leading: ``w:spacing w:line=pt*20 w:lineRule="exact"``; auto rule:
  ``w:line=multiplier*240``
- first-line indent via ``w:ind w:firstLineChars`` (hundredths of a char,
  scales with font size: 24pt indent at 12pt font -> 200 = 2 chars)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from docx.oxml.ns import qn
from lxml import etree

if TYPE_CHECKING:
    from docx.document import Document

    from snippet_docx.config import Config
    from snippet_docx.strategy import Strategy

_TWIPS_PER_PT = 20
_AUTO_LINE_UNITS = 240          # w:line units per 1.0 multiple at lineRule=auto
_HUNDREDTHS_PER_CHAR = 100      # firstLineChars unit: 1/100 of a character

_ALIGNMENT_VALS = {"justify": "both", "center": "center",
                   "left": "left", "right": "right"}

_HEADING_RE = re.compile(r"heading([1-9])$")


def load_packaged_defaults() -> dict:
    """Read <tool_root>/styles/ecepdi-default.yaml (raw packaged defaults)."""
    styles_dir = Path(__file__).resolve().parents[2] / "styles"
    path = styles_dir / "ecepdi-default.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def deep_merge(base: dict, override: dict) -> dict:
    """Recursive dict merge; override wins at leaves, nested dicts merge."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def resolve_styles(strategy: Strategy, config: Config) -> dict[str, dict]:
    """Merged named style entries: deep_merge(defaults, snippet overrides).

    The packaged file wraps entries under a top-level ``style:`` key, and
    snippet overrides mirror that shape (``styles: style: heading2: ...``).
    Bare entry form (``styles: heading2: ...``) is accepted and wrapped so a
    missing wrapper cannot silently drop overrides.
    """
    defaults = strategy.default_styles()
    overrides = dict(config.styles or {})
    if overrides and "style" not in overrides and "style" in defaults:
        overrides = {"style": overrides}
    merged = deep_merge(defaults, overrides)
    entries = merged.get("style")
    return entries if isinstance(entries, dict) else {}


def pt_to_twips(pt: float) -> int:
    return round(pt * _TWIPS_PER_PT)


def alignment_val(alignment: str) -> str:
    try:
        return _ALIGNMENT_VALS[alignment]
    except KeyError:
        raise ValueError(f"unknown alignment {alignment!r}; expected one of "
                         f"{sorted(_ALIGNMENT_VALS)}") from None


def line_spacing_attrs(rule: str, value: float) -> tuple[int, str]:
    """(w:line, w:lineRule) from the schema's rule + value pair."""
    if rule == "exact":
        return pt_to_twips(float(value)), "exact"
    if rule == "auto":
        return round(float(value) * _AUTO_LINE_UNITS), "auto"
    raise ValueError(f"unknown line_spacing_rule {rule!r}; expected auto|exact")


def first_line_chars(spec: dict) -> int:
    """First-line indent in hundredths of a character (0 = no indent).

    24pt indent at 12pt font -> 200 (2 chars); firstLineChars scales with
    the font size, unlike a fixed w:firstLine twips value.
    """
    indent = float(spec.get("first_line_indent_pt") or 0)
    size = float(spec.get("font_size_pt") or 0)
    if indent <= 0 or size <= 0:
        return 0
    return round(indent / size * _HUNDREDTHS_PER_CHAR)


def _sub(parent: etree._Element, tag: str, **attrs: str) -> etree._Element:
    child = etree.SubElement(parent, qn(tag))
    for name, value in attrs.items():
        child.set(qn(f"w:{name}"), str(value))
    return child


def _build_ppr(name: str, spec: dict) -> etree._Element:
    """Paragraph properties; child order per the CT_PPrBase sequence."""
    ppr = etree.Element(qn("w:pPr"))
    spacing_attrs: dict[str, str] = {}
    before = spec.get("space_before_pt")
    after = spec.get("space_after_pt")
    if before is not None:
        spacing_attrs["before"] = str(pt_to_twips(float(before)))
    if after is not None:
        spacing_attrs["after"] = str(pt_to_twips(float(after)))
    rule = spec.get("line_spacing_rule")
    if rule is not None and spec.get("line_spacing") is not None:
        line, line_rule = line_spacing_attrs(str(rule), float(spec["line_spacing"]))
        spacing_attrs["line"] = str(line)
        spacing_attrs["lineRule"] = line_rule
    if spacing_attrs:
        _sub(ppr, "w:spacing", **spacing_attrs)
    chars = first_line_chars(spec)
    if chars > 0:
        _sub(ppr, "w:ind", firstLineChars=chars)
    _sub(ppr, "w:jc", val=alignment_val(str(spec.get("alignment", "left"))))
    heading = _HEADING_RE.match(name)
    if heading:
        _sub(ppr, "w:outlineLvl", val=int(heading.group(1)) - 1)
    return ppr


def _build_rpr(spec: dict) -> etree._Element:
    """Run properties; child order per the CT_RPr sequence."""
    rpr = etree.Element(qn("w:rPr"))
    rfonts = _sub(rpr, "w:rFonts")
    english = spec.get("english_font")
    chinese = spec.get("chinese_font")
    if english:
        rfonts.set(qn("w:ascii"), str(english))
        rfonts.set(qn("w:hAnsi"), str(english))
    if chinese:
        rfonts.set(qn("w:eastAsia"), str(chinese))
    for tag, key in (("b", "bold"), ("bCs", "bold"), ("i", "italic"),
                     ("iCs", "italic")):
        if spec.get(key):
            _sub(rpr, f"w:{tag}")
        else:
            _sub(rpr, f"w:{tag}", val="0")
    size = spec.get("font_size_pt")
    if size is not None:
        half_points = str(round(float(size) * 2))
        _sub(rpr, "w:sz", val=half_points)
        _sub(rpr, "w:szCs", val=half_points)
    return rpr


def define_paragraph_style(doc: Document, name: str, spec: dict) -> None:
    """Create (or replace) the named paragraph style ``name`` from a spec.

    The style carries the full measured value set (fonts, size, emphasis,
    alignment, spacing, leading, indent) so paragraphs need only reference
    it via ``w:pStyle`` — no stray direct run formatting.
    """
    styles_el = doc.styles.element
    for existing in styles_el.findall(qn("w:style")):
        if existing.get(qn("w:styleId")) == name:
            styles_el.remove(existing)
    style = _sub(styles_el, "w:style")
    style.set(qn("w:type"), "paragraph")
    style.set(qn("w:styleId"), name)
    _sub(style, "w:name", val=name)
    _sub(style, "w:basedOn", val="Normal")
    _sub(style, "w:qFormat")
    style.append(_build_ppr(name, spec))
    style.append(_build_rpr(spec))
