"""Optional Carets frontend over the same passive workflow/application API."""

import sys

if sys.version_info < (3, 14):
    raise ImportError("The workflow terminal requires the terminal profile on Python 3.14+")

import contextlib
from dataclasses import dataclass, replace
import io
import json

from carets import Command, CommandErrorMsg, FocusManager, Form, Group, KeyMsg, Msg, Program, TerminalOptions, TerminalSession, TypedField, WindowSizeMsg
from carets.components import TextInput
from carets.renderer import CellDiffRenderer
from carets.style import truncate_ansi
from func_seq import Control

from .application import execute
from .documents import decode_json


@dataclass(frozen=True)
class ProgressMsg(Msg):
    kind: str
    step_id: str | None


@dataclass(frozen=True)
class OutcomeMsg(Msg):
    outcome: dict


def _input_values(text):
    envelope = decode_json(text, source="terminal inputs")
    if type(envelope) is not dict or set(envelope) != {"schema", "inputs"} or type(envelope["schema"]) is not int or envelope["schema"] != 1 or type(envelope["inputs"]) is not dict:
        raise ValueError("Use a schema-1 inputs object")
    return envelope["inputs"]


def _visible(text):
    return "".join(char if char.isprintable() else f"\\u{ord(char):04x}" for char in str(text))


class WorkflowTerminal:
    """A testable update/view model. The host supplies catalog and resource policy."""

    def __init__(self, workflow, catalog, *, catalog_version, checkpoint, inputs=None):
        self.workflow, self.catalog = workflow, catalog
        self.catalog_version, self.checkpoint = catalog_version, checkpoint
        self.names = tuple(dict.fromkeys(step.capability for step in workflow.definition.steps))
        self.checked = set()
        self.selected_index = 0
        initial = json.dumps({"schema": 1, "inputs": inputs if inputs is not None else {}}, ensure_ascii=False)
        self.input = TextInput(initial, cursor=len(initial))
        self.form = Form([Group([TypedField("inputs", "Inputs", _input_values, default=initial)])])
        self.focus = FocusManager()
        for name in ("inputs", "capabilities", "actions"):
            self.focus.register(name)
        self.width, self.height = 80, 24
        self.status, self.progress = "ready", ""
        self.outcome = None
        self.control = Control()
        self.program = None
        self.exit_requested = False
        self._layout()

    def attach(self, program):
        self.program = program

    def _layout(self):
        for name, y in (("inputs", 1), ("capabilities", 2), ("actions", max(0, self.height - 2))):
            self.focus.zones.define(name, 0, min(y, self.height - 1), self.width, 1)

    def start(self, *, resume=False, retry=False, restart=False):
        if self.status == "running":
            return None
        if self.checked != set(self.names):
            self.progress = "Select every required capability before execution"
            return None
        self.form.update("inputs", self.input.value)
        result = self.form.submit()
        if result.status != "valid":
            self.progress = "Inputs must be valid schema-1 JSON"
            return None
        if self.program is None:
            raise RuntimeError("Attach this model to a Program before execution")
        self.status, self.progress, self.outcome = "running", "starting", None
        self.control = Control()

        def observe(event):
            self.program.post(ProgressMsg(event.kind, event.step_id))

        async def produce():
            outcome = await execute(self.workflow, self.catalog, catalog_version=self.catalog_version,
                inputs=result.values["inputs"], checkpoint=self.checkpoint, resume=resume,
                retry=retry, restart=restart, control=self.control, observer=observe)
            return OutcomeMsg(outcome)
        return Command(produce)

    def update(self, message):
        if isinstance(message, WindowSizeMsg):
            self.width, self.height = max(1, message.width), max(1, message.height)
            self._layout()
        elif isinstance(message, ProgressMsg):
            self.progress = message.kind + (f" {message.step_id}" if message.step_id else "")
        elif isinstance(message, OutcomeMsg):
            self.outcome = message.outcome
            self.status = self.outcome["status"]
            if self.exit_requested:
                self.program.stop()
        elif isinstance(message, CommandErrorMsg):
            self.status = "error"
            self.progress = type(message.error).__name__ + "; resume/retry/restart are explicit choices"
            self.outcome = {"schema": 1, "status": "error", "error": type(message.error).__name__}
            if self.exit_requested:
                self.program.stop()
        elif isinstance(message, KeyMsg):
            if message.key == "ctrl-c" or (message.key == "q" and (self.focus.focused != "inputs" or self.status == "running")):
                if self.status == "running":
                    self.exit_requested = True
                    self.control.request_pause()
                elif self.program is not None:
                    self.program.stop()
            elif message.key == "p" and self.status == "running":
                self.control.request_pause()
                self.progress = "pause requested at the next cooperative boundary"
            elif message.key in ("tab", "backtab", "shift-tab"):
                self.focus.route(message)
            elif self.status != "running" and self.focus.focused == "inputs":
                self.input = replace(self.input, focused=True).update(message)
            elif self.status != "running" and self.focus.focused == "capabilities":
                if message.key in ("up", "down"):
                    self.selected_index = (self.selected_index + (1 if message.key == "down" else -1)) % len(self.names)
                elif message.key == " ":
                    name = self.names[self.selected_index]
                    self.checked.symmetric_difference_update({name})
            elif self.focus.focused == "actions":
                if message.key == "enter":
                    return self.start()
                if message.key in ("r", "t", "R"):
                    return self.start(resume=True, retry=message.key == "t", restart=message.key == "R")

    def view(self):
        count = max(1, self.height - 6)
        offset = max(0, self.selected_index - count + 1)
        names = self.names[offset:offset + count]
        lines = [f"Workflow: {self.workflow.definition.name}",
                 f"{self.focus.indicator('inputs')} Inputs: {_visible(replace(self.input, focused=self.focus.focused == 'inputs').view())}",
                 f"{self.focus.indicator('capabilities')} Required capabilities (space selects)"]
        for index, name in enumerate(names, offset):
            lines.append(f"  {'>' if index == self.selected_index else ' '} [{'x' if name in self.checked else ' '}] {_visible(name)}")
        lines += [f"{self.focus.indicator('actions')} Enter run | r resume | t retry | R restart | p pause | q quit",
                  f"Status: {self.status} {_visible(self.progress)}"]
        return "\n".join(truncate_ansi(line, self.width) for line in lines[:self.height])


