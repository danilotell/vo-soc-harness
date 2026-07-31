#!/usr/bin/env node
/**
 * Drive `.opencode/plugins/harness-guard.js` through its hook contract.
 *
 * OpenCode loads the guard at runtime, so a typo or a wrong API call does not fail
 * a test: it surfaces as a blocked tool in the middle of an alert, far from its
 * cause. This calls the real hooks with synthetic arguments and asserts what each
 * one should do. `tool.execute.before` only inspects the arguments of a call that
 * has not happened yet, so no state file, `.env` or source file is ever touched;
 * the one file written is the guard's own liveness marker, in a temporary
 * directory.
 *
 * Usage (needs node, which OpenCode already brings):
 *     node scripts/probe_harness_guard.mjs
 *
 * Exit code 0 = every case behaved as declared, 1 = at least one did not.
 */

import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url)).replace(/[\\/]$/, "");
const guardModule = await import(
  new URL("../.opencode/plugins/harness-guard.js", import.meta.url)
);
const { HarnessGuard } = guardModule;
// Constants travel as properties of the factory, not as module exports: see the
// `exports:` cases below for why.
const { GUARD_VERSION, STATUS_FILE } = HarnessGuard;

const reference = (name) =>
  JSON.parse(readFileSync(new URL(`../docs/references/${name}`, import.meta.url), "utf-8"));

/**
 * A template with every string replaced by `"N/A"`.
 *
 * The templates ARE the declared shape, so they are the right fixture — but their
 * example values are rejected on purpose, since copying them is how an agent
 * invents data. `"N/A"` is the declared marker for "does not apply", so it passes.
 */
const scrub = (value) => {
  if (Array.isArray(value)) return value.map(scrub);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, scrub(v)]));
  }
  return typeof value === "string" ? "N/A" : value;
};

const alertContext = JSON.stringify({
  triage: scrub(reference("template_triage.json").triage),
  analysis: scrub(reference("template_analysis.json").analysis),
});
const workbench = JSON.stringify(reference("seed_workbench_list.json"));

/** `[label, tool, args, expected]` — expected is "allow" or "block". */
const WRITE_CASES = [
  ["workbench, seed shape", "write", { filePath: `${ROOT}/workbench_list.json`, content: workbench }, "allow"],
  [
    "workbench, missing range_days",
    "write",
    { filePath: `${ROOT}/workbench_list.json`, content: JSON.stringify({ last_updated: null, limit_reached: false, alerts: [] }) },
    "block",
  ],
  // The templates state a minimum: declared keys must exist, undeclared ones are
  // accepted so an agent can record what it observed. A whole unknown *section*
  // of alert_context is still refused (see below) — that is a misplaced field,
  // not an observation.
  [
    "workbench, undeclared top-level key",
    "write",
    { filePath: `${ROOT}/workbench_list.json`, content: JSON.stringify({ ...reference("seed_workbench_list.json"), typo: 1 }) },
    "allow",
  ],
  [
    "alert_context, undeclared field inside a section",
    "write",
    {
      filePath: `${ROOT}/context/alert_context.json`,
      content: JSON.stringify({
        triage: { ...scrub(reference("template_triage.json").triage), undeclared_field: "N/A" },
      }),
    },
    "allow",
  ],
  [
    "alert_context, declared field removed",
    "write",
    {
      filePath: `${ROOT}/context/alert_context.json`,
      content: (() => {
        const triage = scrub(reference("template_triage.json").triage);
        delete triage.severity;
        return JSON.stringify({ triage });
      })(),
    },
    "block",
  ],
  ["workbench, bare array", "write", { filePath: `${ROOT}/workbench_list.json`, content: "[]" }, "block"],
  ["workbench, not JSON", "write", { filePath: `${ROOT}/workbench_list.json`, content: "nope" }, "block"],
  ["alert_context, triage + analysis", "write", { filePath: `${ROOT}/context/alert_context.json`, content: alertContext }, "allow"],
  ["alert_context, seed shape", "write", { filePath: `${ROOT}/context/alert_context.json`, content: "{}" }, "allow"],
  ["alert_context, unknown section", "write", { filePath: `${ROOT}/context/alert_context.json`, content: '{"nope":{}}' }, "block"],
  ["alert_context, template placeholders", "write", { filePath: `${ROOT}/context/alert_context.json`, content: JSON.stringify({ triage: reference("template_triage.json").triage }) }, "block"],
  ["history, seed shape", "write", { filePath: `${ROOT}/memory/history.json`, content: "[]" }, "allow"],
  // A partial patch cannot be validated before it lands, whatever the tool.
  ["alert_context via edit", "edit", { filePath: `${ROOT}/context/alert_context.json`, oldString: "a", newString: "b" }, "block"],
  ["workbench via patch", "patch", { filePath: `${ROOT}/workbench_list.json`, patch: "..." }, "block"],
  // Not a state file: the guard must stay out of the way.
  ["ordinary file", "write", { filePath: `${ROOT}/progress/current.md`, content: "# anything" }, "allow"],
  // Protected areas, spelled the awkward ways a model might spell them.
  ["write into mcp_server", "write", { filePath: `${ROOT}/mcp_server/src/app.py`, content: "x" }, "block"],
  ["write into mcp_server, backslashes", "write", { filePath: "mcp_server\\src\\app.py", content: "x" }, "block"],
  ["read a real .env", "read", { filePath: `${ROOT}/mcp_server/src/.env` }, "block"],
  ["read .env.example", "read", { filePath: `${ROOT}/mcp_server/src/.env.example` }, "allow"],
  ["bash redirect into mcp_server", "bash", { command: "echo x > mcp_server/src/app.py" }, "block"],
  ["bash cat of a .env", "bash", { command: "cat mcp_server/src/.env" }, "block"],
  ["bash reading mcp_server", "bash", { command: "cat mcp_server/src/app.py" }, "allow"],
];

