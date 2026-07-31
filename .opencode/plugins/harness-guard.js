/**
 * harness-guard — the guardrails that must not depend on configuration.
 *
 * Two jobs:
 *
 * 1. **Keep the harness out of the MCP server and out of `.env`, and keep the
 *    state files on contract.** The declarative `permission.edit` / `read` / `bash`
 *    rules match patterns against the path the model happened to pass, and an
 *    absolute path, backslashes or a `bash` one-liner can slip past a glob. Here
 *    the argument is normalised first and then matched, so the guard holds however
 *    the path was spelled. A state file must be rewritten whole, and its payload is
 *    validated before the write lands.
 *
 * 2. **Prove it is running.** A plugin that fails to load is silent, so this one
 *    writes a status marker on load and refreshes it on every tool call;
 *    `scripts/check_guard.py` reads it during the preflight.
 *
 * The human-approval gate for containment is NOT here. It is the `permission` map
 * in `opencode.json`: `<server>_*: "ask"` covers every tool of the MCP server,
 * present or future, and the safe ones are allowed one by one. A plugin cannot
 * provide that gate — `permission.ask` is not invoked for a call the config already
 * resolved to "allow", so no hook can turn one into a prompt. Do not move the gate
 * back here.
 *
 * Hook contract (https://opencode.ai/docs/plugins):
 *   - `tool.execute.before(input, output)` — `input.tool`, `output.args`;
 *     throwing blocks the call.
 */

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

/**
 * This file exports exactly ONE thing: the plugin factory. OpenCode's loader
 * walks `Object.values(module)` and throws `Plugin export is not a function` on
 * the first value that is not a factory, which skips the WHOLE file — so a second
 * export silently disables every rule below. Constants ride along as properties of
 * the factory (see the bottom of the file), where the probe reads them.
 * `scripts/probe_harness_guard.mjs` asserts this shape.
 */

/** Bumped when the hook contract changes, so a stale marker is recognisable. */
const GUARD_VERSION = 1;

/** Where the liveness marker is written, relative to the project directory. */
const STATUS_FILE = join(".opencode", "guard-status.json");

/** Tools that can create or change a file. */
const WRITE_TOOLS = new Set(["edit", "write", "patch", "multiedit"]);

/** Argument keys that carry a path, across the built-in tools. */
const PATH_ARGS = ["filePath", "path", "file", "pattern", "glob", "notebookPath"];

/** Protected areas, matched against a normalised (lowercase, forward-slash) path. */
const MCP_SERVER = "mcp_server/";

/**
 * Runtime state files -> the `--check` kind that validates them.
 *
 * Nothing stops a model from reshaping them, and a reshaped document breaks the
 * next step far from the cause. So every write is validated BEFORE it lands: the
 * agent gets the exact key that is wrong and can correct itself.
 */
const STATE_FILES = [
  ["workbench_list.json", "workbench"],
  ["context/alert_context.json", "alert_context"],
  ["memory/history.json", "history"],
];

/** The `--check` kind for a path, or null if it is not a state file. */
function stateKind(path) {
  for (const [suffix, kind] of STATE_FILES) {
    if (path.endsWith(suffix)) return kind;
  }
  return null;
}

/** `.env.example` is a tracked placeholder: it is documentation, not a secret. */
function isProtectedEnv(value) {
  if (!value.includes(".env")) return false;
  return !value.includes(".env.example");
}

function normalise(value) {
  return String(value).replace(/\\/g, "/").toLowerCase();
}

/** Every path-ish argument of a tool call, normalised. */
function pathArgs(args) {
  if (!args) return [];
  return PATH_ARGS.filter((key) => typeof args[key] === "string").map((key) =>
    normalise(args[key]),
  );
}

/**
 * Ways to run the validator, tried in order, as `[executable, leading args]`.
 * The virtualenv that `setup` creates comes first because it needs no
 * resolution; `uv run --no-project` is the fallback for a repo that was never
 * set up (uv provisions the interpreter itself). A bare `python3`/`python` is
 * deliberately NOT a candidate: the interpreter comes from uv, never from PATH.
 */
const VALIDATOR_COMMANDS = [
  ["mcp_server/.venv/Scripts/python.exe", []],
  ["mcp_server/.venv/bin/python", []],
  ["uv", ["run", "--no-project"]],
];

/**
 * Run one candidate and resolve to its exit code, or null if it never started.
 *
 * Spawned directly instead of through the plugin `$` helper: the payload has to
 * reach the validator on **stdin**, and the shell helper offers no way to feed it.
 */
const runCandidate = ([executable, leadingArgs], args, cwd, input) =>
  new Promise((resolve) => {
    let child;
    try {
      child = spawn(executable, [...leadingArgs, ...args], {
        cwd,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
        stdio: ["pipe", "ignore", "pipe"],
      });
    } catch {
      resolve(null);
      return;
    }
    let stderr = "";
    child.stderr?.on("data", (chunk) => {
      stderr += chunk;
    });
    // ENOENT (candidate not installed) and a broken pipe both mean "no verdict".
    child.on("error", () => resolve(null));
    child.stdin?.on("error", () => {});
    child.on("close", (code) => resolve({ code, stderr }));
    child.stdin?.end(input, "utf-8");
  });

