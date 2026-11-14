# Inline image spacing at table boundaries

Status: implementation and structural verification complete; manual Word table/image/caption layout verification pending.

Original handoff scope (preserved): actionable diagnosis and implementation in a **new session**; the original sections contain proposals, not an implemented fix. Follow [the shared spec](../spec.md) for workspace, shared-file ownership, preservation rules and verification limits. Current findings are appended below.

## User-visible complaint

The user reports that an image overlaps the preceding table. In the supplied screenshot, the first figure's pale background begins at the bottom edge of the preceding table, with no visible separating gap; the table's lower border is not visible through the image-width region. The figure caption remains below the image. Treat the user's overlap observation as ground truth, but do not infer final object bounding boxes or a proven rendering mechanism from this screenshot alone.

The requested outcome is a visibly separated table → image → caption sequence, without resizing the image, making it floating, or inserting empty spacer paragraphs.

## Evidence and provenance

All evidence links are relative to this ticket:

- [reported-overlap.png](../evidence/reported-overlap.png): the user's screenshot of the **original `final.docx`**, showing the first table/figure boundary and the caption `图 2.2-4 场区布置`. This is the reported visual failure, not a screenshot of the regenerated structural reference.
- [source.md](../evidence/source.md): preserved sample input. Lines 5–20 place a native-captioned table immediately before a figure whose image is `![图 9.9-7 场区布置](layout.png){width=10cm}`. It also contains native/legacy caption conflicts, separate repeated captions and a landscape region with a hyperlink-wrapped image (lines 94–112).
- [snippet.yaml](../evidence/snippet.yaml): preserved `ecepdi` configuration, section prefix `[2, 2]`, table start `2`, figure start `4` and caption depth `3`.
- [layout.png](../evidence/layout.png): preserved source image used by the sample.
- [reported-final.docx](../evidence/reported-final.docx): snapshot of `C:/Users/zhu_j/worktrees/snippet-docx-native-captions-smoke/final.docx` captured during handoff from the original report path. Its bytes are **not guaranteed to match the screenshot-time document**. Use it for comparison without replacing the screenshot as ground truth.
- [main-final.docx](../evidence/main-final.docx): output previously generated from the same sample with merged main (`b891489`). It is a separate **XML/structure reference**, not a claim that Word renders it identically to the screenshot or the original report-path snapshot.

The sample's intentional conflicting-caption and captionless-table warnings are unrelated to this spacing complaint; retain their established behavior.

## Observed XML and style facts

Prior inspection of `main-final.docx` established:

- The drawings use `wp:inline`; no `wp:anchor` was present. No floating tables were present.
- The inspected image has `wp:extent cx="3599999" cy="1349999"`; its `a:xfrm/a:ext` has the same dimensions, approximately **10 × 3.75 cm**. The intended image dimensions survived conversion.
- The image paragraph has `w:pStyle w:val="figure_caption"` and no direct paragraph spacing override.
- Its `figure_caption` style has `w:spacing w:before="0" w:after="100" w:line="360" w:lineRule="auto"`: **0 pt before, 5 pt after, automatic 1.5-line leading**. This is not an exact-height image paragraph.

These are structural observations from the regenerated reference, not measured final page-space positions in the failing document. They do not establish actual bbox intersection or prove that enlarging a drawing extent would change paragraph allocation correctly.

Relevant current source:

