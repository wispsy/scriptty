import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest

from carets import KeyMsg
from carets.testing import TestProgram
from hidden_moves import Moves
from hidden_moves.adapters import CapabilityCatalog
from moveset import Input, Pipeline, Ref, Step
from scriptty import loads
from scriptty.terminal import WorkflowTerminal, run_terminal


def workflow():
    definition = Pipeline("terminal-proof", version="1", steps=(
        Step("first", "first", {"value": Input("value")}),
        Step("second", "second", {"value": Ref("first")}),
    ), outputs={"value": Ref("second")})
    return loads(json.dumps(definition.manifest))


def catalog(first, second):
    moves = Moves()
    moves.learn(first, name="first")
    moves.learn(second, name="second")
    return CapabilityCatalog(moves, ["first", "second"])


class WorkflowTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_selection_progress_cooperative_pause_and_non_replay(self):
        entered, release, calls = asyncio.Event(), asyncio.Event(), []
        async def first(value: str) -> str:
            entered.set()
            await release.wait()
            calls.append("first")
            return value
        def second(value: str) -> str:
            calls.append("second")
            return value.upper()
        with tempfile.TemporaryDirectory() as directory:
            model = WorkflowTerminal(workflow(), catalog(first, second), catalog_version="v1",
                checkpoint=str(Path(directory) / "progress.json"), inputs={"value": "hello"})
            test = TestProgram(model)
            model.attach(test.program)
            async with test:
                await test.send(KeyMsg("tab"), KeyMsg(" "), KeyMsg("tab"), KeyMsg("enter"))
                self.assertEqual(calls, [])
                self.assertIn("Select every", model.progress)
                await test.send(KeyMsg("backtab"), KeyMsg("down"), KeyMsg(" "), KeyMsg("tab"), KeyMsg("enter"))
                await entered.wait()
                await test.wait_for(lambda: "first" in model.progress)
                await test.send(KeyMsg("p"))
                release.set()
                await test.wait_for(lambda: model.status == "paused")
                self.assertEqual((calls, model.outcome["completed"]), (["first"], ["first"]))
                await test.send(KeyMsg("r"))
                await test.wait_for(lambda: model.status == "completed")
                self.assertEqual(model.outcome["outputs"], {"value": "HELLO"})
                await test.send(KeyMsg("r"))
                await test.wait_for(lambda: model.status == "completed")
                self.assertEqual(calls, ["first", "second"])
            self.assertEqual(test.terminal.restore_count, 1)

    async def test_input_edits_resize_and_safe_visible_text(self):
        def identity(value: str) -> str: return value
        model = WorkflowTerminal(workflow(), catalog(identity, identity), catalog_version="v1", checkpoint="unused.json")
        test = TestProgram(model)
        model.attach(test.program)
        async with test:
            await test.send(*(KeyMsg("backspace") for _ in model.input.value))
            envelope = json.dumps({"schema": 1, "inputs": {"value": "edited"}})
            await test.send(KeyMsg("paste", envelope))
            self.assertEqual(model.input.value, envelope)
            await test.resize(40, 10)
            test.assert_fits(40, 10)
            model.progress = "\x1b[2J"
            self.assertNotIn("\x1b", model.view())

    async def test_uncertain_effect_requires_explicit_retry_action(self):
        calls = []
        def first(value: str) -> str:
            calls.append("first")
            if len(calls) == 1:
                raise RuntimeError("after effect")
            return value
        def second(value: str) -> str:
            calls.append("second")
            return value
        with tempfile.TemporaryDirectory() as directory:
            model = WorkflowTerminal(workflow(), catalog(first, second), catalog_version="v1",
                checkpoint=str(Path(directory) / "progress.json"), inputs={"value": "x"})
            test = TestProgram(model)
            model.attach(test.program)
            async with test:
                await test.send(KeyMsg("tab"), KeyMsg(" "), KeyMsg("down"), KeyMsg(" "), KeyMsg("tab"), KeyMsg("enter"))
                await test.wait_for(lambda: model.status == "error")
                self.assertIn("StepFailedError", model.progress)
                await test.send(KeyMsg("r"))
                await test.wait_for(lambda: model.status == "error")
                self.assertIn("RecoveryRequiredError", model.progress)
                self.assertEqual(calls, ["first"])
                await test.send(KeyMsg("t"))
                await test.wait_for(lambda: model.status == "completed")
                self.assertEqual(calls, ["first", "first", "second"])

    async def test_native_host_rejects_unsupported_input_without_terminal_mutation(self):
        def identity(value: str) -> str: return value
        with self.assertRaisesRegex(ValueError, "POSIX TTY"):
            await run_terminal(workflow(), catalog(identity, identity), catalog_version="1", checkpoint="unused.json",
                               input_stream=io.BytesIO(), output_stream=io.StringIO())
