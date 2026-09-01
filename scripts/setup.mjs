// `npm run setup` - one-shot environment setup:
//   1. create backend/.venv if missing and install Python deps
//   2. install frontend deps
//   3. copy .env.example -> .env where missing
//   4. create the data/ directory
//   5. warn about ffmpeg if it's not on PATH
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import {
  ROOT,
  BACKEND_DIR,
  FRONTEND_DIR,
  VENV_DIR,
  hasVenv,
  venvPythonPath,
  findSystemPython,
  run,
} from "./lib.mjs";

function step(msg) {
  console.log(`\n[kairo] ${msg}`);
}

function copyIfMissing(src, dest) {
  if (existsSync(dest)) {
    console.log(`[kairo] ${path.relative(ROOT, dest)} は既に存在するのでスキップします`);
    return;
  }
  copyFileSync(src, dest);
  console.log(`[kairo] ${path.relative(ROOT, dest)} を作成しました`);
}

async function main() {
  step("Python環境を確認しています...");
  if (!hasVenv()) {
    const py = findSystemPython();
    if (!py) {
      console.error(
        "[kairo] Python 3.10以上が見つかりません。https://www.python.org/downloads/ からインストールし、" +
          "インストール時に「Add python.exe to PATH」にチェックを入れてから、もう一度実行してください。",
      );
      process.exit(1);
    }
    console.log(`[kairo] backend/.venv を作成します (${py.cmd})`);
    await run(py.cmd, [...py.extraArgs, "-m", "venv", VENV_DIR]);
  } else {
    console.log("[kairo] backend/.venv は既に存在します");
  }

  step("Pythonの依存パッケージをインストールしています (backend/requirements.txt)...");
  await run(venvPythonPath(), ["-m", "pip", "install", "--upgrade", "pip"]);
  await run(venvPythonPath(), [
    "-m",
    "pip",
    "install",
    "-r",
    path.join(BACKEND_DIR, "requirements.txt"),
  ]);

  step("フロントエンドの依存パッケージをインストールしています (frontend)...");
  const lockfile = path.join(FRONTEND_DIR, "package-lock.json");
  if (existsSync(lockfile)) {
    await run("npm", ["ci"], { cwd: FRONTEND_DIR });
  } else {
    await run("npm", ["install"], { cwd: FRONTEND_DIR });
  }

  step("環境変数ファイルを用意しています...");
  copyIfMissing(path.join(BACKEND_DIR, ".env.example"), path.join(BACKEND_DIR, ".env"));
  copyIfMissing(path.join(FRONTEND_DIR, ".env.example"), path.join(FRONTEND_DIR, ".env"));

  step("データ保存先フォルダを用意しています...");
  const dataDir = path.join(ROOT, "data");
  if (!existsSync(dataDir)) {
    mkdirSync(dataDir, { recursive: true });
    console.log("[kairo] data/ を作成しました");
  } else {
    console.log("[kairo] data/ は既に存在します");
  }

  step("FFmpegを確認しています...");
  const ffmpegCheck = spawnSync("ffmpeg", ["-version"], { stdio: "ignore" });
  if (ffmpegCheck.error || ffmpegCheck.status !== 0) {
    console.warn(
      "[kairo] 警告: ffmpeg が見つかりませんでした。メディアの読み込み・書き出し・字幕生成に必須です。\n" +
        "  Windows: winget install Gyan.FFmpeg  (インストール後、新しいターミナルを開き直してください)",
    );
  } else {
    console.log("[kairo] ffmpeg が見つかりました");
  }

  console.log(`
[kairo] セットアップが完了しました。

次のステップ:
  1. (AI編集/自動制作機能を使う場合) LM Studioを起動し、Local Serverを有効にする
  2. npm run dev   で開発サーバーを起動
  3. ブラウザで http://localhost:5173 を開く
`);
}

main().catch((err) => {
  console.error(`\n[kairo] セットアップに失敗しました: ${err.message}`);
  process.exit(1);
});
