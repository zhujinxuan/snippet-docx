# Equation overlap: investigate native math line allocation

Status: implementation and structural verification complete; original-equation diagnosis unavailable; manual Word equation layout verification pending.

Original handoff scope (preserved): actionable diagnosis and implementation in a **new session**. The original sections record the report, static source evidence and proposed work only. Dated diagnosis/implementation findings below distinguish subsequent conversions from that handoff.

## User report and evidence limits

The user reports that equations can overlap surrounding content. Treat that observation as ground truth. **No equation-bearing failing source, draft DOCX, final DOCX or target-viewer screenshot was supplied or inspected in this session.** The triggering formula, inline/display path, effective paragraph properties and rendering cause remain unknown.

The house `normal_text` style uses exact 23 pt leading. That is a concrete risk for tall equations, **not a proven root cause of the reported equation overlap**. Do not close this ticket by extrapolating from image evidence or by changing body leading without tracing the math path.

The files in `../evidence/` are image/table evidence, not an equation reproduction. In particular, `main-final.docx` is a structural reference generated from the image sample with merged main; it does not establish Word-rendered equivalence to the user's original output or demonstrate equation behavior.

## Known source evidence

Paths below are relative to the prepared worktree; line ranges describe the handoff baseline, not guaranteed future positions.

- `src/snippet_docx/pandoc_ast.py::md_to_ast` (45–51) reads `markdown+implicit_figures+table_captions` through Pandoc JSON. `ast_to_docx` (61–74) sends JSON directly to Pandoc's DOCX writer. `ast_to_md` (54–58) produces the emitted Markdown. There is no equation-specific writer option in these wrappers. The actual `Math` kinds and resulting OMML have **not** been observed in a conversion for this ticket.
- `src/snippet_docx/pipeline.py::draft` (64–99) parses the source, runs numbering/normalization and writes DOCX from the AST. `polish` (102–151) reparses paired Markdown for context, loads the supplied draft using `Document`, runs DOCX operations and saves the result. Compare both artifacts; do not assume polish is the first point at which a layout-affecting change occurs.
- `src/snippet_docx/ops_docx.py::SetParagraphStyle` (146–227) has branches for table cells, headings, captions, lists, image-only paragraphs and env captions, then assigns `normal_text`. There is no explicit OMML/display-equation branch in this implementation. **[INFERENCE]** A top-level `w:p` containing display math that matches none of the preceding branches will fall through to `normal_text`; whether Pandoc produces that exact paragraph shape/style for the failing case must be captured. Table cells and other early branches also matter for inline math.
- `src/snippet_docx/ops_docx.py::_set_pstyle` (110–120) changes only `w:pStyle`; it does not clear existing direct `w:pPr/w:spacing`. Merely introducing a named equation style cannot be assumed to override conflicting direct spacing.
- `styles/ecepdi-default.yaml::style.normal_text` (95–106) specifies 12 pt 宋体/Times New Roman, justified text, zero space before/after, 23 pt exact leading and a two-character first-line indent. `src/snippet_docx/styles.py::line_spacing_attrs` (90–96) maps `exact` to twips and `auto` to multiplier units; 23 pt therefore becomes `w:line="460" w:lineRule="exact"`. `_build_ppr` (119–143) emits style spacing. The helper currently accepts only `auto|exact`, so proposing `atLeast` is not claiming that it already works in the style configuration.
- `src/snippet_docx/ops_docx.py::ecepdi_docx_ops` (660–663) runs `CreateStyles`, caption numbering, paragraph assignment and existing repairs, with `StripAnchors` last. Prefer a correction within this polish/style seam if the native math structure survives Pandoc.
- `tests/test_e2e.py` already checks house body style properties and paragraph assignment. Its existing expectations are relevant regression contracts, not evidence that math is covered or renders correctly.

## Required diagnosis in the implementation session

