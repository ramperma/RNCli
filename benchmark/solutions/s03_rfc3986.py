"""vCard-style parser: parses NAME:VALUE lines with continuations.

Grammar handled (simplified subset):
  BEGIN:VCARD / END:VCARD wrappers optional
  Lines "NAME:VALUE", continuation lines start with a space.
  Property names are case-insensitive; values keep original case.
"""
from typing import Dict


def parse_vcard(text: str) -> Dict[str, str]:
    props: Dict[str, str] = {}
    current: str | None = None
    for raw in text.splitlines():
        if not raw:
            continue
        if raw[0] in (" ", "\t"):  # continuation
            if current is not None:
                props[current] += raw[1:]
            continue
        if ":" not in raw:
            raise ValueError(f"invalid line: {raw!r}")
        name, value = raw.split(":", 1)
        name = name.split(";", 1)[0].strip().upper()
        if name in ("BEGIN", "END"):
            continue
        props[name] = value
        current = name
    return props
