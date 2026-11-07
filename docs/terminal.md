# Optional workflow terminal

Install the `terminal` profile on Python 3.14+. The native host requires supported
POSIX TTY input; synthetic fixtures qualify the model on Linux/macOS/Windows.

```sh
scriptty terminal examples/text.json --inputs inputs.json --checkpoint progress.json --provider wispsy-reference --select text.normalize --select text.report --catalog-version text-v1
```

Tab moves between the JSON input editor, required capabilities and actions. Use
up/down and space to explicitly select every required capability before execution.
Enter on actions starts a new run; r resumes existing progress, t explicitly retries
an uncertain action, and R restarts. p requests a cooperative pause. q/Ctrl-C during
execution requests pause and closes after that boundary; otherwise it closes the
session. Synchronous functions cannot be preempted while blocking the UI thread.

Inputs use the same schema-1 envelope as CLI execution. Workflow files are still
passive; the host selects trusted installed providers and exact catalog names.
Carets owns input, focus, rendering, terminal state and command lifetime. The same
application.execute API and func_seq Script/Control own execution/progress/recovery.
There is no additional parser, executor, checkpoint format or desktop listener.

The native host owns raw mode, alternate screen, cursor and bracketed paste only
for its session. UI rendering uses the explicitly selected stderr stream; trusted
diagnostics are buffered and flushed after terminal restoration, and the final
versioned outcome uses the CLI stdout contract. Visible input/progress control
characters are escaped. Library construction installs no terminal or signal hooks.

WorkflowTerminal is an ordinary update/view model. Attach it to a Carets Program
and supply the same workflow, catalog version, inputs and explicit checkpoint.
Installed tests use TestProgram to prove input edits, selection gates, resize,
progress, cooperative pause, completed-step non-replay and explicit uncertain retry.
All library and CLI execution remains available without this optional frontend.
