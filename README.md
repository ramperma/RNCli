# RNCli

Multiplexor de **terminales para agentes de IA** hecho con **PySide6**.

Lanza `opencode`, `pi` (Pi Coding Agent), `cursor-agent`, `claude` y `gemini` a la vez,
cada uno en una **terminal real** (pty + emulación VT100 con [pyte]), y organízalos en
pestañas y diseños: **uno solo, dos visibles, rejilla 2×2, 3×2 o todos a la vez**.

```
┌───────────────────────────┬───────────────────────────┐
│ ◆ OpenCode                │ π Pi Agent                │
│  (TUI real, con color)    │  (TUI real, con color)    │
├───────────────────────────┼───────────────────────────┤
│ ✦ Gemini CLI              │ $ Bash                    │
└───────────────────────────┴───────────────────────────┘
      diseños: 1 · 2 en paralelo · 2 apilados · 4 · 6 · todos
```

## Arranque rápido

```bash
./run.sh                 # crea el venv, instala PySide6+pyte y abre RNCli
```

Opciones útiles:

```bash
./run.sh --agent pi            # arranca con un agente concreto
./run.sh --cwd ~/proyecto      # carpeta de trabajo inicial
./run.sh --no-restore          # ignora la sesión guardada
./run.sh --version
```

También se puede ejecutar directamente una vez creado el entorno:

```bash
.venv/bin/python -m rncli
```

## Cómo se usa

### Elegir agente
`Ctrl+T` (pestaña nueva) o `Ctrl+Shift+T` (panel nuevo en la pestaña actual) abre el
selector: pulsa el **número** del agente o haz clic. También hay un campo para escribir
un **comando propio** (por ejemplo `opencode --model sonnet`).

El selector muestra la **ruta absoluta** que ha encontrado de cada agente
(`/home/usuario/.opencode/bin/opencode · instalado`). Si un agente no aparece, el
tooltip explica cómo poner su ruta a mano en `config.json`.

### Diseños («que se vean todos» o «solo dos»)
| Atajo | Diseño | Paneles visibles |
|-------|--------|------------------|
| `Alt+1` | Solo el activo (los demás siguen ejecutándose) | 1 |
| `Alt+2` | Dos en paralelo (izquierda/derecha) | 2 |
| `Alt+3` | Dos apilados (arriba/abajo) | 2 |
| `Alt+4` | Rejilla 2×2 | 4 |
| `Alt+5` | Rejilla 3×2 | 6 |
| `Alt+0` | **Todos visibles** (rejilla automática) | todos |
| `Ctrl+Shift+M` | Alterna entre «todos» y «solo el activo» | |

Los paneles ocultos **no se cierran**: siguen trabajando y los recuperas al cambiar de diseño.

### Pestaña frente a panel

Una **pestaña** es una sesión independiente; un **panel** es una terminal visible dentro
de esa sesión. Para ver agentes que ya abriste en pestañas lado a lado, pulsa
**⇱ Unir pestañas** en la barra superior (o `Sesión → Convertir todas las pestañas en
paneles`) y después elige `Diseño → Dos en paralelo`. Si eliges un diseño con varias
pestañas abiertas, RNCli también te ofrece esa conversión automáticamente.

En enfocar con `Alt+←` / `Alt+→`, el panel activo siempre entra en el diseño visible.

### Difusión (una orden para todos)
`Ctrl+Shift+B` activa la difusión `⇢`: todo lo que escribas se envía **también** a los
demás paneles de la pestaña. Útil para pedir lo mismo a varios agentes a la vez y
comparar respuestas. Se desactiva con el mismo atajo.

### Panel de escritura rápido
La barra de abajo envía texto al panel activo con `Enter`, y con `Ctrl+Enter` lo manda a
todos (sin necesidad de activar la difusión).

### Explorador de carpetas

El panel **Carpetas** aparece a la izquierda y se puede arrastrar a la derecha, cerrar o
volver a abrir desde `Ver → Carpetas` / el botón `📁 Carpetas`.

* Selecciona una carpeta y pulsa **Asignar al terminal activo**.
* Doble clic en una carpeta la asigna directamente al terminal activo.
* Arrastra una carpeta desde el árbol y suéltala encima de cualquier terminal para
  asignarla a ese agente concreto.
* Al cambiar de directorio, el agente se reinicia en esa carpeta: un proceso ya
  ejecutándose no puede cambiar su `cwd` de forma segura desde fuera.
* **＋ Nuevo panel aquí** abre el selector de agentes con esa carpeta ya seleccionada.

