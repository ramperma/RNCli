# Estrategias de Configuración de `sudo` para Pi Coding Agent

Documentación completa de todas las formas de habilitar la ejecución de comandos con `sudo` en el Pi Coding Agent, ordenadas de menor a mayor riesgo de seguridad.

---

## Tabla Rápida

| # | Estrategia | Seguridad | Complejidad | Uso Ideal |
|---|-----------|-----------|-------------|-----------|
| 1 | `timestamp_timeout` largo | Alta | Mínima | Uso general diario |
| 2 | `NOPASSWD` comandos específicos | Muy alta | Baja | Servicios, paquetes, Docker |
| 3 | `NOPASSWD` scripts específicos | Muy alta | Baja | Automatizaciones propias |
| 4 | Extensión con whitelist en código | Máxima | Media | Control granular + auditoría |
| 5 | `sshpass` con contraseña en disco | Baja | Media | Acceso remoto automatizado |
| 6 | `sudo -S` con contraseña en variable de entorno | Baja | Baja | Scripts temporales |
| 7 | `sudoedit` para archivos de sistema | Alta | Baja | Editar configs como root |
| 8 | Sudoers con `runas_spec` restringido | Muy alta | Media | Ejecutar como otro usuario |

---

## 1. Timeout Largo del Cache de Sudo

### Qué hace
Mantiene la contraseña de `sudo` cacheada durante X minutos. Después del primer `sudo`, no pide contraseña de nuevo hasta que expire el timeout.

### Configuración
```bash
sudo visudo
```

Agregar al archivo:
```
Defaults timestamp_timeout=60
```

### Niveles
| Valor | Comportamiento |
|-------|---------------|
| `0` | Pide contraseña SIEMPRE (más seguro) |
| `1-120` | Minutos de cache |
| `-1` | Nunca pide contraseña (mismo que NOPASSWD, menos explícito) |
| `99` | 99 minutos (máximo recomendado) |

### Pros y Contras
- ✅ Muy seguro, la contraseña nunca se expone
- ✅ Simple, configuración nativa de sudo
- ✅ Funciona con cualquier comando
- ⚠️ Sigue pidiendo contraseña después del timeout
- ⚠️ Si cierras la sesión, el cache se pierde

### Recomendación
**60-90 minutos** para uso en servidor local durante la jornada laboral.

---

## 2. NOPASSWD para Comandos Específicos (RECOMENDADA)

### Qué hace
Permite ejecutar **solo ciertos comandos** sin contraseña. Todo lo demás sigue pidiendo contraseña.

### Configuración
```bash
sudo visudo
```

Agregar (cambia `ramon` por tu usuario):
```
# ============================================
# Pi Coding Agent - Comandos sin contraseña
# ============================================
ramon ALL=(ALL) NOPASSWD: /usr/bin/apt-get update
ramon ALL=(NULL) NOPASSWD: /usr/bin/apt-get install *
ramon ALL=(NULL) NOPASSWD: /usr/bin/apt-get upgrade *
ramon ALL=(NULL) NOPASSWD: /usr/bin/apt-get remove *
ramon ALL=(root) NOPASSWD: /usr/bin/systemctl start *
ramon ALL=(root) NOPASSWD: /usr/bin/systemctl stop *
ramon ALL=(root) NOPASSWD: /usr/bin/systemctl restart *
ramon ALL=(root) NOPASSWD: /usr/bin/systemctl reload *
ramon ALL=(root) NOPASSWD: /usr/bin/systemctl status *
ramon ALL=(root) NOPASSWD: /usr/bin/docker *
ramon ALL=(root) NOPASSWD: /usr/bin/certbot *
ramon ALL=(root) NOPASSWD: /usr/bin/chown *
ramon ALL=(root) NOPASSWD: /usr/bin/chmod *
ramon ALL=(root) NOPASSWD: /usr/bin/mkdir *
ramon ALL=(root) NOPASSWD: /usr/bin/touch *
ramon ALL=(root) NOPASSWD: /usr/bin/ln *
ramon ALL=(root) NOPASSWD: /usr/bin/rm *
```

