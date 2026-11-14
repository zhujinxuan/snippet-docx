---
name: snippet-docx
description: Convert a markdown snippet/subsection into a house-standard DOCX (ecepdi 排版标准) via the two-command `draft`/`polish` pipeline — md → pandoc → docx, with baked heading/table/figure numbering (表 2.2.1-1 style captions) and anchor envs (table/figure/landscape). Use when converting 可研报告/风电报告章节片段 from markdown to DOCX, composing report sections for workdir publish/deliverables, baking 表/图 caption numbers instead of hand-numbering captions in Word, or wrapping a wide table in a landscape page. Do NOT use for full-report composition or snippets crossing subsection boundaries.
---

# snippet-docx

Convert one markdown **snippet** (one subsection, or part of one) into a
house-standard DOCX meeting the **ecepdi** standard. Draft bakes heading
numbers as literal text; polish numbers and positions table/figure captions,
applies house styles, inserts A4-landscape pages, and strips anchors.

The code originated from `jz-toolshed tools/snippet-docx`; this skill dir is
its canonical working home (repo copy left as-is; retiring it is a later
decision). The settled design lives in [`references/ToolSpec.md`](references/ToolSpec.md)
(pipeline, anchor grammar, snippet.yaml schema, strategy contract, validation
severities) — read it before extending strategies, ops, or the schema.

## Prerequisites

- **`pandoc` on PATH** — external binary, not managed by uv. Check with
  `pandoc --version`. If missing: both commands fail early with
  `error: pandoc not found on PATH`; install it (e.g. `scoop install pandoc`)
  and retry. Verified against pandoc 3.7.
- `uv` — creates this skill's own `.venv` (`cd <skill> && uv sync`, once).
- bun is NOT needed.

## Invocation

Run from **any** cwd — point uv at the skill's project, never cd into it:

```bash
# {SKILL} = ~/.agents/skills/snippet-docx
uv run --project ~/.agents/skills/snippet-docx snippet-docx --help
```

