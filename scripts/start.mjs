// `npm run start` - production-ish mode: serves the built frontend (dist/)
// with `vite preview` and runs the backend without --reload.
// Builds the frontend first if dist/ doesn't exist yet.
import { existsSync } from "node:fs";
import path from "node:path";
import {
  FRONTEND_DIR,
  BACKEND_DIR,
  requireVenvPython,
  run,
  runConcurrently,
  loadEnvFile,
} from "./lib.mjs";

loadEnvFile(path.join(BACKEND_DIR, ".env"));

const host = process.env.KAIRO_HOST || "127.0.0.1";
const port = process.env.KAIRO_PORT || "8756";
const previewPort = process.env.KAIRO_PREVIEW_PORT || "4173";
const python = requireVenvPython();

async function main() {
  const distDir = path.join(FRONTEND_DIR, "dist");
  if (!existsSync(distDir)) {
    console.log("[kairo] frontend/dist が無いので先にビルドします (npm run build)...");
    await run("npm", ["run", "build"], { cwd: FRONTEND_DIR });
  }

  console.log(`[kairo] backend (本番) : http://${host}:${port}`);
  console.log(`[kairo] frontend (本番): http://localhost:${previewPort}`);
  console.log("[kairo] 停止するには Ctrl+C を押してください\n");

  runConcurrently([
    {
      name: "backend",
      cmd: python,
      args: ["-m", "uvicorn", "app.main:app", "--host", host, "--port", port],
      opts: { cwd: BACKEND_DIR },
    },
    {
      name: "frontend",
      cmd: "npm",
      args: ["run", "preview", "--", "--port", previewPort],
      opts: { cwd: FRONTEND_DIR },
    },
  ]);
}

main().catch((err) => {
  console.error(`\n[kairo] 起動に失敗しました: ${err.message}`);
  process.exit(1);
});
