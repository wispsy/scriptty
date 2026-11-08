"""Synthetic selected provider for installed process tests."""

import os
from pathlib import Path

try:
    from hidden_moves import MoveSet
except ImportError:
    from hidden_moves import Moves
    class MoveSet:
        def __init__(self, name: str) -> None:
            self.name = name
            self._moves = Moves()
        def learn(self, func, **kwargs):
            return self._moves.learn(func, namespace=self.name, **kwargs)
        def moves(self):
            return self._moves.moves()


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
