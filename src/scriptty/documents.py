"""Strict schema-1 JSON/TOML without imports, evaluation or provider activation."""

from dataclasses import dataclass
import json
from pathlib import Path
import tomllib

from moveset import Input, Pipeline, PipelineError, Ref, Step
from moveset.core import MAX_BYTES, MAX_DEPTH, copy_json


class DocumentError(ValueError):
    """A source-labelled passive document error."""


def _error(source, location, message):
    return DocumentError(f"{source}:{location}: {message}")


def decode_json(data: str | bytes, *, source="<memory>"):
    """Decode a bounded finite JSON value; duplicate keys are errors."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate key {key!r}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Non-finite number {value}")

    try:
        text = _text(data)
        return copy_json(json.loads(text, object_pairs_hook=pairs, parse_constant=constant))
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        location = f"{error.lineno}:{error.colno}" if isinstance(error, json.JSONDecodeError) else "$"
        raise _error(source, location, str(error)) from error


def _text(data):
    if type(data) not in (str, bytes):
        raise ValueError("Expected UTF-8 text or bytes")
    if len(data) > MAX_BYTES:
        raise ValueError(f"Document exceeds {MAX_BYTES} bytes")
    if type(data) is bytes:
        data = data.decode("utf-8")
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"Document exceeds {MAX_BYTES} bytes")
    return data


def _object(value, required, optional, source, location):
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - optional:
        raise _error(source, location, f"Expected object with keys {sorted(required)}, optional {sorted(optional)}")


def _expression(value, source, location, depth=0):
    if depth > MAX_DEPTH:
        raise _error(source, location, "Expression nesting limit exceeded")
    if type(value) is not dict or len(value) != 1:
        raise _error(source, location, "Expression requires exactly one tag")
    tag, payload = next(iter(value.items()))
    try:
        if tag == "value":
            return copy_json(payload)
        if tag in ("input", "ref"):
            key = "name" if tag == "input" else "step"
            _object(payload, {key}, {"path"}, source, location)
            path = payload.get("path", [])
            if type(path) is not list:
                raise ValueError("Reference path must be an array")
            return (Input if tag == "input" else Ref)(payload[key], tuple(path))
        if tag == "object" and type(payload) is dict:
            return {key: _expression(item, source, f"{location}.{key}", depth + 1) for key, item in payload.items()}
        if tag == "array" and type(payload) is list:
            return [_expression(item, source, f"{location}[{index}]", depth + 1) for index, item in enumerate(payload)]
        raise ValueError(f"Unsupported expression tag or payload: {tag!r}")
    except PipelineError as error:
        raise _error(source, location, str(error)) from error
    except (TypeError, ValueError) as error:
        if isinstance(error, DocumentError):
            raise
        raise _error(source, location, str(error)) from error


@dataclass(frozen=True)
class Workflow:
    definition: Pipeline
    source: str

    def inspect(self):
        return self.definition.manifest

    def bind(self, catalog, *, catalog_version):
        try:
            return self.definition.bind(catalog, catalog_version=catalog_version)
        except PipelineError as error:
            raise _error(self.source, "$.steps", str(error)) from error


def loads(data: str | bytes, *, format="json", source="<memory>") -> Workflow:
    try:
        if format == "json":
            document = decode_json(data, source=source)
        elif format == "toml":
            document = copy_json(tomllib.loads(_text(data)))
        else:
            raise _error(source, "$", "Format must be json or toml")
        _object(document, {"schema", "name", "version", "steps", "outputs"}, set(), source, "$")
        if type(document["schema"]) is not int or document["schema"] != 1:
            raise _error(source, "$.schema", "Only schema 1 is supported")
        if type(document["steps"]) is not list:
            raise _error(source, "$.steps", "Steps must be an array")
        steps = []
        for index, item in enumerate(document["steps"]):
            location = f"$.steps[{index}]"
            _object(item, {"id", "capability", "arguments"}, set(), source, location)
            arguments = _expression(item["arguments"], source, location + ".arguments")
            try:
                step = Step(item["id"], item["capability"], arguments)
                # Validate references/duplicates at their source step before building the final definition.
                Pipeline(document["name"], version=document["version"], steps=(*steps, step), outputs={})
            except PipelineError as error:
                raise _error(source, location, str(error)) from error
            steps.append(step)
        outputs = _expression(document["outputs"], source, "$.outputs")
        return Workflow(Pipeline(document["name"], version=document["version"], steps=tuple(steps), outputs=outputs), source)
    except DocumentError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise _error(source, "$", str(error)) from error


def load(path: str | Path) -> Workflow:
    path = Path(path)
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
    except OSError as error:
        raise _error(str(path), "$", str(error)) from error
    format = path.suffix.removeprefix(".").lower()
    return loads(data, format=format, source=str(path))