1. Establish a minimal failing path without asking the user to re-prove the report. Inspect any available equation artifact first; otherwise build the candidate fixtures below and label them synthetic. Record Pandoc version, input, snippet/style overrides, paired emitted Markdown, draft and final DOCX, viewer/version and the specific failing location. If synthetic examples do not reproduce the reported collision, say so rather than equating a risk with a captured failure.
2. Trace source formula → Pandoc JSON `Math` with `InlineMath` or `DisplayMath` → DOCX native math (`m:oMath`, `m:oMathPara`, and their actual `w:p` containers). Capture each kind's real output structure, paragraph style and relevant OMML before and after polish. Confirm emitted Markdown preserves the formula and inline/display semantics. Do not infer display status from the absence of ordinary `w:t`, or assume every math paragraph is a top-level body paragraph.
3. Follow `SetParagraphStyle` for the observed display paragraph, including any pre-existing Pandoc style. Determine whether it really falls through to `normal_text` or takes another branch. Inspect mixed prose/inline math and math inside other paragraph roles so that an early `continue` cannot bypass the eventual safe-leading policy.
4. Resolve **effective**, not merely named, spacing for every failing math-containing paragraph: direct `w:pPr/w:spacing`, paragraph style, `w:basedOn` inheritance and `w:docDefaults`. Record `line`/`lineRule`, before/after spacing, indentation and any relevant contextual spacing or document-grid behavior. Check adjacent paragraph spacing too. Compare draft versus polished values and snippet overrides. Identify which setting actually wins; changing a style while leaving a direct exact override is not a fix.
5. Separate line-box allocation/clipping from inter-paragraph separation, page-boundary behavior and conversion corruption. Retain OMML and font/math settings while determining the cause. The diagnosis must identify the actual affected path and supporting evidence; exact 23 pt remains a hypothesis until then.

### Candidate fixtures — proposed, not executed

Use a small valid subsection/snippet configuration and prose before and after each case. Keep these cases independently identifiable in the resulting DOCX:

- Inline fraction: `正文前 $\frac{a+b}{c+d}$ 正文后。`, with adjacent prose lines/paragraphs to expose ascent/descent allocation.
- Inline superscript: `正文前 $x^{n+1}+y^{2}$ 正文后。`; include a wrapped prose paragraph so math sharing a line does not escape coverage.
- Display fraction: `$$\frac{a+b}{c+d}$$`, on its own block between ordinary paragraphs.
- Display matrix: `$$\begin{pmatrix}a & b \\ c & d\end{pmatrix}$$`.
- Display large operators: `$$\sum_{i=1}^{n} x_i + \int_{0}^{1} f(x)\,dx$$`, with limits and adjacent prose.

Exercise the actual source/configuration implicated by diagnosis as well as these minimal cases. Add focused mixed-role coverage for math in lists/table cells/headings/captions where those supported roles would otherwise bypass paragraph handling; preserve their existing role rather than reclassifying them all as display equations. Include a plain non-math control and neighboring image/caption content to catch cross-ticket regressions. Do not claim these fixtures have been tested in this session.

## Suggested fix direction — pending diagnosis

- Preserve native editable OMML and source formula semantics. Prefer polish-time paragraph/style correction when conversion has retained the required structures; only change upstream conversion if evidence shows it loses or corrupts them.
- Introduce a dedicated **display-equation paragraph role**, separate from ordinary body, image and caption roles. Select its alignment, indentation and before/after spacing deliberately from the house requirements and observed output, not by borrowing `figure_caption` because it happens to use automatic leading.
- Give **all math-containing paragraphs, including prose with inline math**, enough vertical allocation using an appropriate `auto` or at-least leading policy. Inline math must retain its prose/list/table/heading/caption role, numbering, fonts and alignment; it must not become a display block just to gain height. A display-only branch is insufficient. Resolve conflicting direct exact leading where it is actually present, without indiscriminately erasing unrelated paragraph properties.
- Preserve ordinary non-math house leading, including exact 23 pt body text where safe. Do not globally relax the body style as a substitute for detecting math. Preserve native math font behavior and ordinary run/style fonts; do not rebuild OMML from flattened text or reapply body run formatting destructively to equations.
- Reuse existing style resolution and snippet override conventions. If at-least leading is selected, extend the existing rule contract deliberately (`atLeast` in OOXML, point-based value), associated regression expectations and existing documentation; `styles.py::line_spacing_attrs` currently rejects it. Automatic leading may avoid that contract extension if evidence demonstrates it is sufficient. Neither choice is a guaranteed viewer-layout fix without evidence.
- Coordinate shared edits to `SetParagraphStyle` and the house stylesheet with [the image ticket](01-inline-image-spacing.md). Preserve the dedicated image/caption distinction and the image fix rather than overwriting it.

