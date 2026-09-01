// `npm run db:init` - explicitly (re)creates data/kairo.db and its tables.
// Not required for normal use: the backend also runs this automatically on
// startup (see backend/app/main.py). Useful for scripting / CI / a fresh
// check that the DB layer works before starting the server.
import { BACKEND_DIR, requireVenvPython, run } from "./lib.mjs";

const python = requireVenvPython();

run(python, ["-c", "from app.core.db import init_db; init_db(); print('DB initialized')"], {
  cwd: BACKEND_DIR,
}).catch((err) => {
  console.error(`[kairo] DB初期化に失敗しました: ${err.message}`);
  process.exit(1);
});
