# Custom Vision One MCP Server

Servidor [MCP (Model Context Protocol)](https://modelcontextprotocol.io) que expone la API de **Trend Micro Vision One** (y VirusTotal / Slack) como herramientas para agentes de IA. Construido con [FastMCP](https://gofastmcp.com).

> Este es uno de los dos componentes del monorepo. El otro es el **harness SOC para OpenCode** (orquestador de agentes que consume este MCP). Este README cubre **solo el servidor MCP** (`mcp_server/`).

---

## Características

- 🔐 **Seguro por defecto** — la contención no se expone salvo opt-in explícito y exige aprobación humana por acción; validación anti-inyección en `TMV1-Filter` y rutas; enmascaramiento de errores; auditoría JSON de todo lo que cambia estado.
- 🧱 **Estable** — errores upstream traducidos a `ToolError` con mensajes limpios, reintentos con backoff exponencial, paginación acotada.
- ⚡ **Rápido** — cliente `httpx` con pooling de conexiones y HTTP/2 (autodetectado).
- 📈 **Escalable** — código modular, salida estructurada con Pydantic, transporte configurable (stdio / HTTP).
- 🎛️ **Configurable sin sorpresas** — se activan/desactivan tools por variable de entorno, las integraciones sin credenciales se deshabilitan solas, y una configuración mal escrita no arranca en vez de fallar en silencio.

---

## Inicio rápido

El proyecto usa [`uv`](https://docs.astral.sh/uv/). **No se requiere Python instalado**: `uv` descarga la versión correcta automáticamente. Desde la raíz del repo:

```bash
# Linux / macOS
./setup.sh

# Windows (PowerShell)
./setup.ps1
```

El script: instala `uv` si falta → provisiona Python → crea el entorno virtual (`mcp_server/.venv`) → instala dependencias → crea `mcp_server/src/.env` desde el ejemplo.

Después basta con editar `mcp_server/src/.env` con las credenciales. OpenCode arranca el servidor automáticamente; o manualmente:

```bash
uv run --directory mcp_server python src/custom_vo_mcp.py
```

<details>
<summary>Instalación manual (sin los scripts)</summary>

```bash
uv sync --directory mcp_server
cp mcp_server/src/.env.example mcp_server/src/.env
```

¿Hace falta un `requirements.txt` (p. ej. para un entorno solo-pip)? Se genera desde el lockfile, así nunca se desincroniza:

```bash
uv export --directory mcp_server --no-hashes -o requirements.txt
```
</details>

> `httpx[http2]` instala `h2` y habilita HTTP/2 automáticamente. Si `h2` no está, el servidor usa HTTP/1.1 sin fallar.

---

## Configuración

Toda la configuración es por variables de entorno (o un archivo `.env` junto a `src/`). **Todas las credenciales son opcionales**: el servidor siempre arranca y solo se habilitan los tools cuyas credenciales estén presentes.

### Credenciales (opcionales)

| Variable | Habilita | Tools |
|---|---|---|
| `VO_REGION` + `VO_API_KEY` | Vision One | alertas, endpoints, respuesta |
| `VT_API_KEY` | VirusTotal | `get_ioc_reputation` |
| `SLACK_WEBHOOK_URL` | Slack | `send_slack_summary` |

`VO_REGION` es la URL base regional de la API (ej. `https://api.xdr.trendmicro.com`).

### Transporte

| Variable | Default | Descripción |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` (local) o `http` (remoto) |
| `MCP_HTTP_HOST` | `127.0.0.1` | Host para transporte HTTP |
| `MCP_HTTP_PORT` | `8000` | Puerto para transporte HTTP |

### Activación de tools

| Variable | Efecto |
|---|---|
| `MCP_ENABLED_TOOLS` | **Allowlist** (CSV). Si se define, SOLO esos tools quedan activos. |
| `MCP_DISABLED_TOOLS` | **Denylist** por nombre (CSV). |
| `MCP_DISABLED_TAGS` | Deshabilita categorías completas (CSV). Tags válidos: por integración `alerts`, `endpoints`, `response`, `intel`, `notify`, `meta`; por acceso `read`, `write`, `destructive`. |

**Precedencia:** denylists > allowlist > gates de seguridad. Los gates van último y siempre ganan: un
tool sin su credencial, o una destructiva sin `MCP_ENABLE_DESTRUCTIVE`, no se puede forzar a activo
desde la allowlist.

> Un nombre de tool o un tag que no existe es un **error de arranque**, no una regla que no filtra
> nada. `MCP_DISABLED_TAGS=destructiv` no arranca en lugar de hacer creer que el servidor quedó
> cerrado, y el mensaje lista los valores válidos.

### Otras

| Variable | Default | Descripción |
|---|---|---|
| `MCP_ENABLE_DESTRUCTIVE` | `false` | Las tools de contención **no se exponen** hasta activarlas a propósito. |
| `MCP_REQUIRE_APPROVAL` | `true` | Qué hacer cuando el cliente **no** puede ser preguntado: `true` rechaza la acción, `false` acepta el gate del cliente (auditado). Un cliente que sí soporta elicitation se pregunta siempre. |
| `MCP_AUDIT_LOG_FILE` | — | Archivo rotado (JSON lines) para la traza de auditoría. Recomendado en producción. |
| `MCP_LOG_LEVEL` | `INFO` | Nivel de logging (a stderr). |
| `MCP_MASK_ERROR_DETAILS` | `true` | Oculta detalles internos de errores al cliente. |
| `MCP_ENABLE_HTTP2` | `true` | Usa HTTP/2 si `h2` está instalado. |
| `VT_BASE_URL` | `https://www.virustotal.com/api/v3` | Base URL de VirusTotal. |

> Ajuste fino opcional del cliente HTTP: `CONNECT_TIMEOUT`, `REQUEST_TIMEOUT`, `MAX_CONNECTIONS`, `MAX_KEEPALIVE_CONNECTIONS`, `MAX_RETRIES`, `BACKOFF_BASE`, `BACKOFF_MAX`, `MAX_PAGES`.

### Ejemplo `.env`

```env
VO_REGION=https://api.xdr.trendmicro.com
VO_API_KEY=tu_api_key
VT_API_KEY=tu_vt_key
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX

# Habilitar contención (por defecto está apagada). Ver "Seguridad".
MCP_ENABLE_DESTRUCTIVE=true
```

Ver [`src/.env.example`](src/.env.example) para el listado completo y comentado.

---

## Ejecución

```bash
# stdio (default) — para integración local con un cliente MCP / OpenCode
uv run --directory mcp_server python src/custom_vo_mcp.py

# HTTP (remoto)
MCP_TRANSPORT=http MCP_HTTP_PORT=8000 uv run --directory mcp_server python src/custom_vo_mcp.py
```

### Integración con OpenCode

Ya configurado en `.opencode/opencode.json` (raíz del monorepo). El comando usa `uv run`, por lo que es **independiente de la ruta de instalación** — funciona en cualquier máquina con `uv` en el `PATH`, sin reescribir rutas absolutas:

```json
{
  "mcp": {
    "custom-vision-one-mcp-server": {
      "type": "local",
      "command": ["uv", "run", "--directory", "mcp_server", "python", "src/custom_vo_mcp.py"],
      "enabled": true
    }
  }
}
```

---

## Tools disponibles

| Tool | Categoría | Tipo | Descripción |
|---|---|---|---|
| `get_server_capabilities` | meta | lectura | Reporta integraciones activas/inactivas y tools disponibles. |
| `get_risk_index` | alerts | lectura | Índice de riesgo de seguridad (ASRM). |
| `get_alert_list` | alerts | lectura | Lista alertas Workbench abiertas (últimos N días). |
| `get_alert_details` | alerts | lectura | Detalle completo de una alerta. |
| `modify_alert_status` | alerts | escritura | Cambia el estado de una alerta. |
| `add_alert_note` | alerts | escritura | Agrega una nota técnica a una alerta. |
| `get_observed_attack_techniques` | endpoints | lectura | Eventos OAT de un endpoint. |
| `get_endpoint_details` | endpoints | lectura | Detalle de un endpoint. |
| `isolate_endpoint` | response | ⚠️ destructiva | Aísla un endpoint de la red. |
| `add_to_block_list` | response | ⚠️ destructiva | Agrega un IOC a la lista de bloqueo. |
| `get_ioc_reputation` | intel | lectura | Reputación de un IOC vía VirusTotal. |
| `send_slack_summary` | notify | escritura | Envía un resumen a Slack. |

> Las tools ⚠️ destructivas **no aparecen** hasta poner `MCP_ENABLE_DESTRUCTIVE=true`. Una vez
> expuestas, pasan por el gate de `approval.py` y aceptan `dry_run=true` para previsualizar sin
> ejecutar. `get_server_capabilities` reporta en su campo `containment` si están activas y **quién**
> aprueba, para que un orquestador no planifique una contención que no va a poder ejecutar.

---

## Arquitectura

```
src/
├── custom_vo_mcp.py   # Entry point: logging + selección de transporte
├── app.py             # build_server(): lifespan, gating, registro de tools
├── config.py          # Settings (pydantic-settings) + validación
├── capabilities.py    # Mapa integración → credencial → tags (fuente única)
├── context.py         # AppContext (recursos compartidos)
├── http_client.py     # VisionOneClient: retries, backoff, errores→ToolError
├── filters.py         # Sanitización TMV1-Filter + validadores compartidos
├── tags.py            # Vocabulario cerrado de tags (integración + acceso)
├── approval.py        # Gate human-in-the-loop para acciones destructivas
├── audit.py           # Traza JSON de toda acción que cambia estado
├── _dates.py          # Helpers de fechas
└── tools/             # Una CARPETA por tool, autodescubierta al arrancar
    ├── _hints.py            # read_only() / write() / destructive() / meta_read()
    ├── _template/           # Scaffolding para copiar (los `_*` no se registran)
    ├── get_alert_list/      # tool.py (+ models.py / validators.py opcionales)
    ├── isolate_endpoint/
    └── ...                  # una carpeta por cada tool de la tabla anterior
```

Los modelos de salida y los validadores específicos viven **dentro de cada tool**; en `filters.py`
solo queda lo que comparten dos o más. Ver [`src/tools/README.md`](src/tools/README.md) para el
contrato completo (hints, tags, proyección de campos, validación).

### Agregar una tool nueva

1. Copiar `tools/_template/` a `tools/<nombre_snake_case>/` (la carpeta se llama igual que la tool).
2. Implementar `tool.py` con su `register(mcp)` y declarar qué hace en una sola línea:

   ```python
   @mcp.tool(**read_only("alerts"))        # lectura sobre Vision One
   @mcp.tool(**write("alerts", idempotent=True))
   @mcp.tool(**destructive("response"))    # contención: requiere aprobación humana
   @mcp.tool(**meta_read())                # diagnóstico, no sale a ningún sistema
   ```

   Esa llamada emite **a la vez** las anotaciones MCP que ve el cliente y los tags que gatea este
   servidor. Se declaran juntas a propósito: si pudieran discrepar, una tool de contención podría
   anunciarse como destructiva al cliente y a la vez escaparse del gating del servidor. Hay un test
   que lo verifica para todas las tools registradas.
3. Añadirla a `EXPECTED_TOOLS` en `tests/test_discovery.py`.

No hay lista central que editar: `tools/__init__.py` descubre cualquier subpaquete que exponga
`register(mcp)` (y aísla fallos: una tool rota se loguea y se omite, el servidor sigue arriba).

### Agregar una integración nueva

Añadir una entrada `Capability(name, env_vars, tags, is_configured)` en `capabilities.py` y usar su
tag en las tools. El gating por credenciales y `get_server_capabilities` se actualizan solos.

---

## Pruebas

La suite de `tests/` es hermética: no necesita red ni credenciales.

```bash
uv sync --group dev                      # instala pytest / ruff / mypy
uv run pytest                            # toda la suite
uv run pytest tests/test_approval.py     # un archivo
uv run ruff check src tests              # lint
uv run ruff format --check src tests     # formato
uv run mypy src tests                    # tipos
```

---

## Seguridad

**Acciones destructivas.** `destructiveHint` es solo metadata: le avisa al cliente, no lo obliga a
nada. Por eso el gate real está en capas independientes:

1. **No existen por defecto.** Sin `MCP_ENABLE_DESTRUCTIVE=true` las tools de contención no se
   registran, así que una instalación nueva no puede aislar ni bloquear nada. Esto se aplica
   *después* de la política de tools, igual que el gating por credenciales: una allowlist no puede
   resucitar lo que el operador nunca habilitó.
2. **Aprobación humana por acción** (`approval.py`). El servidor detecta en el handshake si el
   cliente soporta elicitation:
   - **Sí** → el servidor pregunta él mismo, siempre, sin importar la configuración. Declinar,
     cancelar o responder fuera de schema rechaza la acción.
   - **No** → con `MCP_REQUIRE_APPROVAL=true` (default) se **rechaza**; con `false` se acepta el
     gate del cliente y cada llamada queda auditada como `approval_delegated`.
   No hay camino donde "no se pudo preguntar" derive en "se ejecutó".
3. **Exposición.** `MCP_AUTH_TOKEN` para que en HTTP no sean alcanzables sin token.

> OpenCode no implementa elicitation (verificado en agosto de 2026 contra OpenCode 1.18), así que un
> harness sobre OpenCode necesita `MCP_REQUIRE_APPROVAL=false` **y** su propio gate; en este repo lo
> fuerza por código `.opencode/plugins/harness-guard.js` vía el hook `permission.ask`, no solo por
> config.

**Auditoría.** Toda acción que cambia estado (respuesta, estado de alerta, notas, Slack) emite una
línea JSON en el logger `vo_mcp.audit`: `attempt` y luego `success`/`error`, más los veredictos del
gate (`approved`, `approval_denied`, `approval_unavailable`, `approval_delegated`). Del contenido
solo se registra el tamaño, nunca el texto. Con `MCP_AUDIT_LOG_FILE` la traza va a su propio archivo
rotado, fuera del log de aplicación.

**Secretos y errores.** Las credenciales reales nunca se commitean: `src/.env` es un placeholder y los
secretos se inyectan en runtime. Los detalles internos de error se enmascaran al cliente por defecto
(`MCP_MASK_ERROR_DETAILS=true`) y solo quedan en los logs (stderr).

---

## Licencia

Apache 2.0 — ver [LICENSE](../LICENSE). Copyright 2026 Danilo Peña.

Custom Vision One MCP Server — by Danilo Peña.