class _Renderer:
    def __init__(self, model):
        self.model = model
        self.size = None
        self.renderer = None

    def render(self, view):
        size = self.model.width, self.model.height
        if size != self.size:
            self.size = size
            self.renderer = CellDiffRenderer(*size)
        return self.renderer.render(view)


async def run_terminal(workflow, catalog, *, catalog_version, checkpoint, inputs=None,
                       input_stream=None, output_stream=None, diagnostics=None, messages=None):
    """Select terminal ownership explicitly; flush trusted diagnostics after teardown."""
    input_stream = input_stream if input_stream is not None else sys.stdin.buffer
    output_stream = output_stream if output_stream is not None else sys.stderr
    diagnostics = diagnostics if diagnostics is not None else sys.stderr
    session = TerminalSession(input_stream, output_stream,
        options=TerminalOptions(alternate_screen=True, bracketed_paste=True))
    if messages is None and (not session.capabilities.raw or not session.capabilities.tty):
        raise ValueError("Interactive input requires a supported POSIX TTY; library/CLI execution remains available")
    model = WorkflowTerminal(workflow, catalog, catalog_version=catalog_version, checkpoint=checkpoint, inputs=inputs)
    program = Program(model, input_stream=input_stream, output_stream=output_stream,
                      renderer=_Renderer(model), terminal=session)
    model.attach(program)
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            await program.run(messages, stop_on_eof=messages is None)
    finally:
        diagnostics.write(buffer.getvalue())
        diagnostics.flush()
    return model.outcome if model.outcome is not None else {"schema": 1, "status": "closed"}