### Otros atajos
| Atajo | Acción |
|-------|--------|
| `Ctrl+W` / `Ctrl+Shift+W` | Cerrar panel / pestaña |
| `F2` | Renombrar pestaña |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Pestaña siguiente / anterior |
| `Ctrl+Shift+C` / `Ctrl+Shift+V` | Copiar / pegar |
| **Ctrl derecho** | Host Key tipo VirtualBox: libera el foco de la terminal y activa los atajos de RNCli |
| `Shift+PageUp` / `Shift+PageDown` | Historial de la terminal (también la rueda) |
| `Ctrl+Shift+R` | Reiniciar el agente activo (`Enter` en una terminal terminada) |
| `Ctrl++` / `Ctrl+-` / `Ctrl+0` | Tamaño de letra |
| `F11` | Pantalla completa |
| `F1` | Todos los atajos |
| `Ctrl+Q` | Salir (cierra también los agentes) |

## Instalación en el menú de aplicaciones

```bash
./install.sh     # crea el .desktop y el icono en ~/.local/share
```

Después aparecerá como **RNCli** en el menú de tu escritorio.

## Agentes y claves de API

La configuración vive en `~/.config/rncli/config.json` (botón **⚙ → Abrir config.json**,
que copia la ruta al portapapeles). Formato:

```json
{
  "agents": [
    {
      "id": "gemini",
      "name": "Gemini CLI",
      "command": ["gemini"],
      "emoji": "✦",
      "color": "#38bdf8",
      "description": "Gemini CLI de Google",
      "cwd": "",
      "env": { "GEMINI_API_KEY": "tu_clave_aquí" }
    }
  ],
  "settings": { "theme": "oscuro", "font_size": 11, "default_layout": "1" }
}
```

