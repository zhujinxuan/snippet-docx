# Inline image and equation layout

Status: implementation and structural verification complete; manual Word layout verification pending; original failing equation artifact unavailable.

The original handoff below is preserved as historical context. Dated implementation findings follow it; historical proposals and the 211-test baseline are not current verification results.

## Goal and workspace

Prevent image/equation overlap without changing images to floating objects or flattening native equations. Keep the native-caption feature merged in `b891489` intact.

Prepared worktree: `C:/Users/zhu_j/worktrees/snippet-docx-inline-object-layout`, branch `fix/inline-object-layout`, created from main at `b891489`. Use this worktree for diagnosis, fixes, tests and documentation. Do not implement on the canonical main worktree. These handoff files are intentionally uncommitted and must be preserved by the next session.

## Tickets

1. [Image/table boundary collision and image paragraph spacing](issues/01-inline-image-spacing.md).
2. [Equation overlap and insufficient paragraph line allocation](issues/02-equation-line-allocation.md).

The tickets are independent investigations but share `SetParagraphStyle` and the house stylesheet. Assign one owner to those shared source files; parallelize independent reproduction/fixture work, not conflicting edits.

## Evidence and certainty

The user reported table/image overlap and supplied a screenshot. Treat that observation as ground truth; do not ask them to reproduce it merely to confirm the report. The image sample was inspected structurally, not rendered through Word by the agent. Its dimensions survive conversion and its drawing is inline. Missing separation is a candidate explanation for the table/image boundary collision, not a proven Word rendering root cause.

The user also reports that equations can overlap. No equation-bearing failing artifact was supplied or inspected in this session. Exact 23 pt body leading is a concrete risk, not a confirmed cause of that report. The next session must investigate native inline and display equations rather than claiming an equation fix from image evidence.

`evidence/` preserves the user screenshot and the previously generated sample inputs/output. See each ticket for artifact roles. The sample includes intentional caption conflicts and a captionless table; their warnings are expected and unrelated to overlap.

## Shared constraints

- Keep images as `wp:inline`; preserve intended dimensions, aspect ratio and accessibility ALT.
- Keep equations native/editable OMML. No image replacement or home-grown equation metrics engine.
- Prefer the existing DOCX `polish` phase when Pandoc preserves the relevant structures. Fix upstream only if evidence shows that the conversion destroys or corrupts necessary data.
- Preserve paragraph roles: image, figure caption, display equation and ordinary body text are not interchangeable.
- Preserve caption numbering, placement, per-env deduplication, strategy overrides, relative image resolution and landscape behavior.
- No blank-paragraph spacers, inflated image extents, arbitrary image shrinking or blanket body-style changes to disguise overlap.
- Object dimensions are not final page-space bboxes. Image extents can be read directly; equation dimensions and all final x/y positions require layout. XML checks cannot certify rendered non-overlap.
- No Word COM, `officecli refresh`, or Word-backed exporter automation. Manual target-viewer inspection is allowed. HTML/non-Word rendering is diagnostic evidence, not exact Word pagination proof.

## Completion

For each ticket, record the actual cause, changed path, focused behavioral regression coverage, real draft-to-polish smoke results and any target-viewer visual evidence. Distinguish structural checks from rendered collision verification. If no supported target-viewer verification is available, report that limit explicitly rather than claiming Word layout is fixed. Update existing skill/design documentation for any new paragraph roles or style contracts; remove throwaway scripts after retaining the useful evidence.

Baseline feature verification before this work: 211 tests and `ruff check src tests` passed. These are historical results, not verification of a future layout fix.

Next-session instructions: [next-session-prompt.md](next-session-prompt.md).

## 2026-11-14 implementation findings

### Diagnosed paths and confidence

- **Images:** a real Pandoc 3.7.0.2 draft → polish baseline is retained as `evidence/image-baseline-{draft.docx,anchored.md,final.docx}`. The first image and hyperlink-wrapped landscape image immediately follow their tables. Both image paragraphs receive `figure_caption`, whose effective spacing is before 0 pt / after 5 pt / automatic 1.5 lines; there is no direct spacing override. Normal has an empty paragraph-property definition and document defaults specify only after 200 twips. No floating tables were found. This confirms role coupling and absent configured pre-image separation, not the exact Word-rendered cause of the screenshot's collision.
- **Native math:** [synthetic baseline findings](evidence/math-baseline/findings.json), [AST trace](evidence/math-baseline/math-ast-trace.json), [effective paragraph trace](evidence/math-baseline/paragraph-property-trace.json) and [per-op trace](evidence/math-baseline/polish-stage-trace.json) distinguish conversion from polish. Source and emitted Markdown retain six InlineMath and three DisplayMath formulas. Draft has nine `m:oMath` and three `m:oMathPara`; baseline polish leaves eight and three. `SetParagraphStyle` introduces exact 23 pt leading on observed heading, prose, list and display math; display math also inherits body justification/two-character indentation. Table-cell math already uses automatic 1.5-line leading.
- **Caption content loss:** the baseline `NumberCaptions` stage changes nine native math nodes to eight by rebuilding the native table caption as plain text containing literal TeX. A separate native figure-caption probe reproduces one-to-zero math loss. CreateStyles preserves 9→9 and later stages preserve 8→8. All eight surviving math subtrees retain semantic fingerprints. This is a demonstrated independent content-preservation bug, not merely a line-allocation concern.
- **Direct spacing:** the diagnostic `direct-exact-draft.docx` deliberately injects exact 10 pt direct leading. Baseline polish retains it despite automatic 1.8 named-style overrides. This proves that style-only changes are insufficient; it is not a property naturally emitted by the observed Pandoc baseline or evidence about the unprovided original equation artifact.

