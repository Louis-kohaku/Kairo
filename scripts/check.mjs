// `npm run check` - quick sanity check without starting servers:
//   - frontend: lint (oxlint) + type-check (tsc -b, no emit)
//   - backend: import the FastAPI app (catches syntax/import errors)
// Note: backend/tests/ currently has no test files, so no pytest run here.
import { BACKEND_DIR, FRONTEND_DIR, requireVenvPython, run } from "./lib.mjs";

async function main() {
  console.log("[kairo] フロントエンドをチェックしています (lint + 型チェック)...");
  await run("npm", ["run", "lint"], { cwd: FRONTEND_DIR });
  await run("npx", ["tsc", "-b"], { cwd: FRONTEND_DIR });

  console.log("\n[kairo] バックエンドをチェックしています (import確認)...");
  const python = requireVenvPython();
  await run(python, ["-c", "import app.main; print('backend import OK')"], {
    cwd: BACKEND_DIR,
  });

  console.log("\n[kairo] チェック完了、問題は見つかりませんでした。");
}

main().catch((err) => {
  console.error(`\n[kairo] チェックに失敗しました: ${err.message}`);
  process.exit(1);
});
