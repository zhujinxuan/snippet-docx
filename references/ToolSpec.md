# ToolSpec: snippet-docx

**Status**: settled design (Decisions register). Canonical home is the `snippet-docx` agent skill (`~/.agents/skills/snippet-docx/`); the jz-toolshed origin remains frozen. Native-caption decisions and implementation status are tracked in [the feature spec](../.scratch/native-captions/spec.md).
**CLI name**: `snippet-docx`
**Purpose**: convert a markdown *snippet* (one subsection or part of one
subsection, optionally jinja2-templated with data) into a DOCX meeting a
house standard — ecepdi by default; other customer standards via pluggable
strategies.

A *snippet* never crosses a subsection boundary. A future combine tool will
assemble snippets into full reports; this tool guarantees each snippet's
numbering is correct given its declared offsets, so composition is safe.

**Contents:** [Pipeline](#1-pipeline) · [Commands](#2-commands) ·
[Anchors and captions](#3-anchor-grammar) · [Configuration](#4-snippetyaml-schema) ·
[Strategies](#5-strategy-contract-pluggability) · [Ops](#6-ops) ·
[Validation](#7-validation-policy-q14) · [Verification](#8-verification) ·
[Scope](#9-out-of-scope-v1) · [Decisions](#10-decisions-register-traceability) ·
[Provenance](#11-provenance)

---

## 1. Pipeline

```text
draft:
  optional Jinja render → Pandoc JSON AST → anchor/caption validation
  → bake heading numbers and substitute globals → normalize tables/images
  → Pandoc → draft.docx
  → emit anchored.md (numbered headings + explicit heading context;
                      native/ALT captions retained, not expanded/numbered)

polish:
  draft.docx × snippet.yaml × required --md section context
  → discover/select captions per env → number and position captions in DOCX
  → house styles, table/image repairs, landscape sections
  → strip anchors → final.docx
```

Heading numbers are baked in **draft**. Caption numbers and placement are
realized in **polish**, using shared source discovery/normalization and
per-env plans rather than independent table/figure parsers or counters.
Prefer emitted Markdown for `--md`; raw source Markdown is also supported.
Emitted heading context is explicit: the internal `snippet-docx-section`
heading attribute carries the section path. Preserve it when passing emitted
Markdown to polish; raw Markdown uses the normal heading walker. Polish must
not guess from numeric titles or apply the draft heading transform twice.

**Rule for where a fix lives** (Q17): if pandoc preserves the structure,
repair in polish; if pandoc destroys it (eats simple tables → naked text),
prevent in the md phase.

## 2. Commands

```
snippet-docx draft  <input.md | --template t.md.j2 --data d.yaml>
                    --snippet snippet.yaml
                    [--strategy ecepdi]
                    --out draft.docx --emit-md anchored.md

snippet-docx polish <draft.docx>
                    --snippet snippet.yaml
                    [--strategy ecepdi]
                    --md anchored.md          # required; emitted recommended, raw supported
                    --out final.docx
```

Both commands accept `--strategy`; snippet.yaml `strategy:` key is the default
selector. ecepdi is the built-in default strategy.

## 3. Anchor grammar

Anchors are transported through pandoc as **one inline-code span forming a
standalone paragraph** (pandoc maps it to a `VerbatimChar` run — the mechanism
proven by typst_ir's `irstart:`/`irend:` markers).

```bnf
anchor-line  := "`" "anchor:" payload "`"        # whole paragraph = one code span
payload      := block | env-var | global-var
block        := ("begin" | "end") ":" env-name
env-var      := "env:" env-name ":" key "=" value   # consumed by strategy, e.g. paper=a3
global-var   := ident                                # substituted in md numbering phase
env-name     := strategy registry   # ecepdi v1: "table" | "figure" | "landscape"
global-var   := strategy registry   # ecepdi v1: "section" → current section number
```

Rules:
- begin/end pair as a stack; `landscape` may wrap `table`/`figure`/`figure`s;
  `table` and `figure` may not nest inside each other.
- `anchor:env:*` lines appear inside their block; consumed, never rendered.
- `anchor:section` may appear inline in prose (inline code span inside a
  paragraph); substituted with the current section number (`2.2.3`).
- Reserved for later: `anchor:ref:*` (cross-references) — using it now is an
  undefined-var error.

**Captions are not anchors.** Inside an existing table/figure env, author:

- A Pandoc Markdown table caption: `Table: 标题` or `: 标题`, in a separate
  paragraph adjacent to its table. The pipe table's header row names columns;
  it is not the caption. HTML-recovered Table caption slots are retained too.
- A standalone image with title in ALT: `![标题](image.png)`. ALT is general
  Markdown fallback/accessibility text; using it as a figure caption is this
  pipeline's Pandoc `implicit_figures` behavior, not a universal Markdown rule.
- For legacy compatibility, a plain paragraph starting `表 ` / `图 `
  (or the registered strategy label), with or without a stale number.

Titles need no manual label or number. Normalize optional labels and stale
numbers from both native/ALT and legacy sources before formatting. Select
one logical caption per env: an explicit legacy paragraph wins over
native/ALT even when wording differs; conflicting normalized titles warn.
An empty native/ALT title can fall back to the explicit paragraph; otherwise
the env is captionless and warns. Deduplicate only within that env, never
globally by title. Each logical numbered caption advances its counter once;
identical titles in different envs remain distinct captions.

Draft retains native slots and ALT instead of synthesizing numbered caption
paragraphs. Polish renders the selected caption at the strategy's placement
(ecepdi: table **above**, figure **below**) and removes redundant caption
representations without destroying image drawings or XML. Linked/formatted
images, including ALT starting `图`, must retain their image content. No
implicit anchor insertion or new caption-mode configuration is introduced.

## 4. snippet.yaml schema

```yaml
strategy: ecepdi                 # default; selects the strategy plugin
section:
  prefix: [2, 2]                 # snippet context; len(prefix) = root level
                                 # elements: int | str (str for appendices, e.g. ["A"])
numbering:
  sections:
    start: {3: 3}                # optional counter offsets for DEEPER levels only
                                 # (subsection split across snippets)
  table:  {start: 2}             # first table  → 表 <sec>-2
  figure: {start: 1}             # first figure → 图 <sec>-1
  caption: {max_depth: 3}        # caption prefix clamp (ecepdi slice, parsed by strategy)
styles: {}                       # deep-merged over the strategy's shipped defaults
landscape:
  paper: a4                      # only a4 implemented; a3 reserved, not implemented
anchors:
  prefix: "anchor:"              # escape hatch if prose collides
```

### Numbering semantics

- md heading `#` → doc level `len(prefix)`; each extra `#` → +1 level.
- Author writes **bare** headings (`## 标题`); draft bakes the computed
  number as literal text (`2.2.3 标题`). No Word numPr — avoids the ghost-
  numbering defect class from the 踏勘 skeleton.
- Section counters: the walk starts at `prefix`; level-`len(prefix)` counter is
  fixed (a second heading at root level = cross-subsection → warning).
  Deeper levels count from 1 unless `numbering.sections.start` overrides.
- Table/figure counters advance in polish, once per logical selected caption,
  from `numbering.{table,figure}.start`. ecepdi uses enclosing-section scope;
  custom strategies retain `EnvSpec.counter_scope`.
- Caption prefix: the full current section path, clamped to
  `caption.max_depth` (default 3). Examples: table under `2.2` → `表 2.2-1`;
  under `2.2.3` → `表 2.2.3-1`; under `2.2.3.1` → `表 2.2.3-N` (clamped).
- A snippet that is pure prose+table under `2.2.3` contains no headings;
  `prefix: [2,2,3]` alone drives caption numbering.

## 5. Strategy contract (pluggability)

**Tool-owned (fixed for all strategies):** anchor syntax; pipeline skeleton;
op executors (pandoc-AST and python-docx); the numbering walker (section
state machine + per-scope counters); snippet.yaml top-level shape.

**Strategy-owned:** env/global-var registries; number & caption formatting;
op lists; style defaults; validation severities; jinja globals.

```python
@dataclass(frozen=True)
class EnvSpec:
    name: str                                   # "table"
    label: str                                  # "表"
    numbered: bool = True
    caption_placement: Literal["above", "below"]
    caption_required: bool = False              # False → missing caption = warning
    counter_scope: Literal["section", "chapter", "continuous"] = "section"
    caption_max_depth: int = 3
    may_contain: tuple[str, ...] = ()           # nesting: landscape contains table/figure
    caption_style: str = "Caption"
    content_style: str = "TableContent"

Phase = Literal["md_number", "md_normalize", "docx_polish"]

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
    def docx_ops(self) -> list[DocxOp]: ...

    # phase continuations (L3: scoped CPS — wrap whole phases, never per-node)
    def wrap_phase(self, phase: Phase, ctx: Ctx,
                   proceed: Callable[[Ctx], Ctx]) -> Ctx:
        return proceed(ctx)                     # default: transparent

    # defaults & config
    def default_styles(self) -> dict: ...
    def parse_config(self, raw: dict) -> Config: ...   # strategy's slice of snippet.yaml
    def severities(self) -> dict[str, Literal["error", "warn"]]: ...

    # jinja (auto-built from envs: anchor.begin/end/inline; strategy may add more)
    def jinja_globals(self) -> dict: ...
```

Control levels, in escalating order of power — use the weakest that fits:

| Level | Mechanism | Covers |
|---|---|---|
| L0 | EnvSpec data, format strings, style defaults | ~80% of customer variation |
| L1 | pure `format_section` / `format_caption` | house-style number formats |
| L2 | op-list swap (`md_ops` / `docx_ops`) | mechanical differences (三线表, no landscape) |
| L3 | `wrap_phase` continuations | mode switches (appendix), post-passes (cross-refs), state seeding (combine tool) |

L3 invariants (enforced at runtime):
- `proceed` MUST be called exactly once per `wrap_phase` invocation; an
  un-called `proceed` is an error. The tool's phase runs to completion inside
  `proceed`. Completion is phase-specific: draft has numbered headings and
  retained caption sources; polish has numbered/positioned captions. A draft
  phase continuation must not assume caption numbers already exist.
- Per-node continuations are rejected by design (a strategy that can skip the
  per-node continuation can silently stall the counters).

**Registration**: built-in `ecepdi` + Python entry-point group
`snippet_docx.strategies` for later customer packs.

**Acceptance test of the design**: adding customer X (`Table 2-1: Foo`
captions below tables, chapter-scope numbering, three-line tables, 仿宋
styles) = one new module: EnvSpec data + two format functions + a `docx_ops`
swap + a styles dict. No pipeline, validator, or anchor-parser edits.

## 6. Ops

**md phase** (pandoc JSON AST → AST, command 1):
- `ValidateAnchors` — pairing, standalone-paragraph, registry, caption-source
  discovery, Q14 policy
- `SetHeadingNumber` — bake computed section numbers into heading text;
  retain explicit heading context for emitted Markdown
- `SubstituteGlobalVar` — `anchor:section` → `2.2.3`
- `NormalizeTables` — simple/HTML tables → structured tables (pandoc eats
  simple tables → naked text; unrecoverable post-pandoc); preserve native
  caption slots, including recovered HTML `<caption>`
- `NormalizeImages` — inject missing `{width=… height=…}` attrs (giant-image
  defect from the 踏勘 pipeline)

**docx phase** (python-docx/XML, command 2):
- `NumberCaptions` — shared `captions.py` source discovery, normalization and
  per-env plans; required Markdown section context drives counters and
  `Strategy.format_caption`. Realize exactly one caption per env, preserving
  image XML; runs before `SetParagraphStyle` and landscape section breaks.
  There is no Markdown-side `NumberCaptions` op.
- `CreateStyles` — named styles from merged styles.yaml (once)
- `SetParagraphStyle` — anchor-delimited ranges: captions → caption style,
  table cells → content style, image paragraphs → centered
- `FixTable` — borders single sz=4 on all 6 edges, table centered, tblGrid
  recompute (CJK 160 twips/char, ASCII 80 twips/char at 9pt, +108 cell
  padding; numeric floor 1200, text floor 500), cell fonts per styles.yaml —
  ported from 踏勘 `fix_pandoc_tables.py`
- `ClampImageWidths` — images wider than text width clamped
- `InsertSectionBreak` — `landscape` env → next-page section break before
  (A4, orient=landscape, w/h swapped, same margins) and portrait break after;
  env = arbitrary block sequence (multiple tables + prose allowed)
- `StripAnchors` — remove all anchor paragraphs/runs at XML level

## 7. Validation policy (Q14)

| Finding | Severity |
|---|---|
| unpaired begin/end | error |
| begin/end not a standalone paragraph | error |
| unknown env name / unknown global var | error |
| `anchor:ref:*` used | error (reserved) |
| table/figure env without a usable caption | warning (style it, don't number) |
| conflicting native/ALT and explicit legacy titles in one env | warning (legacy wins) |
| second heading at root level (cross-subsection) | warning ("numbering behavior undefined") |
| heading deeper than doc level 5 | warning (styles define H1–H5 only) |

All findings are collected and reported, including findings from polish.
Validation errors cause a nonzero CLI exit; polish writes no final output
on errors. Missing `--md` is an actionable error, including direct pipeline
calls with no Markdown context.
DOCX ops may return findings (or `None`); polish accumulates them rather than
dropping them and checks errors before saving.

## 8. Verification

1. **Pure-function tests** — numbering walker (offsets, clamp, str paths),
   anchor BNF parser (valid/invalid corpus), format functions, severity table.
2. **Op-level tests** — md ops as AST→AST transforms; docx ops as XML
   assertions (borders sz=4 ×6 edges, sectPr orient=landscape, zero anchor
   residue).
3. **End-to-end acceptance** — native `Table:` / `:` titles, ALT-only figures,
   legacy-only and mixed-source envs; offsets, clamping and custom strategy
   placement/scope/formatting. Assert exactly one correctly numbered caption
   per env, no global title dedup, no drawing loss, retained recovered HTML
   captions, unchanged landscape/heading behavior, and surfaced findings.
   Exercise both emitted Markdown context and raw source Markdown; verify
   missing context and validation errors prevent final output.
4. **Repo gates** — run the project's configured checks and `uv run pytest tests/`.

These are acceptance criteria, not a record of checks performed. Prototype
evidence and implementation verification belong in the feature records.

## 9. Out of scope (v1)

- Snippet composition / combine tool (v2; blueprint: 踏勘 `compose_report.py`
  with docxcompose + Word COM TOC refresh). v1 composition = manual paste in
  Word; numbering offsets make it safe. The L3 `wrap_phase` hook is the
  combine tool's future seam for counter seeding.
- Cross-references (`anchor:ref:*` reserved).
- A3 landscape (schema field reserved, not implemented).
- Auto-injection of anchors around unwrapped tables/images.
- Word numPr multilevel list numbering (baked text chosen deliberately).

## 10. Decisions register (traceability)

| Q | Decision |
|---|---|
| Q1 | Lives in jz-toolshed `tools/snippet-docx`; pluggable strategies (ecepdi default, more customers later) |
| Q2 | pandoc → python-docx polish (both source pipelines use pandoc) |
| Q3 | Anchor = inline code span; begin/end MUST be standalone paragraphs |
| Q4 | Caption prefix = deepest section path, clamped to `caption.max_depth` (default 3) |
| Q5 | Tool bakes heading numbers as literal text |
| Q6 | Jinja render in-tool (command 1 phase); strategy ships jinja macros |
| Q7 | Landscape = A4 horizontal only; `paper` field reserved for A3 |
| Q8 | Composition out of v1; landscape via begin/end env + sectPr breaks; officecli verification |
| Q9 | Default styles = 踏勘 style.yaml verbatim + heading4/5 + caption spacing asymmetry |
| Q10 | Superseded by Q22: polish requires Markdown section context (emitted recommended; raw supported) |
| Q11 | Superseded by Q22: headings numbered in draft; captions numbered/positioned in polish |
| Q12 | pandoc JSON AST is the single md representation |
| Q13 | Landscape env = next-page breaks both sides; region may hold multiple blocks |
| Q14 | Strict/warn policy per §7 |
| Q15 | Heading mapping `#` = `len(prefix)`; schema as §4 |
| — | Constraint: one subsection per snippet; cross-subsection = warning, undefined behavior |
| Q16 | Anchor BNF §3; captions are content, not anchors; source forms extended by Q22–Q23 |
| Q17 | Op lists §6; pandoc-defect rule: preserve→polish, destroy→md-phase |
| Q18 | Verification §8 |
| Q19 | Strategy contract §5: tool owns syntax/skeleton/executor/counters; strategy owns registries/formats/ops/styles/severities |
| Q20 | Scoped CPS: `wrap_phase` phase continuations (must-call-`proceed` enforced); per-node CPS rejected; section path elements `int \| str` |
| Q21 | Clamp ownership: the tool's caption-numbering path clamps to `config.caption_max_depth` (yaml may loosen past EnvSpec default 3); `format_caption` formats the pre-clamped path verbatim — strategies never re-clamp |
| Q22 | User-approved native captions: Pandoc `Table:` / `:` and standalone image ALT; retain slots/ALT in draft, number/place in polish with required Markdown section context; emitted Markdown carries explicit heading context, not expanded caption paragraphs |
| Q23 | Legacy explicit caption wins within the same env even when wording differs; warn on conflict; normalize optional labels/stale numbers from both sources; dedup per env only and advance once per logical caption |
| Q24 | Preserve anchors, offsets, scope, clamp and strategy formatting; no implicit anchors or caption modes; prototype pointer `prototype/native-captions`, evidence/status in the feature records |

## 11. Provenance

- Style values: `…/2026-07-10-微观选址踏勘报告和初设修改/style.yaml`
  (measured from an accepted A03 踏勘报告; sample counts in file).
- Pandoc-defect repairs: 踏勘 `docx-tools/fix_pandoc_tables.py`,
  `apply_style.py`, `timeline.md` pain points.
- Anchor round-trip mechanism: `clean-mast-project/packages/typst_ir/`
  (`marker_detection.py`, `marker_removal.py`, `polish_executor.py`).
- Landscape section breaks: 踏勘 `compose_report.py` `make_section_break()`.
