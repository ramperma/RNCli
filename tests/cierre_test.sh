#!/usr/bin/env bash
# Comprueba que RNCli arranca con el entorno del escritorio (PATH mínimo) y que
# al cerrarse NO deja agentes huérfanos, ni con cierre limpio ni con kill -9.
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

ENV_MINIMA=(env -i "HOME=$HOME" "USER=$USER" SHELL=/bin/bash
            PATH=/usr/local/bin:/usr/bin:/bin "DISPLAY=${DISPLAY:-:0.0}"
            "XDG_RUNTIME_DIR=/run/user/$(id -u)")

app_pid() {
  local wid
  wid=$(DISPLAY="${DISPLAY:-:0.0}" xdotool search --class '^rncli$' 2>/dev/null | head -1)
  [ -n "$wid" ] || return 1
  DISPLAY="${DISPLAY:-:0.0}" xprop -id "$wid" _NET_WM_PID 2>/dev/null | sed 's/.*= //'
}

agentes_hijos() {  # procesos cuyo padre sea la app
  ps -eo pid,ppid,cmd 2>/dev/null | awk -v app="$1" '$2 == app && /opencode|bin\/pi/ {print}'
}

probar() {
  local modo="$1" senal="$2"
  echo "──────── $modo ────────"
  "${ENV_MINIMA[@]}" ./run.sh --no-restore >/tmp/opencode/cierre_$modo.log 2>&1 &
  local lanzador=$!
  sleep 12

  local app
  app=$(app_pid) || { echo "  FALLO: no se encontró la ventana de RNCli"; kill "$lanzador" 2>/dev/null; return 1; }
  echo "  app pid: $app"

  local hijos
  hijos=$(agentes_hijos "$app")
  if [ -n "$hijos" ]; then echo "  agente en marcha:"; echo "$hijos" | sed 's/^/    /'; else echo "  FALLO: el agente no arrancó"; fi

  kill "$senal" "$app" 2>/dev/null
  sleep 3

  local restos
  restos=$(agentes_hijos "$app")
  if [ -n "$restos" ]; then
    echo "  FALLO: quedan procesos huérfanos:"; echo "$restos" | sed 's/^/    /'
    pkill -9 -P "$app" 2>/dev/null
    kill -9 "$lanzador" 2>/dev/null
    return 1
  fi
  echo "  OK: sin procesos huérfanos tras $senal"
  kill -9 "$lanzador" 2>/dev/null
  sleep 1
  return 0
}

fallos=0
probar "limpio"  TERM || fallos=$((fallos + 1))
probar "brusco"  KILL || fallos=$((fallos + 1))

echo
if [ "$fallos" -eq 0 ]; then echo "RESULTADO: OK (cierre limpio y cierre brusco sin huérfanos)"; else echo "RESULTADO: $fallos prueba(s) fallidas"; fi
exit "$fallos"