- `src/snippet_docx/ops_docx.py::SetParagraphStyle` (especially lines 210–215) finds descendant `w:drawing` or `w:pict` in a paragraph with no non-whitespace `w:t` text and assigns **`figure_caption`**. Image paragraphs and actual caption paragraphs therefore share a role/style. Its docstring explicitly describes using automatic leading to avoid exact-height clipping.
- `src/snippet_docx/ops_docx.py::CreateStyles` builds the resolved named paragraph styles before assignment; caption-specific paths in `SetParagraphStyle` must remain distinct from the image path.
- `styles/ecepdi-default.yaml::style.figure_caption` defines centered, zero-first-line-indent text with before `0`, after `5`, line spacing `1.5` and rule `auto` (lines 123–135). `style.table_caption` independently has before `5`, after `0` (lines 108–121).
- `styles/ecepdi-default.yaml::style.normal_text` defines exact `23` pt leading (lines 95–106). That body setting is **not** evidence that this image paragraph currently has exact leading.
- `src/snippet_docx/styles.py::resolve_styles`, `line_spacing_attrs`, `_build_ppr` and `define_paragraph_style` are the existing merged-style/OOXML construction seam. `_build_ppr` emits spacing and alignment; it emits first-line indentation only when positive, so inspect inheritance/direct properties when establishing a truly indent-free image role.

## Working hypothesis, not established cause

Reusing a caption style gives the image **zero space before**. At an immediately preceding table boundary this may leave no visible separation, producing the reported collision or border occlusion. The same reuse also couples image-to-caption spacing to caption typography and user caption overrides.

This missing-gap hypothesis is not proof of actual bbox overlap, and the reference already uses automatic leading. Diagnose effective paragraph/table properties and target-viewer layout before attributing the symptom to clipping, exact leading, corrupted dimensions or floating objects. Object extents are not final page-space bboxes.

## Proposed implementation seam and diagnosis

1. Use the preserved source/configuration for the table → first image → caption boundary. Inspect effective properties and block order in draft and polished XML, including table positioning, direct/style-inherited paragraph spacing and indentation, and any context/page-boundary rules that affect the gap. Compare this with the original screenshot without claiming an identical rendered baseline from `main-final.docx`.
2. Fix in **DOCX polish** through the existing style creation/assignment seam if Pandoc preserves the required image structure, dimensions and metadata. Move upstream only if concrete draft evidence demonstrates corruption or loss of necessary information; record that evidence and the actual cause.
3. Introduce a dedicated image paragraph role/style (proposed name: `figure_image`) rather than assigning image-only paragraphs to `figure_caption`. Starting proposal: **6 pt before**, centered, no first-line/left/right indentation, automatic leading (retain the existing `1.5` multiplier initially), and **5 pt after** as an initial image-to-caption gap. Validate these starting values in the target viewer, especially immediately after a table; do not assume `before=6` alone guarantees the rendered gap.
4. Keep actual figure caption spacing independent. Initially retain `figure_caption` before `0` / after `5` and existing typography, numbering and placement; changing a caption style must not silently change image paragraph allocation. Use existing named-style defaults/overrides rather than a parallel hardcoded formatting mechanism.
5. Change paragraph properties without rebuilding image runs. Preserve `wp:inline`, both existing extent representations, aspect ratio, ALT/accessibility text, media relationships, hyperlink wrappers and run formatting. The sample's hyperlink-wrapped landscape figure must still be detected and styled. Preserve ordinary body paragraphs, landscape section boundaries and caption strategies/deduplication.

Do **not** change image extents to create a gap, shrink images, add blank paragraphs, or convert them to floating objects. Apply the remaining shared constraints in the spec rather than treating this proposal as permission to alter other layout behavior.

## Acceptance criteria

