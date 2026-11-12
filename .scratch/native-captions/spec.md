# Native Markdown captions

Status: resolved; implemented and verified by the integration owner.

## Goal

Author table captions as Pandoc Markdown `Table: 标题` / `: 标题`, and figure captions as standalone image ALT, `![标题](image.png)`, inside the existing anchor envs. Draft retains those sources; polish supplies house labels, numbers and placement. No manually typed `表` / `图` label or number is needed.

This replaces the earlier flag-and-strip policy in [the caption-slot incident](../caption-slot-duplicates/issues/01-table-caption-slot.md); that record describes the historical implementation, not the new contract. The table header row remains column headings, not a caption. ALT-as-caption is a Pandoc dialect behavior, not a universal Markdown rule.

## User-confirmed decisions

- Keep existing anchor grammar; do not implicitly wrap tables/images.
- Draft bakes heading numbers only. Polish numbers and positions captions.
- Require `polish --md` for section context. Emitted Markdown is recommended; raw source is supported. `--emit-md` preserves native/ALT captions rather than expanding standalone numbered caption paragraphs.
- Preserve explicit heading context in emitted Markdown, so polish does not infer section paths from numeric-looking titles or transform heading levels twice.
- Keep legacy explicit `表 标题` / `图 标题` paragraphs. Within the same env the explicit legacy paragraph wins over native/ALT, even with different wording; warn on conflict.
- Normalize optional labels and stale numbers from both sources. An empty native title can fall back to a usable legacy paragraph; otherwise retain the captionless-env warning.
- Deduplicate within an env only, never globally by title. Exactly one counter increment per logical numbered caption; repeated titles in separate envs remain separate captions.
- Preserve numbering offsets, counter scopes, prefix clamping and custom `EnvSpec` / `format_caption` behavior. ecepdi places table captions above and figure captions below.
- Preserve image drawings/XML, including linked/formatted images and ALT beginning `图`; retain usable HTML-recovered table caption slots.
- Surface polish findings at the CLI. Missing Markdown context and validation errors prevent final output. No new modes, retries, telemetry or unrelated behavior.

## Implementation contract

A shared `captions.py` owns source discovery, title normalization and per-env plans. DOCX `NumberCaptions` realizes those plans before paragraph styling and landscape section breaks; the Markdown-side caption-numbering op is removed. The internal `snippet-docx-section` heading attribute carries emitted section paths; raw Markdown uses the heading walker. DOCX ops may return findings, and polish collects them before deciding whether to save.

The maintained pipeline, strategy invariants and decision register are in [ToolSpec](../../references/ToolSpec.md). The implementation ticket is [01-caption-postprocess](issues/01-caption-postprocess.md).

## Prototype and evidence

Prototype branch: `prototype/native-captions` (separate from implementation branch `feat/native-captions`). Evidence and the prototype verdict are recorded in the ticket from CaptionPrototype's actual report; prototype feasibility does not establish integrated implementation correctness.

## Acceptance

- Native table and ALT-only figure captions become exactly one correctly numbered, positioned final caption per env; draft/emitted Markdown does not expand numbered captions.
- Legacy-only and mixed-source envs follow the precedence, normalization and warning rules above, without global title deduplication.
- Emitted and raw Markdown both supply correct section paths; offsets, depth clamps, scopes, custom formatting and heading/landscape behavior remain intact.
- Recovered HTML captions remain usable, image XML survives, and findings/errors reach the CLI with no final output on errors.
- User/agent docs describe the same contract. Integration verification and final ticket status are recorded only after the integration owner reports actual results.

## Outcome

The integration owner reported 211 passing tests, clean `ruff check src tests`,
successful production CLI smoke/review probes, and final DOCX validation with
no errors. The final HTML preview was regenerated and checked for caption
positions, images and landscape; exact Word pagination/layout was not
verified. Full evidence, regression fixes and retained smoke-artifact pointers
are in the [resolved implementation ticket](issues/01-caption-postprocess.md#integration-status).
The prototype remains separately traceable at `prototype/native-captions`,
commit `1724404`.
