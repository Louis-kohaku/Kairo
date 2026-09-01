// `npm run dev` - runs the backend (uvicorn --reload) and the frontend
// (vite dev server) together. Ctrl+C stops both.
import path from "node:path";
import { FRONTEND_DIR, BACKEND_DIR, requireVenvPython, runConcurrently, loadEnvFile } from "./lib.mjs";

loadEnvFile(path.join(BACKEND_DIR, ".env"));

const host = process.env.KAIRO_HOST || "127.0.0.1";
const port = process.env.KAIRO_PORT || "8756";
const python = requireVenvPython();

console.log(`[kairo] backend  : http://${host}:${port} (http://${host}:${port}/docs)`);
console.log("[kairo] frontend : http://localhost:5173");
console.log("[kairo] 停止するには Ctrl+C を押してください\n");

runConcurrently([
  {
    name: "backend",
    cmd: python,
    args: ["-m", "uvicorn", "app.main:app", "--reload", "--host", host, "--port", port],
    opts: { cwd: BACKEND_DIR },
  },
  {
    name: "frontend",
    cmd: "npm",
    args: ["run", "dev"],
    opts: { cwd: FRONTEND_DIR },
  },
]);
