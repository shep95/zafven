"""Generate cipher puzzles for the Cipher Events ARG feature."""
from __future__ import annotations

import base64
import random
from dataclasses import dataclass

_PHRASES = [
    "the monad", "as above so below", "know thyself", "the unseen hand",
    "frequency of truth", "the seeker finds", "nine planets nine gates",
    "the hidden door", "silence speaks", "the inner light", "north star",
    "the void walker", "eternal return", "the golden ratio", "sacred geometry",
]
_MORSE = {
    "a": ".-", "b": "-...", "c": "-.-.", "d": "-..", "e": ".", "f": "..-.",
    "g": "--.", "h": "....", "i": "..", "j": ".---", "k": "-.-", "l": ".-..",
    "m": "--", "n": "-.", "o": "---", "p": ".--.", "q": "--.-", "r": ".-.",
    "s": "...", "t": "-", "u": "..-", "v": "...-", "w": ".--", "x": "-..-",
    "y": "-.--", "z": "--..", " ": "/",
}


@dataclass
class Puzzle:
    answer: str
    ciphertext: str
    method: str
    hint: str


def _caesar(text: str, shift: int) -> str:
    out = []
    for ch in text:
        if ch.isalpha():
            base = ord("a")
            out.append(chr((ord(ch) - base + shift) % 26 + base))
        else:
            out.append(ch)
    return "".join(out)


def _atbash(text: str) -> str:
    return "".join(chr(ord("z") - (ord(c) - ord("a"))) if c.isalpha() else c for c in text)


def make_puzzle(seed: int | None = None) -> Puzzle:
    rng = random.Random(seed)
    answer = rng.choice(_PHRASES)
    method = rng.choice(["caesar", "atbash", "base64", "reverse", "morse"])
    if method == "caesar":
        shift = rng.randint(1, 25)
        return Puzzle(answer, _caesar(answer, shift), "caesar", f"Caesar shift (by {shift}).")
    if method == "atbash":
        return Puzzle(answer, _atbash(answer), "atbash", "Atbash (mirror the alphabet).")
    if method == "base64":
        enc = base64.b64encode(answer.encode()).decode()
        return Puzzle(answer, enc, "base64", "Base64.")
    if method == "reverse":
        return Puzzle(answer, answer[::-1], "reverse", "It's reversed.")
    morse = " ".join(_MORSE.get(c, "?") for c in answer)
    return Puzzle(answer, morse, "morse", "Morse code (/ = space).")


def normalize(text: str) -> str:
    return " ".join(text.lower().split())
