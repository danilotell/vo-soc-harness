# Política de seguridad

Este proyecto expone una consola de seguridad real a un modelo de lenguaje. Un fallo puede derivar en
un endpoint aislado sin motivo, un IOC bloqueado por error o datos de un tenant expuestos en un log.
Los reportes de seguridad son bienvenidos.

## Versiones soportadas

No hay releases. El único código soportado es la rama `main`; los reportes se verifican contra el
último commit.

## Cómo reportar

**Para una vulnerabilidad, usar el canal privado:**
<https://github.com/danilotell/vo-soc-harness/security/advisories/new>

Es un aviso de seguridad en borrador, visible solo para quien lo reporta y para el autor. Permite
discutir el hallazgo y coordinar la corrección antes de que sea público, y publicarlo después con
crédito al reportante.

Para un bug que no sea una vulnerabilidad, el canal es un issue:
<https://github.com/danilotell/vo-soc-harness/issues>. Los issues son públicos, así que abrir uno
divulga el contenido en ese momento, sin período de embargo.

### Contenido del reporte

- Commit probado y cliente MCP utilizado.
- Configuración relevante: `MCP_ENABLE_DESTRUCTIVE`, `MCP_REQUIRE_APPROVAL`, `MCP_DISABLED_TAGS` y
  transporte (stdio o HTTP).
- Pasos de reproducción, resultado obtenido y resultado esperado.
- Impacto estimado.

### Datos del tenant

Los IDs de alerta, hostnames, IPs internas, IOCs, nombres de usuario, claves y URLs de webhook se
censuran antes de pegar cualquier salida. Los marcadores del proyecto (`N/A`, `HOST-01`) cumplen la
misma función en un ejemplo. Un reporte con datos reales constituye por sí mismo una filtración.

### Tiempos de respuesta

Proyecto personal, sin SLA. El acuse de recibo se realiza en días. Un reporte sin respuesta a las dos
semanas puede reiterarse en el mismo issue.

## Alcance

Corresponde a este proyecto todo lo que rompa una garantía que declara:

- **Ejecución de una acción de respuesta sin aprobación humana.** Cualquier camino que ejecute
  `isolate_endpoint` o `add_to_block_list` sin autorización de una persona: en
  `require_human_approval()`, en `_apply_destructive_gating`, o esquivando el `permission` map de
  `.opencode/opencode.json`.
- **Inyección** a través de argumentos que alcanzan rutas de la API, el header `TMV1-Filter` o el
  cuerpo de un request.
- **Exposición de credenciales o de datos del tenant** en logs, auditoría, mensajes de error,
  respuestas de tools o reportes generados.
- **Escape del sandbox del harness**: modificación de `mcp_server/`, lectura de un `.env`, o escritura
  de un archivo de estado que evada la validación.
- **Gating inefectivo**: una tool registrada sin su credencial, o que sobreviva a `MCP_DISABLED_TAGS`
  o `MCP_DISABLED_TOOLS`.
- **Exposición en HTTP**: acceso a una tool sin `MCP_AUTH_TOKEN` estando configurado.

## Fuera de alcance

- **Errores de criterio del modelo en el triage o el análisis.** Es un riesgo asumido y documentado:
  por eso ninguna acción destructiva depende del comportamiento del prompt. Un triage incorrecto no es
  una vulnerabilidad; un triage incorrecto que ejecute una contención por sí solo sí lo es.
- **Operar con `MCP_REQUIRE_APPROVAL=false`.** Es una postura más débil, documentada en el README, y
  queda registrada en la auditoría como `approval_delegated`. Bajo esa configuración el gate es el del
  cliente MCP; un bypass de *ese* gate sí corresponde reportarlo.
- **Configuración de la instalación**: permisos excesivos en la API key, credenciales almacenadas
  indebidamente, webhook de Slack expuesto.
- **Vulnerabilidades en dependencias upstream** (FastMCP, httpx, pydantic, OpenCode). Corresponden al
  proyecto de origen. Si requieren una mitigación en este repositorio, el reporte aplica de todos
  modos.
- **Vulnerabilidades en Trend Micro Vision One.** Este repositorio es un cliente de su API; los fallos
  del producto se reportan por los canales oficiales de Trend Micro.

## Pruebas

Las pruebas se realizan contra un tenant de laboratorio. Este proyecto no autoriza pruebas contra
consolas productivas ni contra entornos de terceros.

## Crédito

Se acredita a quien reporta, salvo pedido en contrario.