### Patrones soportados
```
/comando            # Solo ese comando exacto
/comando *          # Comando con cualquier argumento
/comando arg1 arg2  # Solo esos argumentos exactos
```

### Pros y Contras
- ✅ Máxima seguridad: solo los comandos que defines
- ✅ Auditables, sabes exactamente qué puede hacer
- ✅ No expone tu contraseña
- ⚠️ Requiere mantenimiento si necesitas nuevos comandos
- ⚠️ Los paths deben ser absolutos

### Comandos útiles típicos

**Sistemas:**
```
/usr/bin/systemctl start *
/usr/bin/systemctl stop *
/usr/bin/systemctl restart *
/usr/bin/systemctl reload *
/usr/bin/systemctl enable *
/usr/bin/systemctl disable *
```

**Paquetes:**
```
/usr/bin/apt-get update
/usr/bin/apt-get install *
/usr/bin/apt-get upgrade *
/usr/bin/apt-get remove *
/usr/bin/dnf install *
/usr/bin/yum install *
```

**Docker:**
```
/usr/bin/docker start *
/usr/bin/docker stop *
/usr/bin/docker restart *
/usr/bin/docker pull *
/usr/bin/docker build *
/usr/bin/docker compose *
```

**Red:**
```
/usr/sbin/iptables *
/usr/sbin/ufw *
/usr/sbin/nginx *
/usr/sbin/apache2 *
```

**Archivos:**
```
/usr/bin/chown root:root *
/usr/bin/chmod 0644 *
/usr/bin/chmod 0755 *
/usr/bin/chmod 0600 *
```

---

## 3. NOPASSWD para Scripts Específicos

### Qué hace
Permite ejecutar scripts propios con `sudo` sin contraseña. Útil para automatizaciones complejas.

### Configuración
```bash
sudo visudo
```

```
ramon ALL=(root) NOPASSWD: /home/ramon/scripts/*
```

### Ejemplo de script seguro
```bash
#!/bin/bash
# /home/ramon/scripts/setup-server.sh

set -e

# Solo operaciones predefinidas
apt-get update -qq
apt-get install -y -qq curl git unzip
systemctl restart nginx
systemctl reload php8.2-fpm

echo "Server setup complete."
```

### Pros y Contras
- ✅ Control total sobre qué hace el script
- ✅ Reutilizable, versionable en git
- ✅ El script puede incluir lógica condicional
- ⚠️ El script debe estar en ubicación controlada
- ⚠️ Verificar permisos del script (solo readable por dueño)

### Estructura recomendada
```
~/scripts/
├── setup-server.sh
├── deploy-app.sh
├── backup-database.sh
├── restart-services.sh
└── README.md          # Documentación de cada script
```

Permisos:
```bash
chmod 750 ~/scripts/
chmod 750 ~/scripts/*.sh
chown $USER:~/scripts/
```

---

## 4. Extensión de Pi con Whitelist en Código

### Qué hace
Crea una herramienta personalizada en pi que valida los comandos antes de ejecutarlos. Máximo control programático.

### Instalación
```bash
# Crear directorio de extensiones
mkdir -p ~/.pi/agent/extensions
```

