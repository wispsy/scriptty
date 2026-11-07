"""Explicit trusted provider selection and Expose Interface presentation."""

import contextlib
from pathlib import Path
import sys

from expose_interface import Interface, UsageError, option
from hidden_moves import Moves, discover_providers, load_provider
from hidden_moves.adapters import CapabilityCatalog
from moveset.core import MAX_BYTES, _schema_json, canonical

from .application import execute
from .documents import decode_json, load


def selected_catalog(providers: list[str], names: list[str]):
    """Activate only exact installed provider names requested by the command."""
    available = discover_providers()
    moves = Moves()
    for name in dict.fromkeys(providers):
        entries = [entry for entry in available if entry.name == name]
        if len(entries) != 1:
            raise ValueError(f"Provider {name!r} must identify exactly one installed entry point")
        load_provider(entries[0], moves.registry)
    return CapabilityCatalog(moves, names)


def _inputs(path):
    with Path(path).open("rb") as stream:
        value = decode_json(stream.read(MAX_BYTES + 1), source=path)
    if type(value) is not dict or set(value) != {"schema", "inputs"} or type(value["schema"]) is not int or value["schema"] != 1 or type(value["inputs"]) is not dict:
        raise ValueError("Inputs require {schema: 1, inputs: {...}}")
    return value["inputs"]


def _selection(function):
    function = option("--provider", dest="provider", multiple=True, required=True)(function)
    function = option("--select", dest="select", multiple=True, required=True)(function)
    return option("--catalog-version", required=True)(function)


def build_interface():
    app = Interface("scriptty", description="Inspect and execute explicit workflow documents.")

    @app.command(name="inspect")
    def inspect_document(path: str):
        """Inspect a passive document without importing any provider."""
        return {"schema": 1, "status": "inspected", "workflow": load(path).inspect()}

    @app.command(name="list")
    @_selection
    def list_capabilities(*, provider: list[str], select: list[str], catalog_version: str):
        """List only explicitly selected capabilities from trusted providers."""
        catalog = selected_catalog(provider, select)
        return {"schema": 1, "status": "listed", "catalog_version": catalog_version,
                "capabilities": [{"name": name, "input": _schema_json(catalog.describe(name).input_schema),
                                  "output": _schema_json(catalog.describe(name).output_schema)} for name in sorted(set(select))]}

    @app.command(name="run")
    @_selection
    async def run_document(path: str, *, inputs: str, provider: list[str], select: list[str],
                           catalog_version: str, checkpoint: str | None = None, pace: str = "auto"):
        """Execute a workflow; an explicit new checkpoint enables durable progress."""
        workflow = load(path)
        values = _inputs(inputs)
        return await execute(workflow, selected_catalog(provider, select), catalog_version=catalog_version,
                             inputs=values, checkpoint=checkpoint, pace=pace)

    @app.command(name="resume")
    @_selection
    async def resume_document(path: str, *, inputs: str, provider: list[str], select: list[str],
                              catalog_version: str, checkpoint: str, pace: str = "auto",
                              retry: bool = False, restart: bool = False):
        """Resume existing progress; retry/restart are explicit recovery decisions."""
        workflow = load(path)
        values = _inputs(inputs)
        return await execute(workflow, selected_catalog(provider, select), catalog_version=catalog_version,
                             inputs=values, checkpoint=checkpoint, resume=True, pace=pace, retry=retry, restart=restart)

    return app


def main(argv=None):
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = build_interface().invoke(argv)
        if result is not None:
            sys.stdout.buffer.write(canonical(result) + b"\n")
            sys.stdout.buffer.flush()
    except Exception as error:
        record = {"schema": 1, "status": "error", "error": type(error).__name__, "message": str(error)}
        sys.stderr.buffer.write(b"\n" + canonical(record) + b"\n")
        sys.stderr.buffer.flush()
        raise SystemExit(2 if isinstance(error, UsageError) else 1) from None
