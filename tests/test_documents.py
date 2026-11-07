import json
from pathlib import Path
import tempfile
import unittest

from hidden_moves import Moves
from hidden_moves.adapters import CapabilityCatalog
from moveset import Input, Pipeline, Ref, Step
from scriptty import DocumentError, decode_json, load, loads


def definition():
    return Pipeline("text", version="1", steps=(Step("clean", "normalize", {"text": Input("text")}),), outputs={"text": Ref("clean")})


class DocumentTests(unittest.TestCase):
    def test_json_roundtrip_binds_only_a_selected_catalog(self):
        calls = []

        def normalize(text: str) -> str:
            calls.append(text)
            return text.lower()

        moves = Moves()
        moves.learn(normalize)
        workflow = loads(json.dumps(definition().manifest), source="workflow.json")
        self.assertEqual(calls, [])
        self.assertEqual(workflow.inspect(), definition().manifest)
        selected = CapabilityCatalog(moves, ["normalize"])
        self.assertEqual(workflow.bind(selected, catalog_version="v1").run({"text": "HI"}).outputs, {"text": "hi"})
        with self.assertRaisesRegex(DocumentError, "workflow.json.*clean"):
            workflow.bind(CapabilityCatalog(moves, []), catalog_version="v1")

    def test_toml_and_json_are_equivalent_and_file_reads_bounded(self):
        text = '''schema = 1
name = "text"
version = "1"
outputs = { object = { text = { ref = { step = "clean" } } } }
[[steps]]
id = "clean"
capability = "normalize"
arguments = { object = { text = { input = { name = "text" } } } }
'''
        self.assertEqual(loads(text, format="toml").inspect(), definition().manifest)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.toml"
            path.write_text(text)
            self.assertEqual(load(path).inspect(), definition().manifest)
            path.write_bytes(b" " * 1_048_577)
            with self.assertRaisesRegex(DocumentError, "exceeds"):
                load(path)

    def test_strict_json_syntax_and_finite_values(self):
        for text in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":1e999}', '{"x":"\\ud800"}', b'\xff', '[' * 1000):
            with self.subTest(text=str(text)[:30]), self.assertRaisesRegex(DocumentError, "source.json"):
                decode_json(text, source="source.json")
        with self.assertRaisesRegex(DocumentError, "source.json:2:1"):
            decode_json('{\n!}', source="source.json")

    def test_unknown_keys_versions_and_unsafe_forms_rejected_passively(self):
        base = definition().manifest
        for change in ({"schema": True}, {"schema": 2}, {"provider": "os:system"}, {"steps": "invalid"}):
            with self.subTest(change=change), self.assertRaises(DocumentError):
                loads(json.dumps({**base, **change}))
        for expression in ({"eval": "__import__('os')"}, {"value": 1, "ref": {"step": "clean"}}, {"ref": {"step": "clean", "path": [True]}}, {"import": "os"}):
            base = definition().manifest
            base["steps"][0]["arguments"]["object"]["text"] = expression
            with self.subTest(expression=expression), self.assertRaisesRegex(DocumentError, r"steps\[0\]"):
                loads(json.dumps(base), source="unsafe.json")

    def test_forward_refs_duplicates_and_bad_shapes_have_step_locations(self):
        for arguments in ({"object": {"text": {"ref": {"step": "later"}}}}, {"value": "wrong shape"}):
            base = definition().manifest
            base["steps"][0]["arguments"] = arguments
            with self.assertRaisesRegex(DocumentError, r"source.json:\$\.steps\[0\]"):
                loads(json.dumps(base), source="source.json")
        base = definition().manifest
        base["steps"].append(base["steps"][0])
        with self.assertRaisesRegex(DocumentError, r"steps\[1\].*Duplicate"):
            loads(json.dumps(base))

    def test_literal_reference_shaped_objects_stay_literal(self):
        base = definition().manifest
        literal = {"ref": {"step": "never"}, "input": {"name": "never"}}
        base["outputs"] = {"object": {"literal": {"value": literal}}}
        self.assertEqual(loads(json.dumps(base)).definition.outputs["literal"], literal)

    def test_toml_dates_duplicate_keys_and_unknown_format_rejected(self):
        for text in ('schema = 1\nschema = 1', 'date = 2026-11-07', '[' * 1000):
            with self.assertRaises(DocumentError):
                loads(text, format="toml")
        with self.assertRaises(DocumentError):
            loads("{}", format="python")
