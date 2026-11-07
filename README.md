# Scriptty

Passive workflow documents over explicit Python pipelines. Python 3.11+.

```python
from scriptty import load
workflow = load("examples/text.json")
metadata = workflow.inspect()
bound = workflow.bind(selected_catalog, catalog_version="text-v1")
result = bound.run({"text": " Hello WORLD "})
```

The host supplies a Hidden Moves CapabilityCatalog. Parsing never discovers or
imports providers, evaluates code or invokes operations. JSON and TOML share the
same strict schema-1 model; see [examples](examples/text.toml). A document contains
schema, name, version, steps and outputs. Steps contain id, capability and arguments.
Expressions carry exactly one tag:

| Tag | Payload |
| --- | --- |
| `value` | Literal finite JSON, including reference-shaped records |
| `input` | `{name, path?}` selecting run inputs |
| `ref` | `{step, path?}` selecting an earlier step |
| `object` | Object mapping field names to expressions |
| `array` | Array of expressions |

Paths contain string keys or nonnegative integer indexes. All IDs, shapes,
references and document keys/versions are checked passively. Binding validates
selection and known literal argument shapes. Run preflight validates known input
values; producer-dependent paths/values are checked before their consumer runs.
Errors include source and structural step/expression location; JSON syntax errors
include line/column. TOML syntax diagnostics come from the standard library.

Documents are bounded to 1 MiB and JSON depth 32, with at most 256 steps and paths
of at most 32 segments. Duplicate keys, non-finite values, invalid UTF-8, unknown
tags/keys/versions and TOML dates are rejected. No new grammar is introduced.
Schema 1 is stable for this source line: incompatible definition changes require a
new schema number; unknown fields are rejected instead of silently changing meaning.
No terminal, stdin or signal behavior is installed by library imports.

The independently versioned source profile pins moveset and its selected siblings.
Build with `uv build --out-dir dist`; `python scripts/qualify.py dist` qualifies both
installed artifacts outside the source tree. Publication and released dependency
requirements are separate [Project tasks](https://github.com/orgs/wispsy/projects/23).
