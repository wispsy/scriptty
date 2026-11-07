"""Synthetic selected provider for installed process tests."""

import os
from pathlib import Path

from hidden_moves import MoveSet


def _record(name):
    path = os.environ.get("SCRIPTTY_TEST_RECEIPT")
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(name + "\n")
    return Path(path).read_text().splitlines().count(name) if path else 0


def normalize(text: str) -> str:
    print("normalizing", end="")
    _record("normalize")
    return " ".join(text.split()).casefold()


def report(text: str) -> dict[str, str]:
    count = _record("report")
    if os.environ.get("SCRIPTTY_TEST_FAIL") and count == 1:
        raise RuntimeError("synthetic failure after effect")
    return {"text": text}


def provide_moves():
    print("selected provider")
    moves = MoveSet("text")
    moves.learn(normalize)
    moves.learn(report)
    return moves.moves()
