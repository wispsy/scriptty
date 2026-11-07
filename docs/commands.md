# Workflow commands

Install the `cli` profile. Use `cli,sequence` on Python 3.14+ for durable execution.
The host explicitly installs trusted providers; documents never select imports.

```sh
scriptty inspect examples/text.json
scriptty list --provider wispsy-reference --select text.normalize --select text.report --catalog-version text-v1
scriptty run examples/text.json --inputs inputs.json --provider wispsy-reference --select text.normalize --select text.report --catalog-version text-v1
```

The example uses the provider advertised by the separately installed Wispsy
reference distribution. `inputs.json` is a strict versioned envelope:
`{"schema":1,"inputs":{"text":" Hello WORLD "}}`.
Provider names must each resolve to exactly one installed Hidden Moves entry point.
Loading providers executes trusted Python. Exact capability selection determines
the exposed catalog. Catalog version is host-selected definition identity and
must change when callable behavior/resources/configuration change.

Add `--checkpoint progress.json --pace function` to run one boundary, then use
`scriptty resume` with the same file, inputs and selection. Run requires a new
checkpoint path; resume requires existing progress. `resume --retry` repeats an
uncertain step; `resume --restart` repeats the workflow. These retain func_seq's
explicit uncertainty contract; no automatic retry or rollback is implied.

Successful outcomes use schema 1 with status, fingerprint, completed IDs, results,
outputs and run_id (null for ordinary execution). Paused outputs are null. Changed
definition/input/mapping/catalog identities reject old progress. Diagnostics go to
stderr; the final JSON result is UTF-8 stdout independent of console encoding.
Failures use a final schema-1 JSON stderr line and nonzero status (2 for CLI usage,
1 for application errors). Provider/capability print output is diagnostic only.
Help is rendered on stderr. Outcomes use the same 1 MiB finite JSON transport limit.

Library hosts use `scriptty.application.execute` with a Workflow, selected catalog
and explicit inputs. It installs no stdin reader, signals or terminal session.
The optional terminal frontend can pass func_seq Control/observer without owning
another executor. Hidden Moves' own CLI migration remains
[expose_interface#8](https://github.com/wispsy/expose_interface/issues/8); these
commands adopt Expose Interface directly and do not duplicate that migration.
