# soc-harness

Un SOC asistido por agentes de IA sobre **Trend Micro Vision One**. Los agentes hacen el triage, la
investigación y la documentación de una alerta; **las acciones de respuesta siempre las autoriza un
humano**, y por defecto no están disponibles.

El repo tiene dos componentes que funcionan juntos:

| Componente | Qué es |
|---|---|
| **Harness SOC** (raíz) | Orquestador de agentes para [OpenCode](https://opencode.ai): prompts, estado en JSON y plantillas de reporte. No es código, son instrucciones. |
| **MCP Server** (`mcp_server/`) | Servidor [MCP](https://modelcontextprotocol.io) que expone Vision One, VirusTotal y Slack como herramientas. Python + [FastMCP](https://gofastmcp.com). Sirve para cualquier cliente MCP, no solo para este harness. |

---

## Aviso importante

Este es un proyecto personal. **No es un producto de Trend Micro (hoy TrendAI), no es oficial y no
cuenta con el respaldo, el patrocinio ni el soporte de la empresa.** Los nombres Trend Micro,
TrendAI y Vision One pertenecen a sus titulares y se usan aquí únicamente para identificar la API
con la que este software se integra.

El software se entrega **tal cual, sin garantía de ningún tipo**, en los términos de la licencia
Apache 2.0. El autor no asume responsabilidad por daños, interrupciones, acciones ejecutadas sobre
una consola de seguridad ni pérdida de datos derivados de su uso. **Al descargar, instalar o
utilizar este repositorio se aceptan estas condiciones y los riesgos que implica.**

Este harness delega decisiones de análisis a modelos de lenguaje. **Un modelo de IA se equivoca**:
puede clasificar mal una alerta, malinterpretar una evidencia o proponer una contención
injustificada. Por eso ninguna acción de respuesta se ejecuta sin autorización humana explícita y
la contención viene deshabilitada por defecto. 

**La revisión de un analista sigue siendo indispensable: este proyecto asiste al SOC, no lo reemplaza.**

>Los IDs de alerta, hostnames e IPs que aparecen en las plantillas de `docs/references/` son de
>ejemplo.

---

## Requisitos

- [**OpenCode**](https://opencode.ai) instalado (es el cliente que corre los agentes).
- Un **proveedor y un modelo configurados en OpenCode** (es el modelo que ejecuta los agentes): se
  configura con la autenticación de OpenCode y su selector de modelo. Ningún agente de este
  repositorio fija un modelo: `SOC` hereda el configurado globalmente y cada subagente hereda el del
  orquestador que lo invoca. Para fijar uno distinto, el campo `model` en el frontmatter de
  `.opencode/agents/<Agente>.md`, o el `model` global de `.opencode/opencode.json`.
- [**uv**](https://docs.astral.sh/uv/) — si no está instalado, el script de setup lo instala.
  **No se requiere Python instalado**: `uv` descarga la versión correcta por su cuenta.
- Una **API key de Vision One** con permisos de lectura sobre Workbench y endpoints. Para las
  acciones de respuesta se requieren además permisos de escritura, pero no son necesarios para empezar.
- Opcional: API key de **VirusTotal** (reputación de IOCs) y un **webhook de Slack** (notificaciones).

---

## Instalación en 3 pasos

```bash
git clone <URL-DE-ESTE-REPO> && cd vo-soc-harness

./setup.sh        # Linux / macOS
./setup.ps1       # Windows (PowerShell)
```

El script instala `uv` si falta, crea el entorno virtual, instala dependencias y deja preparados
`mcp_server/src/.env` y los archivos de estado del harness.

**Paso 2 — cargar las credenciales** en `mcp_server/src/.env`. El mínimo para arrancar son dos líneas:

```env
VO_REGION=https://api.xdr.trendmicro.com
VO_API_KEY=tu_api_key
```

`VO_REGION` es la URL base de la región correspondiente (`api.xdr.trendmicro.com`,
`api.eu.xdr.trendmicro.com`, `api.in.xdr.trendmicro.com`, etc. — figura en la consola de Vision
One). Todo lo demás es opcional y está explicado en [`mcp_server/src/.env.example`](mcp_server/src/.env.example).

**Paso 3 — abrir OpenCode** en la raíz del repo. Levanta el servidor MCP por su cuenta y arranca con
el agente `SOC`, que pregunta cómo se quiere empezar.

```
opencode
```

---

## Qué esperar en la primera sesión

El agente `SOC` arranca preguntando qué se quiere hacer. Al elegir listar alertas, muestra el
workbench pendiente en una tabla ordenada por severidad y score. Al elegir una alerta, el flujo es:

```
SOC ──> Tier1 ──> Tier2 ──> SOC ──> HUMANO (autoriza) ──> Tier3 ──> Notifier
        triage    análisis          human-in-the-loop     respuesta  reporte
```

`SOC` coordina y **no ejecuta trabajo**: delega. Cada subagente tiene su contrato completo en su
propio `.md` dentro de `.opencode/agents/`.

La instalación por defecto llega hasta el análisis, la documentación en la alerta y el reporte HTML.
**`Tier3` no puede contener nada**, porque las acciones destructivas vienen deshabilitadas — ver
[Habilitar la contención](#habilitar-la-contención).

---

## Modelo de seguridad

Este harness le da a un modelo acceso a una consola de seguridad real. El diseño asume que el modelo
puede equivocarse, así que ninguna acción destructiva (`isolate_endpoint`, `add_to_block_list`)
depende del comportamiento correcto del prompt:

1. **Por defecto no existen.** Sin `MCP_ENABLE_DESTRUCTIVE=true` esas tools no se registran. Una
   instalación nueva no puede aislar un equipo ni bloquear un IOC, ni por error ni a propósito.
2. **Aprobación humana por acción.** Cuando están habilitadas, el servidor detecta en el handshake
   MCP si el cliente puede preguntarle a una persona. Si puede, pregunta él mismo y **rechaza** si
   nadie aprueba. Si no puede, `MCP_REQUIRE_APPROVAL=true` (default) rechaza de todos modos; solo
   con `false` se delega el gate al cliente, y cada llamada así queda marcada en la auditoría.
3. **El gate del cliente es *deny-by-default*.** El `permission` map de
   [`.opencode/opencode.json`](.opencode/opencode.json) pone en `ask` a **todas** las tools del
   servidor MCP con una sola línea —`"custom-vision-one-mcp-server_*": "ask"`— y habilita en `allow`
   solo las seguras, una por una. La consecuencia es la propiedad que importa: **una tool destructiva
   que se agregue en el futuro pide confirmación sin que nadie toque la configuración**, porque cae en
   el comodín. Es declarativo y visible: se lee en un archivo, no hay que auditar código para saber
   qué pide permiso.
4. **Y el harness verifica sus propias barreras.** El preflight ejecuta `scripts/check_guard.py`, que
   comprueba dos cosas independientes sobre `.opencode/plugins/harness-guard.js`: que **se comporta**
   como declara (ejercita su hook) y que **está cargado** en esta sesión (lee el marcador que el plugin
   refresca en cada llamada a una tool). Ese plugin no es el gate de aprobación —eso es el punto 3—
   pero es lo que impide que un `.env` se lea con cualquier tool, que se modifique `mcp_server/` y que
   un archivo de estado se escriba fuera de contrato; un plugin que no carga se lleva las tres reglas
   en silencio.
5. **Toda acción es atribuible.** `MCP_OPERATOR_ID` identifica a quien opera el servidor y se estampa
   en cada registro de auditoría, junto con el host y el usuario del sistema operativo. Es
   **obligatorio** para habilitar la contención: sin él el servidor no arranca, porque un registro
   que no puede decir quién autorizó un aislamiento no responde la pregunta para la que existe.
6. **Auditoría de todo lo que cambia estado.** Respuestas, cambios de estado de alerta, notas y
   notificaciones emiten una línea JSON en el logger `vo_mcp.audit`, incluyendo lo que se **rechazó**
   y por qué. Con `MCP_AUDIT_LOG_FILE` va a un archivo rotado aparte.
7. **El harness no puede tocar lo que no le corresponde.** Ni modificar `mcp_server/`, ni leer ningún
   `.env`. Enforced por `permission` en `opencode.json` y por el plugin (Guardrail personalizado).

Además, una configuración mal escrita **no arranca**: un tag o un nombre de tool inexistente en
`MCP_DISABLED_TAGS` / `MCP_DISABLED_TOOLS` es un error de arranque, no una regla que silenciosamente
no filtra nada.

### Habilitar la contención

Para que `Tier3` pueda ejecutar acciones de respuesta, en `mcp_server/src/.env`:

```env
MCP_ENABLE_DESTRUCTIVE=true
MCP_OPERATOR_ID=nombre.apellido
```

Las dos líneas son obligatorias: sin `MCP_OPERATOR_ID` el servidor no arranca, porque toda acción de
contención tiene que quedar atribuida a una persona en la auditoría.

El comportamiento depende del cliente MCP. **OpenCode no implementa elicitation de MCP** (verificado
en agosto de 2026 contra OpenCode 1.18), así que el servidor no puede solicitar la aprobación por sí
mismo y rechaza toda acción destructiva. Para operar con OpenCode se agrega también:

```env
MCP_REQUIRE_APPROVAL=false
```

Con eso el gate pasa a ser el de OpenCode: el `permission` map abre el prompt de confirmación, y el
servidor registra cada llamada como `approval_delegated` para que la postura más débil quede visible
en la auditoría en lugar de ser implícita. Con un cliente MCP que **sí** soporta elicitation, conviene
mantener `MCP_REQUIRE_APPROVAL=true`: en ese caso se solicitan las dos confirmaciones.

El modo activo se verifica pidiéndole al agente que ejecute `get_server_capabilities` y revisando el
campo `containment`.

---

## Cómo está organizado

| Ruta | Contenido | ¿Se versiona? |
|---|---|---|
| `.opencode/agents/*.md` | Definición de cada agente: `SOC`, `Tier1`, `Tier2`, `Tier3`, `Notifier`. | sí |
| `.opencode/plugins/` | Guardrails que no dependen de configuración. | sí |
| `docs/references/template_*.json` | Formato de salida obligatorio de cada subagente. | sí |
| `docs/references/seed_*` | Forma canónica **vacía** de cada archivo de estado. | sí |
| `docs/reports/templates/` | Plantilla Jinja del reporte HTML. | sí |
| `scripts/` | Validación del estado del harness contra las plantillas. | sí |
| `mcp_server/` | El servidor MCP ([README](mcp_server/README.md)). | sí |
| `workbench_list.json` | Cache de alertas abiertas. | **no** |
| `context/alert_context.json` | Alerta en curso. | **no** |
| `memory/history.json` | Histórico de alertas gestionadas. | **no** |
| `progress/current.md` | Estado de la sesión. | **no** |
| `docs/reports/outputs/` | Reportes generados. | **no** |
| `audit/` | Traza de auditoría del servidor MCP, si `MCP_AUDIT_LOG_FILE` está activo. | **no** |

Los seis últimos son **datos de runtime**: los escriben los agentes y el servidor con respuestas
reales de las tools, así que contienen datos del tenant (IDs de alerta, hostnames, IPs internas,
IOCs) y están en `.gitignore`. **No deben commitearse.** Lo que se versiona es su *forma*, en
`docs/references/seed_*`, y el setup la copia.

Los archivos de estado y los directorios los crea el setup, no los agentes: `setup.sh` / `setup.ps1`
copian los cuatro seeds y crean `docs/reports/outputs/` y `audit/`. El directorio del log de
auditoría además se crea solo al arrancar el servidor, así que para habilitar la traza basta con
descomentar una línea en `.env`.

> Al cerrar una gestión los agentes **resetean esos archivos al seed**, no los dejan vacíos: un
> archivo vacío no le dice nada a la próxima sesión y el modelo reinventa la estructura. Además cada
> escritura se valida antes de aterrizar, así que un formato mal queda rechazado en el momento
> indicando el campo exacto.

### Datos inventados

Un modelo obligado a llenar un esquema completo, sin forma aceptable de decir "esto no lo pude
obtener", produce el valor más plausible — y en un SOC eso es un dato falso que el paso siguiente
trata como real. Así que los agentes tienen una salida honesta y explícita:

| Marcador | Significado |
|---|---|
| `N/A` | El campo no aplica a esta alerta. |
| `NOT_COLLECTED` | El paso que lo habría obtenido no se ejecutó (p. ej. la tool no está disponible). |
| `UNAVAILABLE` | Se intentó obtenerlo y la tool falló. |

Un triage con marcadores es un resultado **válido**; el orquestador lo reporta tal cual y no le pide
al subagente que lo complete. Y hay tres controles mecánicos, porque un prompt es solo una intención:

- Antes de ejecutar una tool, el agente verifica que esté en `active_tools` de
  `get_server_capabilities`; si no está, marca `NOT_COLLECTED` en lugar de suponer el resultado.
- Copiar los valores de ejemplo de las plantillas (el ID `WB-9002-…`, `HOST-01`, `sender@example.com`,
  el `"..."`) **rechaza la escritura**: es la forma más común de invención, reproducir el formato que
  se le mostró en lugar de lo que leyó.
- Una acción de respuesta cuyo objeto **no aparece** en el triage ni en el análisis rechaza la
  escritura: contener algo que ningún paso observó es el error más caro de todos.

---

## Desarrollo

El código vive en `mcp_server/`; ver su [README](mcp_server/README.md) para arquitectura y para
agregar tools.

**No se requiere Python instalado, y si lo hubiera no se usa.** Todo pasa por `uv`:
`python-preference = "only-managed"` (en `uv.toml` y en `mcp_server/pyproject.toml`) le dice a uv que
ignore el intérprete del sistema, y `.python-version` fija la versión (3.11, la misma que CI). El
único requisito es `uv`, que instalan `setup.sh` / `setup.ps1`. Por eso ningún comando de este repo se
invoca con `python` a secas.

```bash
uv run --directory mcp_server ruff check src tests
uv run --directory mcp_server ruff format --check src tests
uv run --directory mcp_server mypy src tests
uv run --directory mcp_server pytest                    # sin red ni credenciales

# harness (los mismos comandos que corre el preflight `/7x24`)
uv run --no-project scripts/check_guard.py              # gate de aprobación verificado
uv run --no-project scripts/validate_alert_context.py   # estado vs plantillas
uv run --no-project scripts/validate_alert_context.py --self-test
uv run --with jinja2 --no-project scripts/render_report.py --self-test
node scripts/probe_harness_guard.mjs                    # hooks del plugin (Guardrail)
```

Lo mismo corre en CI (`.github/workflows/ci.yml`) en dos jobs: `check` (servidor MCP) y `harness`
(gate, estado, plantillas, renderizador y plugin).

`probe_harness_guard.mjs` existe porque el plugin es la única pieza que OpenCode carga en runtime: un
error ahí no aparece como un test roto sino como una tool bloqueada en medio de una alerta. Llama a
los hooks reales con argumentos sintéticos y afirma cada decisión.

### El reporte

Lo genera `scripts/render_report.py`, no un agente escribiendo HTML. Eso significa que el mismo
contexto produce siempre el mismo documento, que todo valor se escapa —una descripción de alerta o una
ruta de archivo pueden traer marcado, y las elige el atacante— y que el HTML es **autocontenido**: sin
CDN, sin JavaScript, legible sin red y sin ejecutar código de terceros años después.

**El diseño es fijo; el contenido no.** Las tools devuelven campos distintos entre versiones y un
agente puede agregar un hallazgo que nadie previó, así que el renderizador trabaja en dos capas: las
áreas reconocidas (cabecera, línea de tiempo, indicadores, alcance, entidades, MITRE) mantienen su
maquetación, y **todo lo demás se renderiza de todos modos, con su etiqueta, en el mismo lenguaje
visual**. Agregar un campo lo hace aparecer; quitarlo lo hace desaparecer. Ninguna de las dos cosas
exige tocar la plantilla.

### Usar una plantilla propia

Una plantilla se enlaza al *view model* que arma el renderizador — `report.meta`, `report.timeline`,
`report.indicators`, `report.impact`, `report.mitre`, `report.executed`, `report.extras` — y no al
payload crudo de Vision One. Es un contrato chico y estable: un campo que cambie en el origen no
rompe la plantilla de nadie.

```bash
# verificarla antes de usarla: la renderiza en seco contra un contexto de ejemplo
# que incluye campos y secciones que ninguna plantilla previó
uv run --with jinja2 --no-project scripts/render_report.py --check-template mi_reporte.html

# usarla
uv run --with jinja2 --no-project scripts/render_report.py --template mi_reporte.html
```

`docs/reports/templates/soc_report.html` es la referencia y conviene no editarla, para que un `git
pull` no choque. Las etiquetas y el orden de los campos salen de
[`docs/references/report_labels.json`](docs/references/report_labels.json), que es opcional: un campo
que no esté ahí se renderiza de todos modos, con una etiqueta derivada de su nombre.

---

## Notas para desplegarlo en un SOC

Nada de esto lo impone el repositorio; son las decisiones que quedan del lado de quien lo opera.

- **Un clon por analista.** El estado (`context/alert_context.json`, `workbench_list.json`) es de una
  alerta a la vez. Dos personas sobre el mismo clon entran en conflicto.
- **Fijar una versión.** Anclar un commit y actualizar deliberadamente, en vez de seguir `main`.
- **Auditoría.** `MCP_AUDIT_LOG_FILE` escribe un archivo rotado en `audit/`, con el operador, el host
  y el usuario del sistema en cada registro. El directorio lo crea el setup, así que habilitarla es
  descomentar una línea en `.env`.
- **Mínimo privilegio en las credenciales.** Una API key de solo lectura alcanza para triage, análisis
  y documentación. La key con permisos de respuesta solo hace falta donde se opera la contención, y no
  tiene por qué estar en todas las estaciones.
- **Probar primero contra un tenant de laboratorio**, y habilitar la contención solo cuando el modelo
  de aprobación del cliente MCP en uso se haya comprendido.

---

## Autor

**Danilo Peña** - Subject Matter Expert (SME) en Security Operations (SecOps) en Trend Micro **(TrendAI)**

>Este repositorio es un desarrollo personal, hecho fuera de mis funciones, y no representa a la
>empresa ni compromete su posición (ver [Aviso importante](#aviso-importante)).

## Contacto

- Canal único: [Issues](../../issues), para bugs, preguntas, propuestas y reportes de seguridad.
- [`SECURITY.md`](SECURITY.md) define el alcance de un reporte de seguridad y su contenido.

Los issues son públicos. Censurar IDs de alerta, hostnames, IPs internas, IOCs, usuarios, claves y
URLs de webhook antes de pegar cualquier salida.

## Licencia

Apache 2.0 — ver [LICENSE](LICENSE). Copyright 2026 Danilo Peña.
