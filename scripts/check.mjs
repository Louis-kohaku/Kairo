// `npm run check` - quick sanity check without starting servers:
//   - frontend: lint (oxlint) + type-check (tsc -b, no emit)
//   - backend: import the FastAPI app (catches syntax/import errors)
//   - backend: the agent's decision-logic tests (no network, no FFmpeg,
//     no LM Studio - a few seconds)
//
// The end-to-end test (backend/tests/e2e_agent_pipeline.py) is deliberately
// NOT run here: it encodes real video with FFmpeg and takes about a minute.
// Run it directly when changing the production pipeline:
//   backend/.venv/Scripts/python.exe backend/tests/e2e_agent_pipeline.py
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

  console.log("\n[kairo] エージェントの判断ロジックをテストしています...");
  await run(python, ["tests/test_agent_units.py"], { cwd: BACKEND_DIR });
  await run(python, ["tests/test_llm_retry.py"], { cwd: BACKEND_DIR });

  console.log("\n[kairo] チェック完了、問題は見つかりませんでした。");
}

main().catch((err) => {
  console.error(`\n[kairo] チェックに失敗しました: ${err.message}`);
  process.exit(1);
});
