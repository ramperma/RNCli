"""Parser estilo vCard: lineas NAME:VALUE, continuacion con espacio inicial,
parametros ';...' ignorados en el nombre, nombres a mayusculas."""
from typing import Dict


def parse(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    last: str | None = None
    for line in text.splitlines():
        if not line:
            continue
        if line[0] in " \t":
            if last is not None:
                result[last] += line[1:]
            continue
        name, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"invalid line: {line!r}")
        key = name.split(";", 1)[0].strip().upper()
        if key in ("BEGIN", "END"):
            last = None
            continue
        result[key] = value
        last = key
    return result
