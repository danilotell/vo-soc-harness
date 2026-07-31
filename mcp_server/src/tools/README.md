# Tools

Each tool lives in its **own folder** and is registered **automatically**.
There is no central list to edit — dropping a new folder here is enough.

## Anatomy of a tool folder

```
get_alert_list/
  __init__.py    # re-exports register:  from .tool import register
  tool.py        # the @mcp.tool implementation + a module-level register(mcp)
  models.py      # (optional) Pydantic output models / Literal input types
  validators.py  # (optional) input validation unique to this tool
```

The autodiscovery contract (see `__init__.py` of this package) is simple:

> Every sub-package of `tools/` whose name does **not** start with `_` and that
> exposes a `register(mcp)` function is imported and registered at startup.

Folders starting with `_` are skipped — that is why `_hints` and `_template`
are not registered as tools.

## Add a new tool in 4 steps

1. **Copy** `_template/` and rename it to your tool name in `snake_case`
   (use the same name as the tool function, e.g. `quarantine_email/`).
2. In `tool.py`: rename `my_new_tool`, write its docstring (the LLM reads it),
   set its arguments and body. Use `app = get_app_context(ctx)` to reach the
   shared `vision_one` / `http` clients.
3. In `models.py`: declare any output `BaseModel` or `Literal` input types —
   or **delete the file** if the tool returns a plain `dict`/`str`.
4. Declare what the tool does — one call, see below. Then add it to
   `EXPECTED_TOOLS` in `tests/test_discovery.py`. Restart the server and the tool
   appears automatically.

## Validation: shared vs tool-specific

Any free-text argument (endpoint names, ids, IOCs...) flows into URL paths, the
`TMV1-Filter` header or request bodies, so it is an **injection surface** —
always validate it before use. Where the validator lives depends on reuse:

- **Shared check used by 2+ tools** → it belongs in the cross-cutting
  [`filters.py`](../filters.py) module. Import what you need:
  ```python
  from filters import validate_alert_id, validate_endpoint_name, validate_ioc
  ```
  Today every validator there is shared by several tools — that is exactly why
  they are not buried inside any single tool folder.
- **Check unique to one tool** → define it locally in that tool's
  `validators.py` and use a relative import:
  ```python
  from .validators import validate_ticket_id
  ```
  If a second tool later needs the same check, **promote** it to `filters.py`.

Validators raise `fastmcp.exceptions.ToolError` on bad input (the message is
surfaced safely to the caller) and return the cleaned value.

## Shaping output: the model is your field whitelist

Vision One / third-party responses can be large, and every field returned costs
LLM context. **You decide, per tool, how much of the response to expose** — and
the Pydantic model is the mechanism:

- **Projected output (default for verbose endpoints).** Declare only the fields
  you care about in `models.py`, then validate the raw payload against it.
  Pydantic v2 ignores unknown fields, so the model acts as a whitelist:
  ```python
  # models.py
  class EndpointSummary(BaseModel):
      agent_guid: str = Field(alias="agentGuid")
      os_name: str | None = Field(default=None, alias="osName")
      model_config = {"populate_by_name": True, "extra": "ignore"}

  # tool.py
  data = await app.vision_one.get(f"/v3.0/endpointSecurity/endpoints/{guid}")
  return EndpointSummary.model_validate(data)        # only declared fields survive
  ```
  For lists: `return [EndpointSummary.model_validate(x) for x in data["items"]]`.
  `get_alert_list` / `AlertSummary` is a working example.

- **Full response (deliberate opt-out).** Some calls genuinely need the entire
  payload (deep forensic detail, free-form structures). Then skip the model and
  annotate the return as `dict[str, Any]`. Today `get_alert_details`,
  `get_endpoint_details` and `get_observed_attack_techniques` do this on purpose
  — note it in the tool's docstring so the choice is explicit.

Rule of thumb: **project by default; return the raw dict only when you can name
why the full response is needed.**

## Declaring what a tool does (`tools/_hints.py`)

One call sets both the MCP **annotations** the client sees and the **tags** this
server gates on:

```python
@mcp.tool(**read_only("alerts"))               # a read that reaches Vision One
@mcp.tool(**write("alerts", idempotent=True))  # a reversible mutation
@mcp.tool(**destructive("response"))           # containment; also tagged `write`
@mcp.tool(**meta_read())                       # diagnostics, no external system
```

They are produced together because they state the same fact for two different
audiences. Written separately they can disagree, and the dangerous direction is
silent: a tool with `destructiveHint` but no `destructive` tag looks dangerous to
the client while escaping `MCP_ENABLE_DESTRUCTIVE` on the server.
`tests/test_discovery.py` asserts the two agree for every registered tool.

The integration argument comes from a closed vocabulary
([`tags.py`](../tags.py)) — an unknown one raises at registration:

| Integration | Requires |
|-------------|----------------------------------------------|
| `alerts` / `endpoints` / `response` | Vision One (`VO_REGION`, `VO_API_KEY`) |
| `intel` | VirusTotal (`VT_API_KEY`) |
| `notify` | Slack (`SLACK_WEBHOOK_URL`) |
| `meta` | nothing (internal diagnostics) |

That mapping is what makes credential gating work: with a credential missing,
[`capabilities.py`](../capabilities.py) disables every tool carrying that tag. The
access level (`read` / `write` / `destructive`) is what lets an operator switch
off whole classes with `MCP_DISABLED_TAGS`.

> Using a **new** integration? Add a `Capability` entry in `capabilities.py` and
> its tag to `INTEGRATION_TAGS` in `tags.py`, so credential gating covers it.