* `command` acepta lista (`["opencode","--model","sonnet"]`) o cadena.
* `env` sirve para claves de API: `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `CURSOR_API_KEY`,
  `OPENAI_API_KEY`… Lo normal es que las tengas ya en tu `~/.bashrc`; RNCli hereda el
  entorno y solo añade lo que pongas aquí.
* Añade tus propios agentes duplicando un bloque y cambiando `id` (también vale
  `{"name": "...", "command": "mi-cli --flag"}` con solo esos dos campos).

### Si un agente «no se encuentra»
RNCli lanza los agentes con el **PATH real de tu shell** (el de `~/.bashrc`, `~/.profile`,
etc.), aunque abras el programa desde el menú de aplicaciones, donde ese PATH no existe.
Además busca en los directorios típicos (`~/.opencode/bin`, `~/.pi/agent/bin`,
`~/.local/bin`, `~/.bun/bin`, `~/.cargo/bin`…). El PATH detectado se escribe en
`~/.config/rncli/rncli.log` para poder comprobarlo.

Si aun así no lo encuentra, pon la ruta absoluta en el agente:

```json
{ "id": "opencode", "name": "OpenCode", "command": ["/home/ramon/.opencode/bin/opencode"] }
```

## Sesión y ajustes

* **Ajustes** (⚙): fuente, tamaño, tema (Oscuro/Dracula/Claro), líneas de historial,
  diseño inicial, agente por defecto, carpeta inicial, cursor parpadeante y
  «recordar sesión al reiniciar» (pestañas, paneles, agentes y geometría).
* Todo se guarda en `~/.config/rncli/`:
  `config.json` (ajustes y agentes) y `session.json` (sesión, si la activas).
* Si algo va mal, el registro de errores está en `~/.config/rncli/rncli.log`.

## sudo para los agentes

El botón **🔑 sudo** abre un asistente con las estrategias de
[`sudo-config-strategies.md`](sudo-config-strategies.md) resumidas: genera el fragmento
de `sudoers` para tu usuario, lo copia al portapapeles y comprueba con
`sudo -n true` si sudo ya funciona sin contraseña. RNCli **nunca** modifica
`/etc/sudoers`: tú copias el fragmento y lo pegas con `sudo visudo`.

Las dos estrategias recomendadas por el manual para trabajar con agentes son la 1
(`Defaults timestamp_timeout=90`) y la 2 (`NOPASSWD` para comandos concretos).

## Detalles técnicos

* Cada panel es un **pty real** (`_spawn.py` hace `setsid()` + `TIOCSCTTY` + `execvp`),
  así que Ctrl+C, Ctrl+Z, `SIGWINCH` al redimensionar y las TUI funcionan igual que en
  una terminal normal.
* Los agentes se lanzan con el PATH del usuario y con `PR_SET_PDEATHSIG`: si RNCli se
  cierra (incluso con `kill -9`), ningún agente se queda huérfano.
* El emulador usa **pyte** y se dibuja con `QPainter` (rejilla de celdas, 16 colores,
  256 colores y *truecolor*, negrita, cursiva, subrayado, tachado, reverse, cursor
  parpadeante, historial de miles de líneas).
* pyte no entiende las secuencias CSI con prefijo privado que usan las TUI modernas
  (`ESC [ > 4 ; 1 m` para modifyOtherKeys, o los informes de ratón `ESC [ < …`), y las
  interpretaba como SGR (subrayado/negrita en toda la pantalla). RNCli las filtra antes
  de alimentar al emulador (`TerminalWidget.sanitize`).
* La distribución de paneles usa `QSplitter`, así que **puedes arrastrar los bordes**
  para dar más espacio a un agente.
* Datos que llegan de los agentes se tratan como texto: RNCli no interpreta su
  contenido, solo lo pinta.

### Limitaciones conocidas

* No se envían eventos de ratón a las TUI (pyte no implementa el protocolo); el ratón
  se usa para seleccionar texto, pegar (botón central) y desplazar el historial.
* No hay soporte de imágenes (sixel/kitty graphics).
* Los atajos con `Alt` son de RNCli, así que no llegan a los agentes.

### Host Key tipo VirtualBox

Cuando una TUI tiene el foco, sus atajos tienen prioridad: por ejemplo, `Ctrl+T` de
OpenCode y `Shift+Tab` de Pi llegan al agente y no los roba RNCli. Pulsa **Ctrl derecho**
solo cuando quieras usar los atajos del chasis (`Ctrl+W`, `Ctrl+Shift+T`, `Ctrl+Tab`,
`Alt+2`, etc.). Eso activa `MODO RNCli`; haz clic en cualquier terminal para volver a
escribir en ella.

### La pantalla «New session» de OpenCode

La pantalla con `New session`, `Ask anything...` y el logo de OpenCode pertenece al
**propio OpenCode**, no a RNCli. Cada panel lanza una instancia real e independiente
de OpenCode, por eso cada uno puede mostrar su propia pantalla inicial. Escribe en ese
panel y pulsa Enter, como en OpenCode normal; RNCli solo proporciona la ventana, las
pestañas y el mosaico alrededor.

## Estructura del proyecto

```
rncli/
├── __main__.py      # entrada: python -m rncli
├── window.py        # ventana principal: pestañas, menús, atajos, estados
├── layouts.py       # diseños 1 / 2v / 2h / 4 / 6 / todos y difusión
├── pane.py          # panel = cabecera + terminal
├── terminal.py      # emulador VT100 (pyte) + pintado + entrada + historial
├── pty_session.py   # pty no bloqueante con QSocketNotifier
├── _spawn.py        # setsid + TIOCSCTTY + execvp (helper de arranque)
├── agents.py        # perfiles de agentes (opencode, pi, cursor, claude, gemini, shell)
├── shell_env.py     # PATH real del usuario y búsqueda de ejecutables
├── config.py        # config.json y session.json
├── dialogs.py       # selector de agentes, ajustes, atajos y asistente de sudo
├── theme.py         # temas Oscuro / Dracula / Claro
run.sh               # arranque con venv automático
install.sh           # entrada en el menú de aplicaciones
tests/smoke_test.py  # 32 comprobaciones sin pantalla
```

## Pruebas

```bash
.venv/bin/python tests/smoke_test.py --screenshot /tmp/rncli.png   # funcionalidad (32)
.venv/bin/python tests/desktop_env_test.py                        # arranque desde el menú
./tests/cierre_test.sh                                            # sin agentes huérfanos
```

* `smoke_test.py` comprueba que los paneles arrancan, que la terminal interpreta color y
  salida real, los diseños, la difusión (una orden ejecutada de verdad en otro panel), el
  historial, el portapapeles, el guardado y la restauración de la sesión, los ajustes en
  caliente y los fragmentos de sudo. En total 32 comprobaciones.
* `desktop_env_test.py` lanza RNCli con un PATH mínimo (como hace el escritorio) y
  verifica que encuentra `opencode`, `pi`, `git`… y que la TUI de opencode arranca.
* `cierre_test.sh` arranca la aplicación, toma su PID real de la ventana X11 y comprueba
  que al cerrarla (SIGTERM y `kill -9`) no queda ningún agente vivo.

[pyte]: https://github.com/selectel/pyte