### Código: `~/.pi/agent/extensions/sudo-helper.ts`
```typescript
interface SudoToolInput {
  command: string;
  description?: string;
}

// Whitelist de patrones permitidos
const ALLOWED_PATTERNS: RegExp[] = [
  // Paquetes
  /^apt-get\s+(update|upgrade|install|remove|purge)\b/,
  /^apt\s+(update|upgrade|install|remove|purge)\b/,
  
  // Sistema
  /^systemctl\s+(start|stop|restart|reload|enable|disable|status)\b/,
  
  // Docker
  /^docker\s+(start|stop|restart|pull|build|run|compose|ps|logs|exec)\b/,
  /^docker-compose\s+(up|down|restart|build|logs)\b/,
  
  // Servidor web
  /^nginx\s+-[gsrt]/,
  /^apache2\s+(start|stop|restart|reload)\b/,
  
  // Certificados
  /^certbot\s+(renew|install|deploy)\b/,
  
  // Permisos de archivos
  /^chown\b/,
  /^chmod\b/,
  
  // Sistema de archivos
  /^mkdir\b/,
  /^rm\b/,
  /^cp\b/,
  /^mv\b/,
  /^ln\b/,
  
  // Firewall
  /^ufw\b/,
  /^iptables\b/,
  
  // Logs
  /^journalctl\b/,
  /^tail\b/,
];

// Comandos PROHIBIDOS (siempre piden contraseña o bloqueados)
const FORBIDDEN_COMMANDS: RegExp[] = [
  /^chmod\s+4755\b/,     // SUID
  /^chmod\s+6755\b/,     // SUID+SGID
  /^chmod\s+2755\b/,     // SGID
  /^visudo\b/,           // No modificar sudoers
  /^passwd\b/,           // No cambiar passwords
  /^useradd\b/,          // No crear usuarios
  /^userdel\b/,          // No borrar usuarios
  /^usermod\b/,          // No modificar usuarios
  /^grub\b/,             // No modificar bootloader
  /^fdisk\b/,            // No particionar discos
  /^mkfs\b/,             // No formatear discos
  /^dd\b/,               // No escribir raw
];

function isCommandAllowed(command: string): { allowed: boolean; reason: string } {
  // Verificar comandos prohibidos primero
  for (const pattern of FORBIDDEN_COMMANDS) {
    if (pattern.test(command)) {
      return { allowed: false, reason: `Command blocked by security policy: ${command}` };
    }
  }

  // Verificar whitelist
  for (const pattern of ALLOWED_PATTERNS) {
    if (pattern.test(command)) {
      return { allowed: true, reason: "Command matches allowed pattern" };
    }
  }

  return { allowed: false, reason: `Command not in whitelist: ${command}. Use: ${ALLOWED_PATTERNS.map(p => p.source).slice(0, 10).join(", ")}...` };
}

export default function (pi) {
  pi.registerTool({
    name: "sudo_run",
    description: "Execute a command with sudo. Only whitelisted commands are allowed.",
    parameters: {
      type: "object",
      properties: {
        command: {
          type: "string",
          description: "The command to execute with sudo",
        },
        description: {
          type: "string",
          description: "Brief description of what this command does (for audit log)",
        },
      },
      required: ["command"],
    },
    handler: async ({ command, description = "" }) => {
      const validation = isCommandAllowed(command);
      
      if (!validation.allowed) {
        return {
          success: false,
          error: validation.reason,
          command: command,
        };
      }

      // Log de auditoría
      const logEntry = `[${new Date().toISOString()}] sudo_run: ${command} | ${description}`;
      console.log(logEntry);

      try {
        const { execSync } = await import("child_process");
        const output = execSync(`sudo -n ${command}`, {
          encoding: "utf-8",
          timeout: 300000, // 5 minutos máximo
        });
        return {
          success: true,
          output: output,
          command: command,
          timestamp: new Date().toISOString(),
        };
      } catch (error: any) {
        return {
          success: false,
          error: error.message,
          command: command,
        };
      }
    },
  });

  pi.registerTool({
    name: "sudo_check",
    description: "Check if a command is allowed by the sudo whitelist without executing it.",
    parameters: {
      type: "object",
      properties: {
        command: {
          type: "string",
          description: "The command to check",
        },
      },
      required: ["command"],
    },
    handler: async ({ command }) => {
      const validation = isCommandAllowed(command);
      return {
        command: command,
        allowed: validation.allowed,
        reason: validation.reason,
      };
    },
  });
}
```

### Pros y Contras
- ✅ Máximo control, whitelist programable
- ✅ Auditoría en logs
- ✅ Herramienta `sudo_check` para probar antes de ejecutar
- ✅ Comandos prohibidos explícitos
- ⚠️ Requiere TypeScript, mantenimiento de código
- ⚠️ Patrones pueden ser complejos de mantener

---

## 5. sshpass con Contraseña en Disco

### Qué hace
Almacena la contraseña en un archivo y la usa automáticamente. **Riesgo alto.**

### Instalación
```bash
sudo apt install sshpass    # Debian/Ubuntu
sudo yum install sshpass    # RHEL/CentOS
```