`--project` selects the skill's `.venv`/`uv.lock` but leaves your cwd alone.
Relative image paths in the md resolve against the **md file's directory**
(pandoc `--resource-path` + the tool's own image sizing), so outputs are
identical no matter where you run from. Do **not** `cd` into the skill dir:
it changes nothing for the tool and only risks confusing path resolution for
your own inputs.

(The long form `--project <dir>` is required — uv's `-p` means `--python`,
not `--project`.)

## Use when / Do NOT use when

**Use when:** you have a markdown fragment of a report section and need a
standard-compliant DOCX piece: numbering baked, tables fixed to house table
conventions (borders, widths, fonts), landscape pages inserted around wide
tables/figures, anchors stripped so no residue survives in final.docx.

**Do NOT use when:** composing a full report from many snippets — out of scope
(v2 combine tool); pasting is manual in v1. Also not for content spanning
several subsections — split them, convert each, paste.

## The two-command pipeline

Every conversion = draft → polish:

```bash
# {SKILL} = ~/.agents/skills/snippet-docx; run from anywhere
uv run --project ~/.agents/skills/snippet-docx snippet-docx draft  <path>/section.md \
    --snippet <path>/snippet.yaml --out <path>/draft.docx --emit-md <path>/anchored.md
uv run --project ~/.agents/skills/snippet-docx snippet-docx polish <path>/draft.docx \
    --snippet <path>/snippet.yaml --md <path>/anchored.md --out <path>/final.docx
```

Example: `section.md` holds bare heading `# 机组选型与微观选址`, prose,
and a pipe table wrapped in `` `anchor:begin:table` `` /
`` `anchor:end:table` `` with native caption `Table: 各月发电量对比`;
`snippet.yaml` declares the position:

```yaml
strategy: ecepdi
section:
  prefix: [2, 2]          # root heading lands at level len(prefix) => "2.2 …"
numbering:
  table: {start: 1}       # first table caption becomes 表 2.2-1
```

Commands (run from anywhere; paths outside the skill dir are fine; outputs
next to inputs):

```bash
P=C:/Users/zhu_j/workspace/<proj>/publish   # wherever your section lives; NOT inside this skill
uv run --project ~/.agents/skills/snippet-docx snippet-docx draft  "$P/section.md" \
  --snippet "$P/snippet.yaml" \
  --out     "$P/draft.docx" \
  --emit-md "$P/anchored.md"
uv run --project ~/.agents/skills/snippet-docx snippet-docx polish "$P/draft.docx" \
  --snippet "$P/snippet.yaml" --md "$P/anchored.md" \
  --out     "$P/final.docx"
```

## Writing the snippet's markdown

One subsection per snippet. Author bare headings and plain paragraphs; wrap
tables/figures/landscape regions in anchor envs as **standalone code-span
paragraphs** (blank lines around them):

````markdown
# 机组选型与微观选址

本小节给出演区机组布置与风资源特征。

`anchor:begin:table`

| 月份 | 发电量 |
|------|--------|
| 一月 | 101    |
| 二月 | 202    |

Table: 各月发电量对比

`anchor:end:table`

`anchor:begin:figure`

![机组布置示意](layout.png)

`anchor:end:figure`
````

- **Table title:** use Pandoc Markdown `Table: 标题` or `: 标题` on a
  separate paragraph adjacent to the table, inside its env. The pipe table's
  first row (`月份 | 发电量`) is the **column header**, not the table caption.
- **Figure title:** use the image ALT text, `![标题](image.png)`, with the
  image alone in its paragraph inside a figure env. ALT is normally fallback/
  accessibility text in Markdown; this pipeline's Pandoc dialect also uses it
  as a figure caption. It does not auto-wrap images in anchors.
- Write titles only: no manually typed `表`/`图` label or number is needed.
  Optional labels and stale numbers are normalized before final numbering.
- **Legacy compatibility:** explicit plain `表 标题` / `图 标题` paragraphs
  still work. In the same env, the explicit paragraph wins over a native/ALT
  title, even if wording differs; conflicting titles produce a warning.
  Deduplication is local to the env, never global by title: identical titles
  in separate envs each receive their own number.
- Polish positions the single selected caption: ecepdi table **above** the
  table, figure **below** the image. An env with no usable caption produces
  a warning and is styled without numbering; an empty native title can fall
  back to a legacy paragraph.
- A selected native caption retains rich DOCX content (including native
  equations and hyperlinks) when numbered/moved; an explicit legacy winner
  still replaces a losing native title. Strategy formatting controls the
  label/number envelope. A custom formatter that rewrites or duplicates a
  rich title fails explicitly rather than flattening its content.
- Wide table? Wrap in `` `anchor:begin:landscape` `` ...
  `` `anchor:end:landscape` ``; A4 next-page section breaks are inserted
  before/after, and the region may hold multiple blocks.

`polish --md` is required for section context. Prefer the `--emit-md` output:
it retains anchors and explicit heading context while keeping native/ALT
captions unexpanded and unnumbered. Raw source Markdown is also supported.
Heading numbering belongs to draft; caption numbering and placement belong
to polish. Keep the Markdown paired with its draft DOCX.

## Numbering semantics (cheat sheet)

| Input | Result |
|---|---|
| Bare `#` heading | baked as literal text at level `len(prefix)` (`prefix [2,2]` + `# X` → `2.2 X`) |
| Each extra `#` | +1 deeper level |
| Table caption under 2.2.1 | `表 2.2.1-N` (N counts per section from `numbering.table.start`) |
| Caption prefix clamp | `caption.max_depth` default 3: under `2.2.3.1` → `表 2.2.3-N` |
| `prefix [2,2,3]`, no headings | pure-prose snippet; prefix alone drives caption numbers |
| One subsection per snippet | second heading at root level = cross-subsection warning |

## Image and native-equation layout

Polish keeps images inline and equations native/editable OMML. Image-only
paragraphs use `figure_image`, independently of `figure_caption`; native
display-equation paragraphs use `display_equation`. The defaults center
these object roles with zero indentation: image before 6 pt / after 5 pt,
auto 1.5-line leading; display equation before/after 6 pt, at-least 23 pt.
These separation values are not a guarantee of Word non-overlap.

Inline math keeps its prose/list/table/heading/caption role and typography.
Every image- or native-math-containing paragraph gets an effective-leading
guard: exact leading (including direct overrides) becomes at-least at the
same point floor; auto/at-least remains unchanged. Ordinary non-math/non-image
typography, including exact 23 pt body leading, is unchanged.

Override through `snippet.yaml`'s existing `styles.style` merge, for example:

```yaml
styles:
  style:
    figure_image:
      space_before_pt: 8
      space_after_pt: 5
    display_equation:
      line_spacing: 25
      line_spacing_rule: atLeast
```

`auto` uses a line multiplier; `exact` and `atLeast` use points. The object
roles default to `reset_indentation: true`; `left_indent_pt` /
`right_indent_pt` configure their point-based side indents. See
[the layout contract](references/ToolSpec.md#paragraph-allocation-and-style-overrides)
before changing roles, inheritance or direct paragraph properties.

## Output interpretation & errors

- **draft** prints `draft: <src> -> <out>` plus findings; **polish** prints
  `polish: <docx> -> <out>` plus findings — both exit 0 without validation
  errors. Exit 1 on validation errors: draft still writes its diagnostic
  artifacts; polish does not write the final DOCX.
- Findings go to stderr as `[error]`/`[warning]` lines. Validation severities:

| Finding | Severity |
|---|---|
| unpaired begin/end | error |
| begin/end not standalone paragraph | error |
| unknown env/global var | error |
| `anchor:ref:*` used | error (reserved) |
| selected rich caption has no matching native DOCX slot (`caption-context-mismatch`) | error (keep paired draft/Markdown) |
| strategy rewrites/duplicates a rich title (`caption-format-unsupported`) | error (retain the title in the format) |
| table/figure env without a usable caption | warning (styled, not numbered) |
| conflicting native/ALT and explicit legacy titles in one env | warning (legacy wins) |
| second root-level heading (cross-subsection) | warning ("numbering behavior undefined") |
| heading deeper than level 5 | warning |

- pandoc missing → `error: pandoc not found on PATH`.
- After fixing findings, re-run draft then polish. Inspect final.docx
  manually in the intended viewer. XML/content checks do not certify Word
  line/page layout or non-overlap; HTML is an approximation. Keep Word as
  the user's manual review surface—no Word COM, `officecli refresh` or
  unverified Word-backed exports.

## Testing the skill itself

```bash
cd ~/.agents/skills/snippet-docx && uv run pytest tests/
```