### Non-goals and prohibited shortcuts

No bespoke equation bounding-box/metrics engine, guessed equation heights, rasterization/screenshots as equation content, manual blank/spacer paragraphs, formula rewriting, arbitrary font reduction or blanket body-style changes. Image extents do not establish equation line allocation. XML structure is useful evidence but cannot certify final rendered non-overlap.

No Word COM, `officecli refresh` or Word-backed exporter automation. Manual inspection in the intended target viewer is allowed. HTML or another non-target renderer may aid diagnosis but is not exact Word pagination proof.

## Acceptance criteria for the new session

- [ ] Capture the actual failing equation path and cause, distinguishing user evidence, synthetic reproduction and hypotheses. Record inline/display kind, native DOCX structure, effective direct/inherited spacing and the stage that introduces or exposes insufficient allocation. If the failing path remains unavailable, report that exact diagnosis limit rather than claiming the original equation complaint resolved.
- [ ] Native `m:oMath`/`m:oMathPara` remain editable; formula semantics, inline/display intent, math fonts and ordinary paragraph/run style behavior are preserved. No math is replaced by a picture or flattened text.
- [ ] Display equations have a distinct paragraph role, and every math-containing paragraph—including inline math and relevant early-branch roles—receives safe effective line allocation. Direct exact overrides cannot silently defeat the policy. Ordinary non-math leading remains unchanged.
- [ ] Verify sufficient line allocation and no overlap/clipping with surrounding content in the intended target viewer for the failing case and tall inline/display examples. Retain the visual evidence and viewer/version. If supported target-viewer verification is unavailable, explicitly report the blocker and separate structural success from unverified rendered collision behavior; do not claim Word layout verified.
- [ ] Add focused behavioral regression coverage for paragraph classification, effective spacing/direct override handling, native OMML/formula preservation and ordinary non-math controls. Cover the chosen leading-rule contract and existing style overrides; do not restrict coverage to a simplified case that bypasses the failing path.
- [ ] Run a real **draft → emitted Markdown → polish** conversion smoke with native math fixtures and the actual failing configuration. Inspect resulting DOCX XML and report commands/results and any rendering limitation. Unit construction of XML alone is not the conversion smoke. These runs belong to the new session, not this handoff.
- [ ] Preserve the image/caption fix, inline image semantics, intended dimensions/ALT, caption numbering/placement/deduplication, strategy overrides, relative image resolution and landscape behavior. Update existing relevant skill/design documentation for any new equation role or leading-rule contract and remove throwaway investigation scripts after retaining useful evidence.

## Comments

No implementation, regression tests, conversion runs or equation rendering checks were performed while authoring this ticket. `ready-for-agent` means the diagnosis is actionable, not that a root cause or fix has already been established.

## 2026-11-14 diagnosis and implementation record

### Synthetic evidence, not the original failing equation

The original failing equation source, draft/final DOCX and rendered artifact remain unavailable. The user report is not disputed, but the original formula, effective properties and Word collision mechanism cannot be recovered from the image sample. All new math cases are explicitly **synthetic**.

Pandoc 3.7.0.2 converted [source.md](../evidence/math-baseline/source.md) and [snippet.yaml](../evidence/math-baseline/snippet.yaml) into [draft.docx](../evidence/math-baseline/draft.docx), [emitted.md](../evidence/math-baseline/emitted.md) and pre-fix [final.docx](../evidence/math-baseline/final.docx). [findings.json](../evidence/math-baseline/findings.json) summarizes the observations; [commands.json](../evidence/math-baseline/commands.json) retains exact argv, cwd, exit status and output. These baseline filenames must not be mistaken for corrected artifacts.