### Configuración
```bash
echo "tu_contraseña" > ~/.sudo_pass
chmod 600 ~/.sudo_pass      # Solo readable por ti
```

### Uso en el agente
El agente puede ejecutar:
```bash
echo "$(cat ~/.sudo_pass)" | sudo -S apt-get update
```

### Wrapper seguro
```bash
#!/bin/bash
# ~/.local/bin/sudo-auto
# Uso: sudo-auto apt-get update
if [ -z "$1" ]; then
  echo "Usage: sudo-auto <command>"
  exit 1
fi

PASS=$(cat ~/.sudo_pass 2>/dev/null)
if [ -z "$PASS" ]; then
  echo "ERROR: ~/.sudo_pass not found or empty"
  exit 1
fi

echo "$PASS" | sudo -S "$@"
```

```bash
chmod 700 ~/.local/bin/sudo-auto
```

### Pros y Contras
- ✅ Funciona con CUALQUIER comando sudo
- ✅ Sin configurar sudoers
- ⚠️ **Contraseña en disco** (aunque con permisos 600)
- ⚠️ Si alguien accede a tu sesión, tiene la contraseña
- ⚠️ Backups podrían exponer la contraseña

### Nunca hacer esto
```bash
# MALO: contraseña en texto plano en historial
echo "password" | sudo -S command

# MALO: contraseña en variable de entorno exportada
export SUDO_PASSWORD=password
```

---

## 6. Sudo con Contraseña en Variable de Entorno

### Configuración
```bash
# En ~/.bashrc o ~/.zshrc (cuidado, visible con env)
export SUDO_ASKPASS_PASSWORD="tu_contraseña"
```

### Script helper
```bash
#!/bin/bash
# ~/.local/bin/sudo-env
export SSH_ASKPASS=/dev/null
export DISPLAY=:0

echo "$SUDO_ASKPASS_PASSWORD" | sudo -S "$@"
```

### Pros y Contras
- ✅ Rápido de configurar
- ⚠️ Variable visible con `env` o `/proc/self/environ`
- ⚠️ Puede aparecer en logs de shell
- ⚠️ No recomendado para producción

---

## 7. Sudoedit para Editar Archivos de Sistema

### Qué hace
Permite editar archivos como root de forma segura. El editor se ejecuta como root pero solo en archivos específicos.

### Configuración
```bash
sudo visudo
```

```
# Permitir editar archivos de configuración específicos
ramon ALL=(root) NOPASSWD: /usr/bin/sudoedit /etc/nginx/*
ramon ALL=(root) NOPASSWD: /usr/bin/sudoedit /etc/apache2/*
ramon ALL=(root) NOPASSWD: /usr/bin/sudoedit /etc/systemd/system/*
ramon ALL=(root) NOPASSWD: /usr/bin/sudoedit /etc/hosts
ramon ALL=(root) NOPASSWD: /usr/bin/sudoedit /etc/ssh/sshd_config
```

### Uso en el agente
```bash
sudoedit /etc/nginx/nginx.conf
```

### Pros y Contras
- ✅ Seguro, solo edita archivos permitidos
- ✅ No ejecuta código arbitrario
- ✅ Backup automático del archivo original (.orig)
- ⚠️ Solo para edición de archivos, no para ejecución

---

## 8. Runas Spec Restringido

### Qué hace
Permite ejecutar comandos sudo **como otro usuario** (no solo root).

### Configuración
```bash
sudo visudo
```

```
# Ejecutar como usuario 'www-data' sin contraseña
ramon ALL=(www-data) NOPASSWD: ALL

# Ejecutar como usuario 'postgres' sin contraseña  
ramon ALL=(postgres) NOPASSWD: /usr/bin/psql
```

### Uso en el agente
```bash
sudo -u www-data ls /var/www
sudo -u postgres psql -c "SELECT version();"
```

### Pros y Contras
- ✅ Principio de mínimo privilegio (no siempre como root)
- ✅ Útil para servicios específicos
- ⚠️ Más complejo de configurar
- ⚠️ Requiere entender los usuarios del sistema

---

## 9. Combos Avanzados

