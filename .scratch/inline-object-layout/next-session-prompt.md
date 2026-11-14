Fix inline-image and native-equation overlap/layout problems in snippet-docx.

Use the already prepared worktree:
- Path: C:/Users/zhu_j/worktrees/snippet-docx-inline-object-layout
- Branch: fix/inline-object-layout
- Starting main commit: b891489 (native-caption feature already merged).

Work only there, not on the canonical main worktree. Preserve the existing uncommitted handoff documents and evidence; they are intentional. Do not reset/clean the worktree or recreate it over those files.

Read .scratch/inline-object-layout/spec.md and both tickets under its issues/ directory before implementation. Read the applicable snippet-docx, diagnosing-bugs and docx-workflow skills and the existing ToolSpec. Inspect the preserved evidence/ artifacts.

Implement both tickets:
1. Diagnose the reported table/image boundary collision. Keep images INLINE with their intended dimensions and ALT. The drawing extents were preserved; sharing figure_caption style with image paragraphs and zero preceding space are observed facts, while the precise Word rendering cause is unconfirmed. A dedicated image paragraph style with explicit separation is the proposed fix, not permission to skip diagnosis.
2. Investigate the equation-overlap report with actual inline and display math conversions. No equation-bearing failing artifact was inspected previously. Exact 23 pt normal_text leading is a hypothesis to investigate, not an established cause. Keep equations native/editable OMML and handle both display equations and text paragraphs containing inline equations.

Prefer the existing DOCX polish seam if Pandoc preserves the necessary data. Keep caption numbering/deduplication, strategy overrides, image sizing, landscape behavior and ordinary non-math typography intact. Follow the tickets' constraints; do not replace objects with raster images, add blank-paragraph spacers or build an equation bbox engine.

Assign one owner to shared paragraph-style/polish edits; independent reproduction work can run in parallel. Add focused consumer-visible regressions and run actual draft -> polish smoke scenarios, not just XML checks. Use the supplied screenshot as the reported failure, not a request for the user to repeat it.

Verify rendered separation in the target viewer where available. No Word COM, officecli refresh or unverified Word-backed exporter automation. XML/HTML checks do not prove exact Word layout; explicitly report any remaining target-viewer verification limit rather than claiming full visual success.

Update the tickets and existing documentation with actual findings and results. Deliver the changed files, exercised commands/results and sample DOCX paths. Keep the work on this branch; do not merge or push unless asked.