- The actual diagnosed cause and chosen polish change are recorded, with any difference from the hypothesis explained. No statement claims that the regenerated reference proves the original Word-rendered cause.
- At the **original first table → image boundary**, the table's complete lower border and the image are visibly separate in the target viewer; neither occludes the other. Capture a before/after comparison against the reported screenshot where available, and identify the exact output and viewer/version used.
- The **image → caption boundary** has a deliberate, readable gap with no collision. The caption remains below its image, and its spacing/typography can be controlled independently of the image role. Check both captioned and captionless image paragraphs without introducing empty spacers.
- Structural regression coverage verifies that configured paragraph separation reaches the output, image and caption layout can be controlled independently, and effective image leading can grow rather than clipping to an exact height. It verifies centered, effectively indent-free image paragraphs while distinguishing actual captions and ordinary text, including hyperlink-wrapped/formatted images and style overrides. Preserve image geometry; do not pin the proposed style name or initial 6 pt trial value as an incidental permanent test requirement.
- Regression coverage verifies preserved inline drawings, unchanged `wp:extent` and `a:xfrm/a:ext`, ALT/accessibility data, image relationships and link/run formatting. No new floating drawings or spacer paragraphs are introduced. Caption numbering, placement, per-env deduplication/overrides and the sample's landscape figure/section behavior remain intact.
- In the implementation session, run focused structural regressions and a real sample **draft → polish** smoke conversion, then record results and relevant generated artifacts. Update existing style/skill documentation for the new role and its override contract as required by the shared spec.
- Provide **target-viewer visual evidence** for table/image separation and image/caption separation, including the linked landscape case and relevant page boundaries. XML assertions alone do not establish rendered non-overlap. If supported target-viewer inspection is unavailable, state that limit explicitly and do not claim the Word layout is verified. HTML or another non-Word rendering may aid diagnosis but is **not exact Word layout/pagination proof**; use only the verification methods permitted by the shared spec.

## Comments

- Handoff only: no production code, tests or styles changed and no conversion runs performed as part of authoring this ticket. Proposed values and root-cause explanations require diagnosis in the new session.

## 2026-11-14 diagnosis and implementation record

### Observed cause and limits

A real conversion of the preserved sample with Pandoc 3.7.0.2 produced `../evidence/image-baseline-draft.docx`, `image-baseline-anchored.md` and `image-baseline-final.docx`. These are **pre-fix diagnostic outputs**, separate from the preserved screenshot and `reported-final.docx`; they do not reproduce the screenshot-time Word rendering.

The first and linked-landscape image paragraphs immediately follow their respective tables and use `figure_caption`. Effective image spacing is before 0 pt / after 5 pt / automatic 1.5 lines, with no direct spacing override. The Normal style's paragraph properties are empty; document defaults contribute only after 200 twips. No floating tables were found. Both extent forms remain 3599999 × 1349999 EMU and the inline drawing, ALT and media survive. This establishes coupled image/caption roles and missing configured pre-image separation. **It does not establish the exact rendering mechanism or page-space bbox collision behind the user's screenshot.** In particular, the image baseline does not have exact-height leading.

### Implemented polish contract

The shared style creation/paragraph-assignment seam gains a distinct `figure_image` role for image-only paragraphs, including descendant drawings in hyperlink/formatted runs. Its default is centered, before 6 pt / after 5 pt, automatic 1.5-line leading and explicit zero indentation. This separates image allocation from `figure_caption`, whose default remains before 0 pt / after 5 pt with its existing typography.

Overrides use `styles.style.figure_image` independently of `styles.style.figure_caption`. `reset_indentation: true` opts the image/display roles into explicit resets, including inherited twip/character and legacy/logical indentation aliases; `left_indent_pt` and `right_indent_pt` configure point-based side indents. Existing ordinary styles that merely specify a zero first-line indent retain their established behavior. An exact winning line rule on an image-only paragraph is relaxed to `atLeast` at the same point floor so direct or inherited exact leading cannot impose a fixed-height image line. Before/after separation is controlled through the resolved role style, not blank spacers or image geometry.

The safe-leading pass also covers images in mixed-content paragraphs without reclassifying their ordinary role. For object-role paragraphs, configured alignment/indentation is applied directly to defeat conflicting direct indents, while existing direct before/after and unrelated paragraph properties are preserved and win normally.

Image runs are retained rather than reconstructed. This contract preserves inline drawings, geometry/aspect ratio, ALT/accessibility data, relationships, hyperlink/run content, caption placement/numbering and landscape sections. The initial 6 pt separation is a deliberate default, **not a guarantee of Word non-overlap at every table/page boundary**.

### Verification status