### Combo 1: Timeout largo + NOPASSWD selectivo
```
# sudoers
Defaults timestamp_timeout=90

# Comandos críticos siempre sin contraseña
ramon ALL=(root) NOPASSWD: /usr/bin/systemctl restart *
ramon ALL=(root) NOPASSWD: /usr/bin/docker *

# El resto usa el cache de timeout
```

### Combo 2: NOPASSWD + Logging
```bash
# sudoers
Defaults log_output
Defaults logfile="/var/log/sudo_pi_agent.log"

ramon ALL=(root) NOPASSWD: /usr/bin/docker *, /usr/bin/systemctl *
```

Cada `sudo` se registra en `/var/log/sudo_pi_agent.log` con timestamp, usuario, comando y IP.

### Combo 3: NOPASSWD + comandos con `sudo -n` explícito
El agente siempre usa `sudo -n` (non-interactive), así si un comando no está en NOPASSWD, falla silenciosamente en vez de pedir password:

```bash
# En el agente:
sudo -n systemctl restart nginx  # Funciona si está en NOPASSWD
sudo -n rm /etc/shadow           # Falla silenciosamente si no está
```

---

## Matriz de Decisiones

```
¿Necesitas ejecutar comandos arbitrarios como root?
├── Sí → ¿Confías completamente en el modelo?
│         ├── Sí → Timeout largo (estrategia 1)
│         └── No → Extensión whitelist (estrategia 4)
│
└── No, solo comandos específicos
    ├── Sí → NOPASSWD selectivo (estrategia 2)
    └── ¿Es para editar archivos?
          └── Sí → Sudoedit (estrategia 7)
```

---

## Checklist de Seguridad

Antes de configurar, verifica:

- [ ] **Audita el sudoers** después de cambiarlo con `visudo -c`
- [ ] **No uses `ALL=(ALL)` con NOPASSWD** sin restricciones de comandos
- [ ] **Usa paths absolutos** en el sudoers
- [ ] **Mantén logs activados** (`log_output` y `logfile`)
- [ ] **Revisa los logs** periódicamente (`journalctl -u sudo` o `sudo -l -U $USER`)
- [ ] **No uses variables de entorno** para contraseñas en producción
- [ ] **Usa `sudo -n`** en scripts para evitar hangs por password prompt
- [ ] **Backs up el sudoers** antes de modificar: `sudo cp /etc/sudoers /etc/sudoers.bak`
- [ ] **Testea con `sudo -l`** para ver los permisos actuales
- [ ] **Cierra la sesión** cuando termines (invalida el cache de sudo)

---

## Comandos de Verificación

```bash
# Ver permisos actuales de sudo
sudo -l

# Verificar sintaxis del sudoers
sudo visudo -c

# Ver logs de sudo
sudo journalctl -u sudo
sudo grep sudo /var/log/auth.log

# Ver comandos permitidos para un usuario
sudo -U tu_usuario -l

# Timeout actual
sudo -V | grep timeout
```

---

## Integración con Pi Agent

### Opción A: Estrategia 1 + 2 (Recomendada para la mayoría)
1. Configura `timestamp_timeout=60` en `/etc/sudoers`
2. Agrega `NOPASSWD` para los comandos que más usas
3. El agente usa `sudo` normalmente

### Opción B: Estrategia 4 (Para control máximo)
1. Crea la extensión `sudo-helper.ts`
2. El agente usa `sudo_run "command"` en vez de `sudo command`
3. La extensión valida antes de ejecutar

### Opción C: Híbrida
1. Timeout largo para uso general
2. Extensión para comandos sensibles
3. NOPASSWD solo para operaciones de infraestructura crítica

---

## Notas Finales

- **Servidor local, LM de confianza**: Estrategia 1 (timeout 60+) es suficiente
- **Servidor multi-usuario**: Estrategia 2 (NOPASSWD selectivo) + logs
- **Producción / alta seguridad**: Estrategia 4 (extensión whitelist) + logs + auditoría
- **Nunca expongas tu contraseña** en variables de entorno o archivos no protegidos
- **Revisa los logs** de sudo periódicamente para detectar actividad sospechosa