// The guard needs the real ROOT to reach the validator, but its liveness marker
// goes to a sandbox: if verifying the guard refreshed the marker that
// `check_guard.py` reads, the preflight would pass without OpenCode having loaded
// anything.
const sandbox = mkdtempSync(join(tmpdir(), "harness-guard-probe-"));
const guard = await HarnessGuard({
  directory: ROOT,
  statusFile: join(sandbox, "main-status.json"),
});
const before = guard["tool.execute.before"];

let failures = 0;
const report = (ok, label, detail) => {
  if (!ok) failures += 1;
  console.log(`${ok ? "ok  " : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
};

// The loader's own rule, asserted here because breaking it is silent at runtime:
// OpenCode walks every export of the file and throws `Plugin export is not a
// function` on the first that is not a factory, skipping the whole plugin — which
// drops every rule it carries while the rest of the harness keeps working.
const badExports = Object.entries(guardModule).filter(([, value]) => typeof value !== "function");
report(
  badExports.length === 0,
  "exports: only plugin factories, or OpenCode skips the whole file",
  badExports.map(([name, value]) => `${name} is a ${typeof value}`).join(", "),
);
report(typeof HarnessGuard === "function", "exports: the plugin factory is exported");
report(
  GUARD_VERSION !== undefined && STATUS_FILE !== undefined,
  "exports: the factory carries GUARD_VERSION and STATUS_FILE",
  `version=${GUARD_VERSION} file=${STATUS_FILE}`,
);

for (const [label, tool, args, expected] of WRITE_CASES) {
  let actual = "allow";
  let detail = "";
  try {
    await before({ tool }, { args });
  } catch (error) {
    actual = "block";
    detail = error.message.split("\n")[0];
  }
  report(actual === expected, `${tool}: ${label} -> ${expected}`, actual === expected ? "" : detail || "not blocked");
}

// The liveness marker `scripts/check_guard.py` reads.
try {
  const marker = () => JSON.parse(readFileSync(join(sandbox, STATUS_FILE), "utf-8"));

  const isolated = await HarnessGuard({ directory: sandbox });
  const onLoad = marker();
  report(onLoad.active === true, "heartbeat: written on load", `active=${onLoad.active}`);
  report(
    onLoad.version === GUARD_VERSION,
    "heartbeat: declares the guard version",
    `version=${onLoad.version}`,
  );

  // Refreshed by the hook itself, so the marker proves the hooks are live and not
  // merely that the module was imported once.
  const beforeAtLoad = onLoad.seen_at;
  await new Promise((resolve) => setTimeout(resolve, 5));
  await isolated["tool.execute.before"]({ tool: "read" }, { args: { filePath: "README.md" } });
  report(marker().seen_at > beforeAtLoad, "heartbeat: refreshed by tool.execute.before");

  // A blocked call must still leave the marker fresh: refusing a tool is the
  // guard working, and the preflight must not read that as the guard being gone.
  const beforeBlocked = marker().seen_at;
  await new Promise((resolve) => setTimeout(resolve, 5));
  await isolated["tool.execute.before"](
    { tool: "read" },
    { args: { filePath: join(sandbox, "mcp_server", "src", ".env") } },
  ).catch(() => {});
  report(marker().seen_at > beforeBlocked, "heartbeat: refreshed even when the call is blocked");
} finally {
  rmSync(sandbox, { recursive: true, force: true });
}

console.log(failures ? `\n${failures} case(s) failed.` : "\nAll cases behaved as declared.");
process.exit(failures ? 1 : 0);
