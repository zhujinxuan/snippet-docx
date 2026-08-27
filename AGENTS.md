# snippet-docx skill

Standalone global skill: convert a markdown snippet into a house-standard DOCX
(ecepdi default; pluggable strategies). Origin: jz-toolshed `tools/snippet-docx`
(frozen); this skill dir is the canonical working home. See `SKILL.md` for usage
and `references/ToolSpec.md` for the settled design.

## Agent skills

### Issue tracker

Issues and specs live as markdown files under `.scratch/<feature-slug>/` (one `spec.md` + `issues/NN-<slug>.md` tickets). See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root (created lazily). See `docs/agents/domain.md`.
