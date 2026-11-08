import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest

from carets import KeyMsg
try:
    from carets.testing import TestProgram
except ImportError:
    import heapq, math
    from carets import KeyMsg
    from carets.input import AnsiInputParser
    from carets.runtime import Program
    from carets.style import visual_width
    from carets.terminal import TerminalCapabilities, TerminalSession

    class ManualClock:
        def __init__(self):
            self.now = 0.0
            self._sleepers = []
            self._order = 0
        async def sleep(self, seconds):
            if not math.isfinite(seconds) or seconds < 0:
                raise ValueError("Delay must be finite and nonnegative")
            if seconds == 0:
                await asyncio.sleep(0)
                return
            self._order += 1
            future = asyncio.get_running_loop().create_future()
            heapq.heappush(self._sleepers, (self.now + seconds, self._order, future))
            await future
        def advance(self, seconds):
            if not math.isfinite(seconds) or seconds < 0:
                raise ValueError("Clock advances must be finite and nonnegative")
            self.now += seconds
            while self._sleepers and self._sleepers[0][0] <= self.now:
                _, _, future = heapq.heappop(self._sleepers)
                if not future.done():
                    future.set_result(None)

    class FakeTerminal:
        capabilities = TerminalCapabilities(True, True, True, True, True)
        def __init__(self, width=80, height=24):
            self.input = io.BytesIO()
            self.output = io.StringIO()
            self.dimensions = (width, height)
            self.raw = False
            self.restore_count = 0
            self.handlers = {}
        def size(self): return self.dimensions
        def capture_raw(self): return self.raw
        def enter_raw(self): self.raw = True
        def restore_raw(self, state):
            self.raw = state
            self.restore_count += 1
        def install_signal(self, name, callback):
            previous = self.handlers.get(name)
            self.handlers[name] = callback
            return name, previous
        def restore_signal(self, token):
            name, previous = token
            if previous is None:
                self.handlers.pop(name, None)
            else:
                self.handlers[name] = previous
        def resize(self, width, height):
            self.dimensions = (width, height)
            if "resize" in self.handlers:
                self.handlers["resize"]()

    class SnapshotRenderer:
        def __init__(self): self.frames = []
        def render(self, view):
            self.frames.append(str(view))
            return ""
        @property
        def latest(self): return self.frames[-1] if self.frames else ""

    class TestProgram:
        def __init__(self, model, *, terminal=None, clock=None):
            self.model = model
            self.terminal = terminal if terminal is not None else FakeTerminal()
            self.clock = clock if clock is not None else ManualClock()
            self.renderer = SnapshotRenderer()
            self.parser = AnsiInputParser()
            self.program = Program(model, renderer=self.renderer, output_stream=self.terminal.output,
                sleep=self.clock.sleep, terminal=TerminalSession(self.terminal.input, self.terminal.output, backend=self.terminal))
            self.task = None
        async def __aenter__(self):
            self.task = asyncio.create_task(self.program.run([], stop_on_eof=False))
            await self.settle()
            return self
        async def __aexit__(self, *_errors):
            self.program.stop()
            await self.task
        async def settle(self):
            await self.program.idle()
            if self.task is not None and self.task.done():
                await self.task
        async def send(self, *messages):
            for message in messages:
                self.program.post(message)
            await self.settle()
        async def send_bytes(self, data):
            await self.send(*self.parser.feed(data))
        async def advance(self, seconds):
            self.clock.advance(seconds)
            await self.settle()
        async def resize(self, width, height):
            self.terminal.resize(width, height)
            await self.settle()
        async def wait_for(self, predicate, *, turns=100):
            for _ in range(turns):
                await self.settle()
                if predicate():
                    return
            raise AssertionError("Application did not reach the expected state")
        def assert_snapshot(self, expected):
            if self.renderer.latest != expected:
                raise AssertionError(f"Expected {expected!r}, received {self.renderer.latest!r}")
        def assert_fits(self, width, height):
            lines = self.renderer.latest.splitlines()
            if len(lines) > height or any(visual_width(line) > width for line in lines):
                raise AssertionError(f"Snapshot exceeds {width}x{height}")
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
