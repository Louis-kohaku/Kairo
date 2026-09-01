// Shared helpers for the root-level npm scripts (setup/dev/start/check).
// Pure Node.js core modules only - no dependencies to install at the repo root.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const BACKEND_DIR = path.join(ROOT, "backend");
export const FRONTEND_DIR = path.join(ROOT, "frontend");
export const VENV_DIR = path.join(BACKEND_DIR, ".venv");

// Minimal .env loader (KEY=VALUE per line, '#' comments, optional quotes)
// mirroring python-dotenv's default: never overrides a variable already set
// in the real environment. Lets KAIRO_HOST/KAIRO_PORT live in backend/.env
// alongside the variables the Python backend itself reads from there.
export function loadEnvFile(filePath) {
  if (!existsSync(filePath)) return;
  for (const line of readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (key && !(key in process.env)) process.env[key] = value;
  }
}

const IS_WIN = process.platform === "win32";

// Only npm/npx are resolved via a PATH-based shell shim (.cmd) on Windows.
// Direct executable paths (venv python, ffmpeg, ...) don't need a shell,
// and avoiding it sidesteps shell-argument-escaping foot-guns entirely.
function needsShell(cmd) {
  return IS_WIN && (cmd === "npm" || cmd === "npx");
}

// Node warns (DEP0190) whenever shell:true is combined with an args array,
// since none of the args get escaped. Our args never contain spaces/shell
// metacharacters, so we fold them into a single command string ourselves
// instead, which avoids the warning while keeping the same behavior.
function toSpawnArgs(cmd, args) {
  if (!needsShell(cmd)) return { command: cmd, commandArgs: args, shell: false };
  return { command: [cmd, ...args].join(" "), commandArgs: [], shell: true };
}

export function venvPythonPath() {
  return IS_WIN
    ? path.join(VENV_DIR, "Scripts", "python.exe")
    : path.join(VENV_DIR, "bin", "python");
}

export function hasVenv() {
  return existsSync(venvPythonPath());
}

export function requireVenvPython() {
  if (!hasVenv()) {
    console.error(
      "[kairo] backend/.venv が見つかりません。先に `npm run setup` を実行してください。",
    );
    process.exit(1);
  }
  return venvPythonPath();
}

export function findSystemPython() {
  for (const candidate of IS_WIN ? ["py", "python"] : ["python3", "python"]) {
    const args = IS_WIN && candidate === "py" ? ["-3", "--version"] : ["--version"];
    const result = spawnSync(candidate, args, { stdio: "ignore", shell: needsShell(candidate) });
    if (!result.error && result.status === 0) {
      return { cmd: candidate, extraArgs: IS_WIN && candidate === "py" ? ["-3"] : [] };
    }
  }
  return null;
}

// Runs a command to completion, inheriting stdio, and rejects on non-zero exit.
export function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const { command, commandArgs, shell } = toSpawnArgs(cmd, args);
    const child = spawn(command, commandArgs, {
      stdio: "inherit",
      shell,
      ...opts,
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${cmd} ${args.join(" ")} がコード ${code} で終了しました`));
    });
  });
}

// Spawns a long-running child process (dev server) without waiting for exit.
export function spawnService(name, cmd, args, opts = {}) {
  const { command, commandArgs, shell } = toSpawnArgs(cmd, args);
  const child = spawn(command, commandArgs, {
    stdio: "inherit",
    shell,
    ...opts,
  });
  child.on("error", (err) => {
    console.error(`[kairo] ${name} の起動に失敗しました:`, err.message);
  });
  return child;
}

// Runs several long-running services together; Ctrl+C / one process exiting
// stops all of them.
export function runConcurrently(services) {
  const children = services.map(({ name, cmd, args, opts }) =>
    spawnService(name, cmd, args, opts),
  );

  let shuttingDown = false;
  const shutdown = (signal) => {
    if (shuttingDown) return;
    shuttingDown = true;
    for (const child of children) {
      if (!child.killed) child.kill(signal ?? "SIGTERM");
    }
  };

  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));

  for (const child of children) {
    child.on("exit", (code) => {
      if (!shuttingDown) {
        console.log(`[kairo] プロセスが終了しました (code ${code})。他のプロセスも停止します...`);
        shutdown();
      }
    });
  }
}