The original failing equation source/output remains unavailable. Synthetic structure demonstrates a fixed-allocation path and caption loss, but neither equation height nor final page-space bounds have been measured. The user's overlap reports remain ground truth; neither original rendering mechanism is established.

### Implemented seam and contracts

The ecepdi operation order remains `CreateStyles`, `NumberCaptions`, `SetParagraphStyle`, `FixTable`, `ClampImageWidths`, `InsertSectionBreak`, `StripAnchors`. The correction stays in polish because observed Pandoc drafts retain native image/math structure.

- `figure_image` separates image-only paragraphs from actual `figure_caption`: centered, before 6 pt / after 5 pt, auto 1.5 by default. `display_equation` selects native `m:oMathPara`: centered, before/after 6 pt, `atLeast` 23 pt. Inline math keeps its ordinary role.
- Override through `styles.style.<role>`. `line_spacing_rule: atLeast` extends the existing rule contract: `exact`/`atLeast` values are points; `auto` is a multiplier. `reset_indentation: true` on the two object roles explicitly resets inherited/direct indentation aliases; `left_indent_pt`/`right_indent_pt` configure side indents. Existing ordinary styles are not opted into that reset.
- After classification, all image/native-math paragraphs resolve winning line attributes through direct paragraph properties, assigned style/basedOn and docDefaults. Exact leading becomes at-least at the same resolved floor; auto/at-least stays unchanged. Object-role alignment/indentation is applied from resolved configuration; unrelated direct properties and direct before/after spacing are retained. Ordinary non-object typography, including exact 23 pt body text, remains unchanged.
- Caption numbering retains/moves the selected rich native or explicit legacy paragraph, normalizes only leading label/number text and preserves native OMML, hyperlinks, fields and runs. Winner precedence, losing-caption removal, placement and counters remain unchanged. Strategy formatting supplies the surrounding envelope; a rich-title rewrite/duplication fails explicitly (`caption-format-unsupported`) instead of flattening.

