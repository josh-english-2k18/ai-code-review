# Review design

Reviewers operate with incomplete knowledge of the intended system. A change proposed to satisfy a reviewer can silently remove behavior that the author meant to preserve. This can compound across rounds. The review workflow treats a finding as a challenge the author can verify and adjudicate.

See the [README](../README.md) for installation and command examples.

## Git scope

`GitOps` resolves the worktree root from the supplied path. All three review commands (`prompt`, `changes`, and `packet`) use the same comparison rules.

- **Working tree.** Git compares the net staged and unstaged state with HEAD. A repository before its first commit uses the empty tree. Untracked paths come from Git's nonignored inventory when requested. The brief records the baseline and tells the reviewer to recheck the live state.
- **Branch comparison.** With `--base`, both refs resolve to commits. Git compares their merge base with the reviewed head, which defaults to HEAD unless supplied explicitly. The brief pins both endpoints and gives commands for reading files and history at those revisions, even when the current checkout is elsewhere.

## Review brief

Plain `prompt` reads Git name-and-status metadata. It builds a preview of up to 20 changed paths with a 2,000-character row budget. For larger changes, the preview prioritizes some changed tests and docs and samples across directories before filling the remaining places. The brief includes commands for finding omitted paths and inspecting the diff and history.

The reviewer reads focused diffs and checks relevant callers, interfaces, baseline tests, and docs. Optional `--intent` notes supply author context. Each `--context-file` points to a regular file inside the repository, validated against the worktree or pinned head. The reviewer reads these files in place.

The prompt asks an independent reviewer to prepare falsifiable challenges for the author who implemented the change. The reviewer investigates behavior and intent separately and tries to disprove both before reporting a candidate. The Markdown report records the evidence, the attempted disproof, and a way for the author to test both claims. The author verifies or rejects the challenge against the implementation and intended behavior, then chooses how to respond.

`synthesize-prompt` reads regular `*.md` files directly inside the supplied directory and builds a brief for a subsequent agent. That brief asks the agent to combine equivalent challenges only when they concern the same behavior and review target, retain independent checks, and surface unresolved disagreements. Matching HEAD commits alone leave the working-tree state uncertain.

## Supplemental material

`changes` and `packet` use one Git comparison for tracked status, counts, and patch text. Git emits NUL-delimited path metadata to preserve unusual filenames. The file summary covers the scoped changes. Binary files and unreadable or oversized untracked files can have unavailable line counts. The source excerpt is bounded separately.

| Material | Default limit |
| --- | --- |
| Patch preview | 4,000 lines and 250,000 characters before annotation. `--max-diff-lines` sets the line limit. |
| Hunk index | 100 entries. |
| Untracked text preview | 400 lines per file, with a 1,000,000-byte per-file limit. |
| Packet structural context | 40 files with rendered summaries. |
| Downstream impact in working-tree packets | Up to two levels of inferred dependents, with the first 25 displayed per changed path. |

`packet` adds structural summaries, inferred impact where available, and heuristic signals such as changed tests or sensitive paths. `prompt --with-packet` attaches this material to the review brief. Chunking repeats the brief for each excerpt and uses an approximate character budget. It splits at line boundaries and preserves the diff fence across chunks.

With `--chunked --output`, an existing directory or a path without an extension receives `chunk.01.md`, `chunk.02.md`, and so on. A file-style path such as `review.md` sets the prefix for sibling files such as `review.01.md`. Without `--output`, chunks go to stdout, separated by dividers or terminated by NUL with `--chunk-separator nul`.

## Structural analysis and cache

`analyze` uses Git's tracked paths in a checkout and walks a plain directory outside a checkout. It summarizes supported regular files from the current filesystem. Working-tree packets can also analyze included untracked files. Their dependency graph estimates downstream impact from imports. Branch packets read changed structures from the pinned head. The brief directs branch reviewers to inspect downstream consumers in the repository.

The analyzer cache lives at `.ai_review/cache/analysis.json` under the analysis root. Entries are keyed by path and checked against the analyzer, cache format, and source content. Incremental runs reuse matching entries and skip a cache write when its contents match. Writes replace the cache atomically. `--full` rebuilds summaries, and `--read-only` bypasses cache reads and writes.

## Path filtering and redaction

The CLI filters common sensitive paths such as `.env` and `.env.*`, `credentials`, `secrets.json`, and `.pem` and `.key` files. It also filters generated directories and checks both paths in Git rename and copy records. When Git reports separate additions and deletions, the path filter evaluates each entry on its own.

Best-effort redaction runs on rendered source excerpts and summaries. Author notes, synthesis inputs, and diffs of recognized text formats mask bare values of at least eight characters in recognized credential assignments, including letter-only values. Source diffs preserve recognizable code references. Diff redaction preserves path metadata, patch prefixes, and citation ranges.

Private-key handling is scoped to individual diff hunks and treats old and new sides separately when needed. An unmatched banner in prose only masks adjacent lines that look like key payload. Direct checkout access follows the reviewing agent's tool permissions.
