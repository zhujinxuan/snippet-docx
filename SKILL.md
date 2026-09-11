---
name: snippet-docx
description: Convert a markdown snippet/subsection into a house-standard DOCX (ecepdi 排版标准) via the two-command `draft`/`polish` pipeline — md → pandoc → docx, with baked heading/table/figure numbering (表 2.2.1-1 style captions) and anchor envs (table/figure/landscape). Use when converting 可研报告/风电报告章节片段 from markdown to DOCX, composing report sections for workdir publish/deliverables, baking 表/图 caption numbers instead of hand-numbering captions in Word, or wrapping a wide table in a landscape page. Do NOT use for full-report composition or snippets crossing subsection boundaries.
---

# snippet-docx

Convert one markdown **snippet** (one subsection, or part of one) into a
house-standard DOCX meeting the **ecepdi** standard. The tool bakes heading,
table, and figure numbers as literal text pre-pandoc, then polishes the DOCX
(caption/table styles, three-line tables, A4-landscape pages, anchor stripping).

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

Real example (verified end-to-end): `section.md` holds bare heading
`# 机组选型与微观选址`, prose, a pipe table wrapped in `` `anchor:begin:table`
`` / `` `anchor:end:table` `` with numberless caption paragraph `表 各月发电量对比`;
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
# 机组选型与微观选址           ← bare heading; level = len(prefix)

本小节给出演区机组布置与风资源特征。   ← prose; `anchor:section` may appear inline

`anchor:begin:table`

表 各月发电量对比                ← caption: PLAIN paragraph starting 表␣ ;
                                   NO number — the tool assigns 表 2.2-1
                                   (above the table for ecepdi)

| 一月 | 二月 | 三月 |
|------|------|------|
| 101  | 202  | 303  |

`anchor:end:table`

以上为普通表格段落。
````

- Table env pattern (verbatim): open/close the table block with
  `` `anchor:begin:table` `` / `` `anchor:end:table` `` as standalone paragraphs.
- Figure env likewise; figure caption goes **below** the image.
- Wide table? Wrap in `` `anchor:begin:landscape` `` ... `` `anchor:end:landscape` ``;
  A4 next-page section breaks inserted before/after; the region may hold
  multiple blocks.
- Numberless OR stale-numbered captions both fine — number stripped, correct
  one assigned. Captions inside an env without one = warning, not error.

## Numbering semantics (cheat sheet)

| Input | Result |
|---|---|
| Bare `#` heading | baked as literal text at level `len(prefix)` (`prefix [2,2]` + `# X` → `2.2 X`) |
| Each extra `#` | +1 deeper level |
| Table caption under 2.2.1 | `表 2.2.1-N` (N counts per section from `numbering.table.start`) |
| Caption prefix clamp | `caption.max_depth` default 3: under `2.2.3.1` → `表 2.2.3-N` |
| `prefix [2,2,3]`, no headings | pure-prose snippet; prefix alone drives caption numbers |
| One subsection per snippet | second heading at root level = cross-subsection warning |

## Output interpretation & errors

- **draft** prints `draft: <src> -> <out>` plus findings; **polish** prints
  `polish: <docx> -> <out>` — both exit 0 when clean. Exit 1 when validation
  errors exist (draft still writes files but you must fix the md).
- Findings go to stderr as `[error]`/`[warning]` lines. Validation severities:

| Finding | Severity |
|---|---|
| unpaired begin/end | error |
| begin/end not standalone paragraph | error |
| unknown env/global var | error |
| `anchor:ref:*` used | error (reserved) |
| env without caption paragraph | warning (styled, not numbered) |
| second root-level heading (cross-subsection) | warning ("numbering behavior undefined") |
| heading deeper than level 5 | warning |

- pandoc missing → `error: pandoc not found on PATH`.
- After fixing findings, re-run draft then polish. Always eyeball final.docx;
  officecli can assert contents programmatically if needed.

## Testing the skill itself

```bash
cd ~/.agents/skills/snippet-docx && uv run pytest tests/
```

180 tests covering walker/anchors/captions/landscape/e2e pass here (pandoc
3.7, Python 3.13).
