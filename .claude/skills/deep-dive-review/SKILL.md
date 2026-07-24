---
name: deep-dive-review
description: Conduct a thorough, adversarial, source-grounded code review aimed at correctness, robustness, and production-readiness — pairing an independent fresh-context reviewer subagent with live verification against real sources, then reconciling the two before any finding stands. Use this whenever the user asks for a deep-dive, adversarial, second-pass, or "go deeper" review, an audit, or a correctness/robustness/thread-safety pass — especially on genome-dl (the Datasets v2 + FTP downloader) but applicable to any tool with live external dependencies. Trigger even when the user just says "review this hard", "poke holes in it", or "is this production-ready?".
---

# Deep-Dive Review

A review process for finding the bugs a surface review misses: concurrency and
thread-safety, API-contract drift, retry/backoff and partial-failure handling,
metadata fidelity, input safety, and behavior at scale. It works because it
never trusts a single source of truth — an independent reviewer and live
verification each check the other, and the human decides scope before any code
changes.

For genome-dl's current state (prior review rounds, deferred items, exit-code
contract, how to verify against live NCBI), read
`references/genome-dl-context.md` first. Keep that file updated at the end of
each round so the next reviewer starts grounded and never re-litigates settled
findings.

## Why this shape

A lone reviewer — human or model — anchors on its first read and misses things.
Two independent passes that must agree catch far more, and disagreements are
where the real bugs hide. In the last genome-dl round the independent reviewer
both *missed* a genuine HIGH bug (a multi-value filter that the REST API rejects
with HTTP 400) and *overstated* a LOW one (a null-field crash it claimed happened
"routinely" but that live probing could not reproduce). Live verification
resolved both. That is the whole point: **live sources are the tiebreaker.**

## Process

### 1. Ground yourself (do this yourself, do not delegate)

Read the target modules end to end — sections, not snippets — plus tests,
constants, and the exception hierarchy. Read `memory://root` and the project
context reference. You own the scope and the top-level decomposition; a generic
"go plan this" subagent as step one knows less than you and adds latency for zero
parallelism.

### 2. Fan out: independent reviewer + your own live verification (same turn)

Spawn a fresh-context `code-reviewer` subagent with the focus areas below and the
explicit rule: ground every finding in file:line, be adversarial, and do not
re-report already-fixed bugs (list them). In parallel, start your own
verification against **live sources** — for genome-dl that means real calls to
the NCBI Datasets v2 REST API and `ftp.ncbi.nlm.nih.gov`. Do not sit idle behind
the subagent; the two streams run concurrently.

### 3. Verify every disputed or load-bearing claim against reality

Never let a claim stand that a quick live call can settle. Reproduce the failure
if you can (a curl, an API request, running the actual code path). A finding that
survives both the code and a live probe is real; one that a live probe refutes is
downgraded or dropped, no matter how confident the reviewer sounded.

### 4. Reconcile as advisor

Merge your findings with the reviewer's. For each: assign severity
(critical/high/medium/low), cite exact file:line, describe the concrete failure
scenario, and give a fix direction. Explicitly separate genuine bugs from
nitpicks, and correct the reviewer where live evidence disagrees. A conclusion
stands only after this cross-check.

### 5. Present findings and confirm scope — before writing any code

Deliver a prioritized report. State plainly which findings you think are worth
fixing versus leaving, and why. Then confirm scope with the user (an `ask` with
grouped options works well) and surface any design decisions a fix implies (e.g.
the partial-success vs rollback contract). Ask questions when uncertain. Do not
start editing until scope is confirmed.

### 6. On approved fixes: implement, prove, clean up

Fix at the source; migrate all callsites; no shims. Add a regression test per
fix that fails on the real bug and defends an observable contract. Then verify:
`just check` (or the project's lint+format), `just test-cov` (coverage gate),
`just test-integration` where it exercises the change, and a real smoke test of
the changed path (run the thing, not just a test file). Regenerate context files
with the `update-catalog` skill after changing modules/functions/CLI/constants/
exceptions.

### 7. Close the loop

Update `references/genome-dl-context.md` with the round's outcome (what was fixed,
commit hash, what was deliberately left) so the next review builds on it.

## Focus areas (push hard where a surface review is thin)

- **Concurrency / thread-safety:** shared sessions across workers, thread-pool +
  KeyboardInterrupt handling, atomic temp-file rename under races, partial-file
  cleanup, orphaned files on partial success.
- **API contract drift:** version/status selection, suppressed/superseded/
  replaced/notfound edges, pagination, and behavior when the response shape
  changes or fields are missing/null (probe live — do keys go absent or null?).
- **Transport robustness:** directory/path resolution and fallbacks, checksum
  manifest edge cases, formats legitimately absent, retry/backoff (including
  errors the HTTP adapter does *not* cover, like mid-body stream drops),
  truncated/corrupt downloads, HTTP error pages saved as data.
- **Metadata fidelity:** does the output faithfully reflect the source record
  across assemblies with unusual/missing fields?
- **Input handling & safety:** accession/ID parsing, list-file quirks, taxon/name
  handling, path handling (prefix traversal), anything untrusted.
- **Performance at scale:** large input lists (request batching), large taxa
  (full pagination + memory before subsetting).
- **Test & integration coverage:** where are the real gaps? Are the live
  integration tests adequate and actually exercised?

## Verification environment (genome-dl)

Activate the `genome-dl` conda env first (has pytest, ruff, just). Recipes:
`just fmt`, `just check`, `just test`, `just test-cov`, `just test-integration`.
Integration tests are deselected by default and hit live NCBI. Use `curl`/Python
against `https://api.ncbi.nlm.nih.gov/datasets/v2` and
`https://ftp.ncbi.nlm.nih.gov/genomes` to settle contract questions directly.