Implementation and structural checks are tracked separately from rendered acceptance. The original target-viewer criteria above remain open: no permitted Word/non-COM target-viewer route is available in this environment. No screenshot of corrected Word output, lower-border separation guarantee, image/caption visual pass or linked-landscape visual pass is claimed.

### Final exercised results — 2026-11-14

The parent reran the preserved sample through real draft → emitted Markdown → polish after all fixes, using Pandoc 3.7.0.2. Commands, run from `C:/Users/zhu_j/worktrees/snippet-docx-inline-object-layout` (PowerShell):

```powershell
$E = '.scratch/inline-object-layout/evidence'
uv run --project . snippet-docx draft "$E/source.md" --snippet "$E/snippet.yaml" --out "$E/image-fixed-draft.docx" --emit-md "$E/image-fixed-anchored.md"
uv run --project . snippet-docx polish "$E/image-fixed-draft.docx" --snippet "$E/snippet.yaml" --md "$E/image-fixed-anchored.md" --out "$E/image-fixed-final.docx"
```

Both commands exited 0. [image-fixed-final.docx](../evidence/image-fixed-final.docx) is the corrected structural output, not a replacement for the original screenshot or historical report-path snapshot. Parent read-only assertions exited 0 and are retained in [final-smoke-verification.json](../evidence/final-smoke-verification.json):

- All three drawing payloads and media are identical to draft, including inline geometry, ALT and linked/formatted image content.
- Image paragraphs have before 120 twips (6 pt), after 100 twips (5 pt), auto `line=360` (1.5 lines) and zero indentation; figure captions remain independently styled.
- All ten sample captions appear exactly once. Section order remains portrait → landscape → portrait, including the linked landscape figure. There are no nonstructural blank spacers.
- `InsertSectionBreak` no longer adds a redundant bare paragraph after the landscape end anchor; genuine section-close carriers, including the table-only landscape case, are retained. This does not change image geometry or use empty paragraphs for separation.

The parent also ran `uv run pytest tests/ && uv run ruff check src tests`: **268 passed in 121.00 s**, Ruff **All checks passed!**, exit 0. Relevant final suite coverage includes 13 inline-object layout cases, 71 caption cases, 26 style cases, 38 strategy-seam cases and 16 landscape cases. Tests cover independent overrides, effective direct/inherited exact→at-least allocation, object indentation including conflicting hanging aliases, inline drawing/ALT/relationship preservation, native caption identity/numbering, and no-spacer/section behavior. These module counts are part of the final suite, not a claim that each module was rerun separately.

**Disposition:** polish implementation, structural regressions and real conversion smoke are verified. The original Word-rendered mechanism remains unconfirmed. Visual acceptance for the original first table border/image boundary, image/caption gap, linked landscape figure and relevant page boundaries is **pending manual target-viewer inspection**. No Word screenshot, PDF, refresh, page-count or automation was performed; XML success does not establish rendered separation.

### Subsequent review clarification — 2026-11-14

The user supplied [another boundary screenshot](../evidence/reviewed-table-image-boundary.png), then clarified that it came from a **draft DOCX viewed in WPS Writer**. It does not demonstrate failure of the polished output's configured gap.

Read-only inspection of the retained sample artifacts exited 0: `image-fixed-draft.docx` uses `CaptionedFigure` → `Figure` → `Normal`, with no spacing on those styles; `image-fixed-final.docx` uses `figure_image`, with before 120 twips / after 100 twips / automatic line 360. Neither image paragraph has direct spacing. This is the expected draft-versus-polish distinction, not an established WPS suppression defect.

No additional production change, spacing increase, new regression test or conversion rerun was warranted. The previously exercised 268-test/Ruff and smoke results remain applicable because source and conversion inputs were unchanged. [Primary-source research](../evidence/table-image-boundary-research.md) is retained as conditional background, not proof of a final-output rendering defect. Review `image-fixed-final.docx` in WPS for the still-pending visual acceptance; no new target-viewer pass is claimed.