- Source and emitted AST preserve the same ordered formulas/kinds: six InlineMath and three DisplayMath. Draft contains nine `m:oMath` and three `m:oMathPara`. Inline math lives in its actual heading, prose, list, caption or table-cell paragraph; display math is `m:oMathPara/m:oMath` in a top-level `w:p`.
- Baseline Pandoc paragraph styles and their inherited/default properties supply no fixed line rule. `SetParagraphStyle` introduces exact 23 pt (`line=460`) on the observed heading, prose, list and display equations. Display paragraphs fall through to `normal_text`, gaining justified alignment and `firstLineChars=200`; they have no display role. Table-cell math already has auto 1.5-line allocation. The [effective-property trace](../evidence/math-baseline/paragraph-property-trace.json) and [per-op trace](../evidence/math-baseline/polish-stage-trace.json) establish the introducing stage, not rendered clipping.
- Baseline `NumberCaptions` loses the native table-caption equation (9→8 `m:oMath`) and inserts literal TeX. A separate [native figure-caption probe](../evidence/math-baseline/figure-caption-source.md) reproduces 1→0 loss. CreateStyles retains 9→9 and every later operation retains 8→8. All eight surviving native-math semantic fingerprints are unchanged. This concrete caption bug requires preserving rich caption XML, not only changing leading.
- A deliberately injected exact 10 pt direct-spacing variant remains exact even when named styles are overridden to automatic 1.8 lines. The injection is documented in [direct-exact-injection.json](../evidence/math-baseline/direct-exact-injection.json); **it is not Pandoc-produced baseline spacing or an original user artifact**. It establishes why the winning direct/inherited rule must be resolved rather than assuming a named style wins.

No formula height, page-space bbox, target-viewer wrap position or clipping was measured. The fixed-allocation path and caption loss are demonstrated; attribution of the original reported Word overlap remains unconfirmed.

### Implemented polish policy

`CreateStyles` → `NumberCaptions` → `SetParagraphStyle` remains the relevant seam. A paragraph containing native `m:oMathPara` gets the dedicated `display_equation` role: centered, before 6 pt / after 6 pt, zero indentation and `atLeast` 23 pt leading by default. Inline equations retain their prose, heading, list, table-cell or caption role, numbering, alignment and ordinary typography.

A post-classification native-math pass covers all roles, including early branches. It resolves line attributes from direct `w:pPr`, the assigned style's `basedOn` chain and document defaults. A winning `exact` rule becomes `atLeast` at the **same point floor**; existing `auto` and `atLeast` allocation is retained. It modifies only the necessary line allocation and preserves unrelated direct spacing/properties. This also prevents a direct exact override from defeating a configured automatic style. Non-math paragraphs retain their established house leading, including exact 23 pt body text; no blanket body relaxation or guessed equation-height calculation is used.

Override paths are `styles.style.display_equation` and existing role styles. `line_spacing_rule` supports `auto`, `exact` and `atLeast`: `line_spacing` is a multiplier for `auto`, **points** for `exact`/`atLeast`. `reset_indentation: true` opts image/display roles into explicit zero resets of twip/character/legacy/logical indentation aliases; `left_indent_pt`/`right_indent_pt` configure point-based side indents. Zero first-line settings on existing ordinary roles do not opt into that reset.

Selected rich native captions are preserved and moved rather than recreated from flattened Markdown title text. Native OMML, hyperlinks, fields and run formatting stay in the selected paragraph while the caption label/number envelope follows the strategy formatter. Legacy-vs-native precedence, losing-caption removal and one number per selected env remain unchanged. A strategy format that rewrites/duplicates the rich title cannot safely be mapped back to its XML; it produces an explicit error instead of silent math flattening.

### Verification status

The diagnostic CLI draft/polish, emitted/source AST captures and read-only stage/property probes recorded above exited 0. These are baseline diagnosis, not post-fix tests or visual acceptance. Original acceptance checkboxes are preserved; implementation/structural results and manual rendered criteria must be judged separately.

No permitted target-viewer verification route is available here. Word remains the user's manual review surface; no Word automation or Word-backed export was used. Tall inline/display equation allocation, clipping/non-overlap, font resolution and page boundaries remain **visually unverified**. A synthetic structural pass does not close the unavailable original-equation diagnosis.

### Final exercised results — 2026-11-14

After all source/test corrections, the parent reran these real native-math conversions from `C:/Users/zhu_j/worktrees/snippet-docx-inline-object-layout` (PowerShell):

