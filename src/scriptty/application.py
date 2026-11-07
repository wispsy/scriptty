"""Application outcomes shared by command-line and optional interactive hosts."""

from pathlib import Path


async def execute(workflow, catalog, *, catalog_version, inputs, checkpoint=None,
                  resume=False, pace="auto", retry=False, restart=False, control=None, observer=None):
    """Run selected code without installing input/signal/terminal policy.

    An explicit checkpoint selects func_seq. New execution requires a new path;
    resume requires existing progress. Recovery choices retain func_seq semantics.
    """
    bound = workflow.bind(catalog, catalog_version=catalog_version)
    if checkpoint is None:
        if resume or retry or restart or pace != "auto" or control is not None or observer is not None:
            raise ValueError("Lifecycle options require an explicit checkpoint")
        result = await bound.arun(inputs)
        return {"schema": 1, "status": "completed", "fingerprint": bound.fingerprint,
                "completed": [step.id for step in bound.definition.steps], "results": result.results,
                "outputs": result.outputs, "run_id": None}
    if bool(resume) != Path(checkpoint).exists():
        raise ValueError("Resume requires existing progress; run requires a new checkpoint path")
    if (retry or restart) and not resume:
        raise ValueError("Recovery requires explicit resume")
    from moveset.sequence import compile_script

    script = compile_script(bound, inputs, asynchronous=True)
    progress = await script.arun(checkpoint=checkpoint, pace=pace, retry=retry, restart=restart,
                                control=control, observer=observer)
    outputs = bound.finish(inputs, progress.results).outputs if progress.status == "completed" else None
    return {"schema": 1, "status": str(progress.status), "fingerprint": bound.fingerprint,
            "completed": list(progress.completed), "results": progress.results,
            "outputs": outputs, "run_id": progress.run_id}