/**
 * @param directory  Project root, as OpenCode passes it.
 * @param statusFile Where to write the liveness marker. Only the probe sets it,
 *   so that verifying the guard cannot refresh the marker the preflight reads —
 *   a self-fulfilling check would report a gate that is not there.
 */
export const HarnessGuard = async ({ directory, statusFile }) => {
  // Remembered after the first successful run so later writes skip the probing.
  let runner = null;

  /**
   * Record that this guard is loaded and still receiving hook calls.
   *
   * Best-effort by design: a failure to write the marker must never block a tool
   * mid-alert. The consequence of losing it is a preflight that refuses the
   * session, which is the safe direction.
   */
  const heartbeat = () => {
    try {
      const path = statusFile ?? join(directory, STATUS_FILE);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(
        path,
        JSON.stringify(
          { active: true, version: GUARD_VERSION, pid: process.pid, seen_at: Date.now() },
          null,
          2,
        ),
        "utf-8",
      );
    } catch {
      // Intentionally silent: see above.
    }
  };

  heartbeat();

  /**
   * Ask the validator about a document.
   *
   * Returns `{ verdict: true|false }` when the validator actually ran, and
   * `{ verdict: null }` when no interpreter could run it. With no verdict the
   * write goes through: this is a data-quality guard, not a security boundary —
   * the path rules are, and they need no Python.
   */
  const validateState = async (kind, content) => {
    const args = ["scripts/validate_alert_context.py", "--check", kind];
    for (const candidate of runner ? [runner] : VALIDATOR_COMMANDS) {
      const result = await runCandidate(candidate, args, directory, content);
      // 0 = accepted, 1 = the validator ran and rejected the payload. Anything
      // else means we never reached the validator, so try the next candidate.
      if (result && (result.code === 0 || result.code === 1)) {
        runner = candidate;
        return {
          verdict: result.code === 0,
          detail: result.stderr.trim() || "invalid",
        };
      }
    }
    console.error(
      "harness-guard: could not run scripts/validate_alert_context.py — " +
        "state writes are going through UNVALIDATED. Run /7x24 to see why.",
    );
    return { verdict: null, detail: "" };
  };

  return {
    "tool.execute.before": async (input, output) => {
      // Refreshed before any decision, so the marker proves the hook is live and
      // not merely that the plugin was imported at some point in the past. The
      // preflight runs its check through `bash`, which passes through here first.
      heartbeat();

      const tool = input.tool;
      const args = output.args ?? {};

      // 1. No reading/writing a real .env, with any tool.
      for (const path of pathArgs(args)) {
        if (isProtectedEnv(path)) {
          throw new Error(
            `Blocked: '${tool}' may not touch .env files (secrets). ` +
              "Read mcp_server/src/.env.example instead.",
          );
        }
        // 2. No modifying the MCP server's source; reading it stays allowed.
        if (WRITE_TOOLS.has(tool) && path.includes(MCP_SERVER)) {
          throw new Error(
            `Blocked: '${tool}' may not modify ${MCP_SERVER} — the MCP server is ` +
              "out of scope for the SOC harness. Ask the user to change it.",
          );
        }
      }

      // 3. Same two rules for shell commands, which bypass the path arguments.
      if (tool === "bash" && typeof args.command === "string") {
        const command = normalise(args.command);
        if (isProtectedEnv(command)) {
          throw new Error("Blocked: shell commands may not read or write .env files (secrets).");
        }
        // Only redirections/editors can mutate files from bash; plain reads are fine.
        const mutates = /(>|>>|\btee\b|\bsed -i\b|\brm\b|\bmv\b|\bcp\b)/.test(command);
        if (mutates && command.includes(MCP_SERVER)) {
          throw new Error(`Blocked: shell commands may not modify ${MCP_SERVER}.`);
        }
      }

      // 4. State files are written WHOLE and validated before they land.
      const target = typeof args.filePath === "string" ? normalise(args.filePath) : null;
      const kind = target && stateKind(target);
      if (!kind) return;

      // A partial edit cannot be validated before it lands, and a half-applied
      // patch on these files corrupts the next step. Rewrite the whole document.
      if (tool !== "write" && WRITE_TOOLS.has(tool)) {
        throw new Error(
          `Blocked: '${target}' must be rewritten whole with 'write' (not '${tool}'), so its ` +
            "shape can be validated before it lands.",
        );
      }
      if (tool !== "write") return;

      const { verdict, detail } = await validateState(kind, args.content ?? "");
      if (verdict === false) {
        throw new Error(
          `Blocked: this would leave ${target} off-contract:\n${detail}\n` +
            `Fix the payload — the canonical empty shape is in ` +
            `docs/references/seed_${kind === "workbench" ? "workbench_list" : kind}.json.`,
        );
      }
    },
  };
};

// Published here rather than as module exports: see the note at the top of the
// file — a second export would stop OpenCode from loading this plugin at all.
HarnessGuard.GUARD_VERSION = GUARD_VERSION;
HarnessGuard.STATUS_FILE = STATUS_FILE;