```powershell
$E = '.scratch/inline-object-layout/evidence'
uv run --project . snippet-docx draft "$E/math-baseline/source.md" --snippet "$E/math-baseline/snippet.yaml" --out "$E/math-fixed-draft.docx" --emit-md "$E/math-fixed-emitted.md"
uv run --project . snippet-docx polish "$E/math-fixed-draft.docx" --snippet "$E/math-baseline/snippet.yaml" --md "$E/math-fixed-emitted.md" --out "$E/math-fixed-final.docx"
uv run --project . snippet-docx draft "$E/math-baseline/figure-caption-source.md" --snippet "$E/math-baseline/snippet.yaml" --out "$E/figure-math-fixed-draft.docx" --emit-md "$E/figure-math-fixed-emitted.md"
uv run --project . snippet-docx polish "$E/figure-math-fixed-draft.docx" --snippet "$E/math-baseline/snippet.yaml" --md "$E/figure-math-fixed-emitted.md" --out "$E/figure-math-fixed-final.docx"
uv run --project . snippet-docx polish "$E/math-baseline/direct-exact-draft.docx" --snippet "$E/math-baseline/auto-style-override.yaml" --md "$E/math-baseline/emitted.md" --out "$E/direct-exact-fixed-final.docx"
```

All commands exited 0. Parent read-only assertions also exited 0, with persisted results in [final-smoke-verification.json](../evidence/final-smoke-verification.json):

| Output | Observed final result |
|---|---|
| [math-fixed-final.docx](../evidence/math-fixed-final.docx) | Nine native equations retained 9→9 with unchanged OMML semantics and three display wrappers. Previously exact body/heading/list/display math receives `atLeast line=460` (23 pt floor). Table-cell and table-caption math retains auto `line=360`. Plain CONTROL paragraphs stay exact 23 pt. |
| [figure-math-fixed-final.docx](../evidence/figure-math-fixed-final.docx) | Native figure-caption math retained 1→1 rather than converted to literal TeX. |
| [direct-exact-fixed-final.docx](../evidence/direct-exact-fixed-final.docx) | All nine native equations retained; deliberately injected exact 10 pt direct leading becomes `atLeast line=200`, preserving its original floor. |
| [image-fixed-final.docx](../evidence/image-fixed-final.docx) | Three drawing payloads/media unchanged, ten sample captions each exactly once, portrait → landscape → portrait section order and no nonstructural blanks. |

The parent ran `uv run pytest tests/ && uv run ruff check src tests`: **268 passed in 121.00 s**, Ruff **All checks passed!**, exit 0. Relevant final suite coverage includes inline-object layout (13), captions (71), styles (26), strategy seam (38) and landscape (16). Coverage exercises native inline/display classification and early-branch math roles, direct/inherited exact allocation, unchanged auto/at-least and non-math controls, caption OMML/rich winner preservation, object-identity provenance across captionless objects, and custom formatter/numeric-title collisions. Pure formatters may be probed to recover an unambiguous envelope, but the real-title formatter output remains authoritative; formatter call count is not a contract. Unsupported rich-title rewriting fails explicitly.

The expected read-only **red-before** assertion on preserved baseline output exited 1: native math 9→8 and exact-leading heading/body/list paths violated preservation/expandable-allocation requirements. This establishes baseline structural failure and corrected structural behavior, not a measured Word collision.

Current disposition of the preserved historical acceptance checklist:

| Criterion | Disposition |
|---|---|
| Original failing equation path/cause | **Unavailable:** no original equation source, DOCX or screenshot was supplied; synthetic findings do not substitute for it. |
| Native OMML/semantics, display role, all-role effective leading, ordinary typography | **Structurally verified** by final regression suite and real conversion assertions. |
| Focused regressions and real conversion smoke | **Passed** for the documented synthetic fixtures/configurations and injected direct-exact diagnostic; no claim of exercising an unavailable original failing configuration. |
| Image/caption/strategy/landscape preservation and documentation | **Structurally verified/documented**, with the redundant landscape-end bare spacer removed and genuine section carriers retained. |
| Sufficient rendered allocation and no clipping/non-overlap in Word | **Pending manual target-viewer verification**, including tall inline/display examples and page boundaries. No permitted rendering route exists here; no Word screenshot/PDF/refresh/page-count or automation was used. |

Implementation/structural completion does not close the unavailable original-equation diagnosis or certify Word's final line/page layout, font selection or collision behavior.
