#!/usr/bin/env bash
# Instala RNCli en el menú de aplicaciones del escritorio (usuario actual).
set -euo pipefail

ROOT="$(dirname "$(readlink -f "$0")")"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

echo "[rncli] preparando el entorno virtual..."
"$ROOT/run.sh" --version >/dev/null

mkdir -p "$DESKTOP_DIR" "$ICON_DIR"
cp "$ROOT/assets/rncli.svg" "$ICON_DIR/rncli.svg"

sed -e "s|__EXEC__|$ROOT/run.sh|g" \
    -e "s|__ICON__|rncli|g" \
    "$ROOT/packaging/rncli.desktop" > "$DESKTOP_DIR/rncli.desktop"
chmod +x "$DESKTOP_DIR/rncli.desktop"

echo "[rncli] instalado:"
echo "  entrada de menú : $DESKTOP_DIR/rncli.desktop"
echo "  icono           : $ICON_DIR/rncli.svg"
echo
echo "Ya puedes abrir RNCli desde el menú de aplicaciones (búscalo como «RNCli»)."
