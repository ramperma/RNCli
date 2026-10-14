#!/usr/bin/env bash
# Arranca RNCli creando el entorno virtual la primera vez.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
ROOT="$(pwd)"

PYTHON="${PYTHON:-python3}"
VENV="$ROOT/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  echo "[rncli] creando entorno virtual en $VENV ..."
  "$PYTHON" -m venv "$VENV"
fi

if ! "$VENV/bin/python" -c "import PySide6, pyte" >/dev/null 2>&1; then
  echo "[rncli] instalando dependencias (PySide6, pyte) ..."
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  "$VENV/bin/python" -m pip install -r requirements.txt
fi

# Motor nativo opcional (PTY + VT). Si no hay Rust o falla la compilación, se usa pyte.
if [ -x "$HOME/.cargo/bin/cargo" ] || command -v cargo >/dev/null 2>&1; then
  export PATH="${HOME}/.cargo/bin:${PATH}"
  NATIVE_SO="$("$VENV/bin/python" -c "import pathlib, rncli_native; print(next(iter(pathlib.Path(rncli_native.__file__).parent.glob('*.so')), ''))" 2>/dev/null || true)"
  NEED_BUILD=1
  if [ -n "$NATIVE_SO" ] && [ -z "$(find "$ROOT/native/src" "$ROOT/native/Cargo.toml" -newer "$NATIVE_SO" -print -quit 2>/dev/null)" ]; then
    NEED_BUILD=0
  fi
  if [ "$NEED_BUILD" = "1" ]; then
    echo "[rncli] compilando motor nativo (Rust)..."
    if "$VENV/bin/python" -m pip install -q maturin \
      && (cd "$ROOT/native" && VIRTUAL_ENV="$VENV" "$VENV/bin/python" -m maturin develop --release); then
      echo "[rncli] motor nativo listo"
    else
      echo "[rncli] no se pudo compilar el motor nativo; se usará pyte"
    fi
  fi
fi

exec "$VENV/bin/python" -m rncli "$@"
