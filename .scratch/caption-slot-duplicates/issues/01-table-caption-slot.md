# Table caption slot duplicates the numbered caption

Status: resolved

## Problem

Pandoc's `table_captions` extension (default ON) folds a `Table: xxx` (or
`: xxx`) paragraph after a table into the Table block's caption slot
(`c[1]`). No tool component reads that slot — walker
(`src/snippet_docx/walker.py:190-202`), ValidateAnchors
(`src/snippet_docx/anchors.py:171-176`), and
`NumberCaptions`/`_move_to_placement` (`src/snippet_docx/ops_md.py:111-177`)
all inspect only plain `表 ` paragraphs (ToolSpec §3 contract: captions are
plain paragraphs). Pandoc's docx writer then emits the slot as an
**unnumbered** `Table Caption` paragraph directly above the table, and
polish's `_PANDOC_CAPTION_STYLES` (`src/snippet_docx/ops_docx.py:68-70`)
restyles it as a house `table_caption` — a duplicate of the tool's numbered
`表 2.2-1 …` caption that looks legitimate. One caption with index, one
without: the same hole the figure path had (`implicit_figures`, fixed in
`pandoc_ast.py` by parsing with `-implicit_figures`).

Verified empirically (pandoc 3.7.0.2): pipe table + `Table: 电量对比` →
slot `[null, [Plain [Str "电量对比"]]]`; `ast_to_docx` emits
`p[Table Caption] 电量对比` above `w:tbl`; empty slot emits nothing.
With `-table_captions`, pipe AND simple tables parse with empty slot and the
`Table: xxx` line survives as a literal plain paragraph.

A second injection path the reader flag cannot reach: `_recover_html_run`
(`src/snippet_docx/ops_md_normalize.py:162-181`) re-parses raw HTML via
`pandoc -f html`, whose reader populates the slot from `<caption>` elements.

## Design (agreed: C — flag + strip)

1. `md_to_ast` (`src/snippet_docx/pandoc_ast.py`): add `-table_captions`
   alongside `-implicit_figures`. `Table: xxx` lines degrade honestly to
   visible stray prose + captionless-env warning, matching the §3 contract.
2. Normalize-phase strip: in `NormalizeTables`
   (`src/snippet_docx/ops_md_normalize.py`), clear any surviving non-empty
   Table caption slot to `[None, []]` and emit a `warn` finding naming the
   dropped text (covers HTML `<caption>` recovery and future readers).
3. Keep `_PANDOC_CAPTION_STYLES` as last-ditch styling defense (the HTML
   path means ImageCaption/TableCaption stay reachable in principle).

Caption placement (ecepdi table = above) is already correct and stays the
plugin's responsibility (`strategies/ecepdi.py:29`,
`NumberCaptions._move_to_placement`); this ticket only closes the slot hole.

## Tests (assert-absence regression — none of the existing caption tests
would have caught either duplicate)

1. `test_table_caption_line_does_not_populate_slot` — md_to_ast on pipe
   table + `Table: 电量对比`: slot empty, line survives as plain Para.
2. `test_table_caption_slot_stripped_with_finding` — hand-built AST with
   non-empty slot through NormalizeTables: slot emptied, finding emitted.
3. `test_html_recovered_table_caption_slot_cleared` — test_repair.py:
   `<table><caption>…</caption></table>` through md_to_ast + NormalizeTables:
   real Table, empty slot, finding emitted.
4. `test_no_duplicate_captions_at_cli` — CLI seam mirroring
   `test_caption_numbers_and_placement_in_md_and_docx`
   (tests/test_captions.py:240-307): figure env with alt text + caption
   Para, table env with `表 ` Para + trailing `Table: xxx` line; final.docx
   has exactly one 表/图 caption each and no unnumbered caption paragraphs.

## Acceptance

- All four tests fail before the src changes (where applicable) and pass
  after; full `uv run pytest tests/` green.
- The `Table:`+caption duplicate from the Problem section no longer appears
  in final.docx.


## Answer

Design C implemented (flag + strip), 185/185 green:

- `src/snippet_docx/pandoc_ast.py` — `md_to_ast` now parses with
  `-f markdown-implicit_figures-table_captions` (docstring extended:
  same rationale as `-implicit_figures`, ToolSpec §3). `Table: xxx`
  lines degrade honestly to visible stray prose.
- `src/snippet_docx/ops_md_normalize.py` — `NormalizeTables` gained a
  final pass after all existing processing (HTML-run recovery included):
  every top-level `Table` whose caption slot `c[1]` is not `[None, []]`
  gets the slot cleared and a warn finding emitted —
  `table-caption-slot: dropped Table caption slot '电量对比': captions are
  plain 表-prefixed paragraphs (ToolSpec §3); the slot would render an
  unnumbered duplicate`. Covers the `_recover_html_run` `<caption>` path.
- `_PANDOC_CAPTION_STYLES` (ops_docx.py) untouched, last-ditch defense.
- Tests: `test_table_caption_line_does_not_populate_slot` +
  `test_table_caption_slot_stripped_with_finding` +
  `test_no_duplicate_captions_at_cli` (tests/test_captions.py, fixtures
  tests/data/captions-dup.{md,yaml}), and
  `test_html_recovered_table_caption_slot_cleared`
  (tests/test_repair.py). The CLI test was verified RED pre-fix: the
  final docx contained an unnumbered `电量对比` slot caption beside
  `表 2.2-1 电量对比`; post-fix the only 电量对比 paragraphs are the
  numbered caption and the honest stray `Table: 电量对比` line.

## Comments
