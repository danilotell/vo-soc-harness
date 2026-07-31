# AGENTS.md — Mapa de navegación para agentes de IA

## 1. Mapa del repositorio

| Archivo / carpeta              | Qué contiene                                                    | Cuándo leerlo                           |
|--------------------------------|-----------------------------------------------------------------|-----------------------------------------|
| `workbench_list.json`          | Lista de alertas sin gestionar en Vision One                                        | Siempre, al empezar |
| `progress/current.md`          | Estado de la sesión                                                                 | En caso de que falle la sesión |
| `memory/history.json`          | Historial append-only de alertas gestionadas                                        | Si necesitas contexto histórico |
| `context/alert_context.json`   | Contexto global de gestión de la alerta                                             | durante la gestión |
| `docs/references/template_*`   | Plantillas .json para outputs de subagentes y para reportes                                           | durante la gestión |
| `docs/references/seed_*`       | Forma canónica vacía de los archivos de estado (son runtime, no se versionan)                        | al cerrar una sesión |
| `docs/reports/templates/soc_report.html`     | Plantilla del reporte. La aplica `scripts/render_report.py`, NO la copies a mano     | nunca |
| `docs/reports/outputs/*.html`  | Reportes generados por el renderizador                                              | durante la gestión |
| `.opencode/agents/*`           | Definiciones de agentes y subagentes (SOC, Tier1, Tier2, Tier3, Notifier) | Si orquestas la gestión |
| `.opencode/commands/*`         | Comandos disponibles para el agente                                                 | `7x24.md` (el preflight) al inicio de cada sesión; el resto nunca |
| `.opencode/plugins/*`          | Plugins disponibles para los agentes                                                | nunca |
| `scripts/*`                    | Utilidades del harness: validar el estado y renderizar el reporte                   | si algo falla al validar |
| `mcp_server/src/*`             | Código de Custom Vision One MCP                                                     | nunca |


## 2. Reglas duras (no negociables)

- SIEMPRE (OBLIGATORIO) cada subagente tiene su propio `*.md` y es muy importante que lo lea y haga estrictamente lo que dice, es decir, no quiero que resumas lo que debe hacer cada subagente, `SOC` delega y `Tier1` o `Tier2` o `Tier3` o `Notifier` lee y entiende qué es lo que debe hacer.
- NUNCA ejecutar acciones de respuesta desde ningún agente o subagente sin autorización y aprobación del **USUARIO** "Humano". Esa autorización **se registra, no se recuerda**: el `SOC` la obtiene y la escribe en `responses.authorization` de `context/alert_context.json` antes de delegar, y el `Tier3` se niega a ejecutar si no está. Lo ejecutado se cruza contra `approved_actions`, así que el registro no es una formalidad: es lo que habilita la ejecución.
- SI no encuentras un archivo valida correctamente, ya que todo lo que se te ha dado debe estar, en caso de no encontrar algo usa la herramienta `bash` con comando pwd y la herramienta `read` para ubicarte bien respecto al repositorio.
- Los archivos de estado (`workbench_list.json`, `context/alert_context.json`, `memory/history.json`) se escriben SIEMPRE completos con `write` y respetando la forma de `docs/references/seed_*.json`. NUNCA los dejes vacíos ni los edites parcialmente con `edit`: una escritura que rompe la forma se rechaza indicándote el campo exacto.
- Las plantillas de `docs/references/*.json` declaran el MÍNIMO: esos campos tienen que estar. Puedes AGREGAR campos propios dentro de una sección cuando observaste algo que no encaja en ninguno — se aceptan y el reporte los muestra —, pero NUNCA crees una sección nueva de primer nivel en `context/alert_context.json` ni quites un campo declarado.
- El reporte HTML lo genera `scripts/render_report.py`, nunca un agente escribiendo HTML: el mismo contexto tiene que producir siempre el mismo documento.
- **Las notas de Vision One las firma el servidor**, no el agente: `add_alert_note` le agrega el `operator_id` del `.env` antes de enviarla, así que toda nota nombra a un responsable. NO agregues tu propia línea de firma ni inventes un autor — el "Agente: Tier N" que sí escribe dice qué rol la generó, no quién responde por ella.
- NUNCA inventes un dato. Todo valor tiene que venir de la respuesta de una tool o de un archivo que hayas leído. Para lo que no puedas obtener usa uno de estos tres marcadores, nunca un valor plausible:
  - `"N/A"` -> el campo no aplica a esta alerta.
  - `"NOT_COLLECTED"` -> el paso que lo habría obtenido no se ejecutó (por ejemplo, la tool no está en `active_tools`).
  - `"UNAVAILABLE"` -> se intentó obtenerlo y la tool falló.
  Un hueco declarado es información útil; un hueco rellenado es un dato falso que el resto del flujo va a tratar como real. Copiar los valores de ejemplo de las plantillas (`WB-9002-...`, `HOST-01`, `sender@example.com`, `"..."`) también cuenta como inventar: la escritura queda rechazada.
- Las claves de los archivos de estado son `snake_case`, siempre. Si necesitas agregar un campo, sigue esa convención: el reporte es una plantilla Jinja y una clave con espacios o mayúsculas fuerza acceso por corchetes y se despega de los prompts que la referencian.

## 3. Mecánica del cliente (OpenCode)

Esta sección es lo único que depende del cliente de IA que corre el harness. Si algún día se migra a
otro, es lo que hay que reescribir; el resto de este archivo y los `.md` de los agentes describen el
trabajo del SOC y no cambian.

- Los comandos de `bash` que aparecen en los `.md` se ejecutan **tal cual, uno por vez**. NO les antepongas `cd` (ya se ejecuta desde la raíz del repositorio) y NO los encadenes: `&&` no es válido en PowerShell y este repo se usa igual en Windows, Linux y macOS. Un comando por llamada funciona en los tres.
- Para preguntarle algo al usuario se usa la herramienta `question`. **Solo el `SOC` la tiene**: OpenCode la deniega por defecto y `.opencode/opencode.json` la habilita únicamente en `agent.SOC.permission`. En los subagentes queda denegada por config, no solo por prompt — así que "un subagente nunca habla con el usuario" es algo que el cliente hace cumplir. Si un subagente necesita algo del usuario, vuelve al `SOC` y se lo dice.
- Al llamar una tool destructiva, OpenCode pide confirmación al humano. Eso es el segundo gate y es correcto: no intentes evitarlo ni reintentar para esquivarlo.
- NUNCA modifiques `mcp_server/` ni leas ningún `.env`: está bloqueado por `permission` en `.opencode/opencode.json` y por el plugin `.opencode/plugins/harness-guard.js`. Si necesitas ver la configuración del MCP, lee `mcp_server/src/.env.example`. Si un cambio en el servidor MCP hace falta, pídeselo al **USUARIO**.