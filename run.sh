#!/usr/bin/env bash
# Arranca RNCli creando el entorno virtual la primera vez.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

PYTHON="${PYTHON:-python3}"
VENV=".venv"

if [ ! -x "$VENV/bin/python" ]; then
  echo "[rncli] creando entorno virtual en $VENV ..."
  "$PYTHON" -m venv "$VENV"
fi

if ! "$VENV/bin/python" -c "import PySide6, pyte" >/dev/null 2>&1; then
  echo "[rncli] instalando dependencias (PySide6, pyte) ..."
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  "$VENV/bin/python" -m pip install -r requirements.txt
fi

exec "$VENV/bin/python" -m rncli "$@"
