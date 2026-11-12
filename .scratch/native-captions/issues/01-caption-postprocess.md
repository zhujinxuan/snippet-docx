# Realize native captions in polish

Type: task
Status: resolved

## Problem

The historical flag-and-strip fix blocked native table captions and implicit figure captions to avoid duplicate, unnumbered DOCX captions. The user instead approved native `Table:` / `:` titles and image ALT, with numbering and placement in polish. Pandoc transports these sources but does not implement the tool's precedence, deduplication or numbering rules.

## Approved contract

The [feature spec](../spec.md#user-confirmed-decisions) records the user-confirmed decisions: required Markdown section context (emitted recommended, raw supported), draft-only heading numbering, polish-only caption numbering/placement, legacy explicit winner with conflict warning in the same env, optional-label/stale-number normalization, per-env deduplication and one counter increment per logical caption. Existing anchors and strategy offsets/scopes/clamps/formatting remain authoritative.

## Scope

- Share caption discovery, normalization and per-env planning; realize captions in DOCX before styling/landscape passes and anchor stripping.
- Retain native/HTML-recovered table caption slots and image ALT in draft, including emitted Markdown, without expanded numbered caption paragraphs.
- Carry explicit emitted heading context; support raw Markdown without guessing from numeric heading titles.
- Preserve drawings/linked/formatted images while removing duplicate caption representations.
- Report polish findings and prevent final output on validation errors or missing Markdown context.
- Update affected callers/tests and existing user/agent docs; no implicit anchors or new configuration modes.

## Prototype evidence

**Prototype verdict (CaptionPrototype): feasible** within the approved anchored,
one-logical-caption-per-numbered-env scope. The probe establishes available
conversion data and the model demonstrates source selection; it does **not**
verify production integration, formatting-run preservation or final Word layout.

Reported by CaptionPrototype and confirmed by the integration owner:

- Branch `prototype/native-captions`, commit `1724404`.
- Interactive artifact: `src/snippet_docx/caption-prototype.html` on that branch, in worktree `C:/Users/zhu_j/worktrees/snippet-docx-native-captions-prototype`. Open in a browser; full probe inputs, AST and DOCX XML are embedded.
- Real Pandoc **3.7.0.2** parses a standalone image as `Figure.c = [attr, caption, content]`. `Table:` and `:` captions, plus HTML `<caption>`, populate `Table.c[1] = [null, [Plain …]]`.
- Its DOCX writer emits the image as `CaptionedFigure` followed by `ImageCaption`, and emits `TableCaption` before `w:tbl`. Empty ALT gives no `ImageCaption`.
- ALT survives as `wp:docPr@descr` with implicit figures enabled or disabled; disabled implicit figures produce a BodyText drawing without a visible ALT caption.
- Legacy explicit paragraphs remain separate `BodyText`: Pandoc does not deduplicate or assign tool numbering.
- CaptionPrototype exercised all six guided HTML cases in Chromium, with an empty page-error list. It observed stable 1/2 numbering, per-section reset, legacy conflict winner plus warning, stale-prefix stripping and no index for a captionless env. These are prototype checks, not production integration tests.

## Acceptance

The [feature spec acceptance](../spec.md#acceptance) governs completion. In particular, verify exactly one correctly numbered/positioned caption per env, independent repeated titles across envs, raw/emitted context parity, preserved strategy/heading/landscape behavior, usable recovered HTML captions, intact image XML, and surfaced findings with no final output on errors.

## Integration status

Implementation branch: `feat/native-captions`, worktree `C:/Users/zhu_j/worktrees/snippet-docx-native-captions`. The integration owner reported:

- Full `pytest tests/`: **211 passed in 78.08s** (`artifact://39`).
- Real CLI smoke: 10 correctly numbered captions, 8 tables and 3 drawings;
  raw/emitted `--md` parity, starts/clamping, two legacy-priority conflict
  warnings, identical titles in distinct envs, and landscape behavior checked.
  Missing `--md` exited 2 without output.
- `officecli validate` on final DOCX reported no errors. Its HTML preview was
  visually checked for caption placement, images and landscape. Exact Word
  pagination was **not** checked.
- Review corrections covered planning inside strategy continuations, raw
  inline global substitution/annotation, and native-source content eligibility.
  A previously crashing raw-global case produced `表 2.2-2 2.2数据` after
  the fix; a logo previously selected as title yielded the intended `数据`.

Final integration-owner report:

- `ruff check src tests`: **All checks passed!** Only mechanical imports and
  an unused binding changed after the full 211-pass suite; no behavior changed.
- All three review findings are fixed, with permanent regression coverage
  included in those 211 passing tests. Final production smoke and review
  probes passed after the source fixes.
- Final DOCX was revalidated by officecli with no errors; HTML preview was
  regenerated. Exact Word pagination/layout remains unverified.
- Retained source/config/PNG/final DOCX/HTML smoke artifacts:
  `C:/Users/zhu_j/worktrees/snippet-docx-native-captions-smoke`.
  Throwaway verification Python scripts are being removed by the integration
  owner; the retained sample artifacts are not production code.

Resolved on the integration owner's explicit final report. Prototype branch
`prototype/native-captions`, commit `1724404`, remains the feasibility pointer,
separate from production verification.

## Comments

- The earlier [caption-slot incident](../../caption-slot-duplicates/issues/01-table-caption-slot.md) remains historical evidence of the duplicate-caption defect; its flag-and-strip choice is superseded by this feature's user-approved native-caption contract.
- The integration owner independently opened the captured prototype HTML in Chromium and exercised free-play controls: native `机位布置` plus legacy `图 8.8-9 保留旧图题` produced exactly one `图 2.2.3-1 保留旧图题` below the image, with a visible conflict warning. Browser errors were empty and a screenshot was captured. This confirms prototype interaction only; production smoke/tests were still pending in that report.