These are paragraph-allocation/preservation contracts, not a bespoke equation metrics engine or a rendered-layout guarantee. See [ToolSpec's authoritative override contract](../../references/ToolSpec.md#paragraph-allocation-and-style-overrides).

### Verification boundary

All `evidence/math-baseline/` outputs are **pre-fix diagnostic artifacts**, including its `final.docx`; their names do not imply corrected output. [commands.json](evidence/math-baseline/commands.json) records exact argv, cwd, exit status and stdout/stderr. Diagnostic draft/polish and AST commands exited 0 under Pandoc 3.7.0.2; no test-suite result is implied.

The environment has Pandoc, uv, officecli and pdftoppm, but no soffice/mutool or existing Word process. No permitted target-viewer rendering route was available. Word remains the user's manual review surface; no Word automation or Word-backed export is used. HTML is not exact Word layout proof. Manual table/image/caption separation and equation non-overlap remain pending independently of structural implementation.

### Structural red-before evidence

The parent ran a read-only contract assertion on the preserved `evidence/math-baseline/draft.docx` versus `final.docx`. It observed native-math counts `(9, 8)` and exact-leading math roles `heading2`, five `normal_text` paragraphs and `list_item`, then exited 1 with `AssertionError: Baseline fails native-math preservation and expandable line-allocation contract`. This is an expected **pre-fix structural failure** proving that the preservation/allocation contract catches the diagnosed baseline paths. It is not a target-viewer collision reproduction or a failing post-fix result.

### Landscape spacer correction

The implementation also removes `InsertSectionBreak`'s redundant bare paragraph after the landscape end anchor. Word section properties close the preceding section; the terminal body section properties or a later portrait-close carrier govern following portrait content, so a blank portrait "opener" is not required. Genuine section-break carriers, including table-only landscape closure, are retained along with section ordering, A4 geometry, margins and next-page semantics. This corrects the discovered no-spacer regression without changing image extents or using blank paragraphs to create separation.

### Real conversion commands and artifact mapping

The parent exercised the following input/output pairs from the prepared worktree using `uv run --project .` (PowerShell shorthand below). The final verification result is recorded separately; command success alone is not structural or rendered acceptance.

```powershell
$E = '.scratch/inline-object-layout/evidence'
uv run --project . snippet-docx draft "$E/source.md" --snippet "$E/snippet.yaml" --out "$E/image-fixed-draft.docx" --emit-md "$E/image-fixed-anchored.md"
uv run --project . snippet-docx polish "$E/image-fixed-draft.docx" --snippet "$E/snippet.yaml" --md "$E/image-fixed-anchored.md" --out "$E/image-fixed-final.docx"
uv run --project . snippet-docx draft "$E/math-baseline/source.md" --snippet "$E/math-baseline/snippet.yaml" --out "$E/math-fixed-draft.docx" --emit-md "$E/math-fixed-emitted.md"
uv run --project . snippet-docx polish "$E/math-fixed-draft.docx" --snippet "$E/math-baseline/snippet.yaml" --md "$E/math-fixed-emitted.md" --out "$E/math-fixed-final.docx"
uv run --project . snippet-docx draft "$E/math-baseline/figure-caption-source.md" --snippet "$E/math-baseline/snippet.yaml" --out "$E/figure-math-fixed-draft.docx" --emit-md "$E/figure-math-fixed-emitted.md"
uv run --project . snippet-docx polish "$E/figure-math-fixed-draft.docx" --snippet "$E/math-baseline/snippet.yaml" --md "$E/figure-math-fixed-emitted.md" --out "$E/figure-math-fixed-final.docx"
uv run --project . snippet-docx polish "$E/math-baseline/direct-exact-draft.docx" --snippet "$E/math-baseline/auto-style-override.yaml" --md "$E/math-baseline/emitted.md" --out "$E/direct-exact-fixed-final.docx"
```

`math-baseline/direct-exact-draft.docx` is the preserved diagnostic injection, not fresh Pandoc output or the user's original equation file. The fixed outputs are distinct from the immutable historical screenshot/report and pre-fix baselines.

### Final integrated verification — 2026-11-14

The parent ran `uv run pytest tests/ && uv run ruff check src tests` from the prepared worktree: **268 passed in 121.00 s**, followed by **All checks passed!** from Ruff (exit 0). The final suite includes `tests/test_inline_object_layout.py` (13), `tests/test_captions.py` (71), `tests/test_styles.py` (26), `tests/test_strategy_seam.py` (38) and `tests/test_landscape.py` (16). These are current implementation results; the earlier 211-test result remains historical.

Focused coverage includes independent image/caption layout overrides; inherited/direct exact-leading correction; automatic/at-least retention; display versus inline-math role selection across heading/body/list/table/caption paths; rich native/legacy winner preservation and losing-caption removal; native caption provenance across captionless/inline objects; numeric/rich titles colliding with section labels; authoritative custom strategy formatting and explicit unsupported rich rewrites; positive-indent reset without conflicting hanging attributes; and no added nonstructural spacer while retaining section carriers.

After the final code corrections, every real conversion in the command recipe above was rerun and exited 0. Read-only assertions also exited 0; the persisted result is [final-smoke-verification.json](evidence/final-smoke-verification.json):

| Output | Final observed structural result |
|---|---|
| [image-fixed-final.docx](evidence/image-fixed-final.docx) | All three drawing payloads and media match draft; images use before 120 / after 100 twips, auto `line=360`, zero indentation; all ten sample captions appear exactly once; sections remain portrait → landscape → portrait; no nonstructural blank spacers. |
| [math-fixed-final.docx](evidence/math-fixed-final.docx) | Native math 9→9 with unchanged OMML semantics and three display wrappers; previously exact body/heading/list/display math uses `atLeast line=460`; table-cell/table-caption math retains auto `line=360`; plain CONTROL paragraphs retain exact 23 pt leading. |
| [figure-math-fixed-final.docx](evidence/figure-math-fixed-final.docx) | Native figure-caption math retained 1→1, rather than baseline flattening. |
| [direct-exact-fixed-final.docx](evidence/direct-exact-fixed-final.docx) | Injected direct-exact diagnostic retains 9→9 native math; all affected lines become `atLeast line=200`, preserving the injected 10 pt floor rather than imposing a guessed formula height. |

Review corrections are included in those final results: caption reuse follows the selected table/drawing identity (including captionless objects), numeric-title envelope recovery validates against real formatter output, and indentation reset removes competing hanging attributes. Formatter call count is deliberately not a contract; the pure formatter may be probed.

**Remaining manual acceptance:** visible table/image lower-border separation, image/caption separation, linked landscape/page-boundary layout, and tall inline/display equation clipping/non-overlap are not verified in Word. The parent only read `officecli view --help`: screenshot `--render auto` defaults to native on Windows and page-count needs Word repagination; no screenshot/PDF/refresh/page-count command or Word launch was performed. No permitted target-viewer route was available. The missing original equation artifact additionally prevents exact original-case diagnosis. Implementation/structural completion must not be read as a pass for those rendered criteria.
