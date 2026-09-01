# Kairo

ローカル環境で完結する AI 動画制作・編集ツールです。動画素材の取り込みからタイムライン編集、無音カット、字幕の自動生成、ローカルLLM (LM Studio) によるAI編集・自動制作、書き出しまでを、外部クラウドサービスを一切使わずに行えます。

バックエンドは Python (FastAPI)、フロントエンドは React (Vite)、動画処理は FFmpeg、文字起こしは faster-whisper、AI編集/自動制作はローカルで動く LM Studio（OpenAI互換API）を利用します。

---

## 🚀 最短起動 (Windows / PowerShell)

すでに Node.js と Python がインストールされていれば、以下だけで開発サーバーが立ち上がります。

```powershell
# 1. リポジトリを取得
git clone <このリポジトリのURL>
cd Kairo

# 2. 依存関係のインストール + 初回セットアップ (venv作成・pip install・npm install・.env作成)
npm run setup

# 3. 開発サーバーを起動 (バックエンド + フロントエンド)
npm run dev
```

起動したら、ブラウザで **http://localhost:5173** を開いてください。

> AI編集・AI自動制作機能を使う場合は、事前に [LM Studio](https://lmstudio.ai/) を起動し、Local Server を有効にしておく必要があります（詳細は [LM Studioのセットアップ](#lm-studio-のセットアップ) を参照）。動画の読み込み・書き出し・無音カット・字幕生成には [FFmpeg](https://www.gyan.dev/ffmpeg/builds/) が必須です（`npm run setup` が未検出時に警告します）。

---

## 目次

- [プロジェクト概要](#プロジェクト概要)
- [主な機能](#主な機能)
- [動作環境](#動作環境)
- [必要な前提ソフトウェア](#必要な前提ソフトウェア)
- [インストール手順](#インストール手順)
- [初回セットアップ手順](#初回セットアップ手順)
- [起動方法](#起動方法)
- [停止方法](#停止方法)
- [ブラウザからのアクセスURL](#ブラウザからのアクセスurl)
- [LAN内の別端末からアクセスする方法](#lan内の別端末からアクセスする方法)
- [環境変数の設定方法](#環境変数の設定方法)
- [データベースの初期化](#データベースの初期化)
- [LM Studio のセットアップ](#lm-studio-のセットアップ)
- [動画生成機能 (実験的)](#動画生成機能-実験的)
- [トラブルシューティング](#トラブルシューティング)
- [プロジェクトのディレクトリ構成](#プロジェクトのディレクトリ構成)
- [開発者向け情報](#開発者向け情報)

---

## プロジェクト概要

Kairo は、動画素材の取り込み → タイムライン編集 → 無音部分の自動カット → 字幕の自動生成 → AI (ローカルLLM) による編集指示・企画/台本の自動生成 → FFmpegでの書き出し、という一連の動画制作フローをブラウザUIから行えるローカル動作のツールです。クラウドAPIキーは不要で、AI機能は LM Studio 等のローカルLLMサーバーと通信して動作します。

## 主な機能

- **プロジェクト管理**: 複数の動画プロジェクトを作成・切り替え
- **メディア読み込み**: 動画/音声ファイルをドラッグ&ドロップで取り込み
- **タイムライン編集**: クリップの追加・削除・分割・トリム・音量調整、ドラッグ&ドロップでの並び替え
- **プレビュー再生**: タイムラインの内容をブラウザ上でそのまま再生確認
- **無音自動カット**: 無音区間を検出し、まとめてカットするプランを適用（`AI編集`パネルの元になっている機能）
- **字幕自動生成**: faster-whisper によるローカル文字起こしから字幕(SRT)を生成・編集
- **AI編集 (自然言語)**: 「無音部分を削除して、字幕をつけてください」のような指示をLLMに渡し、タイムライン操作を自動実行
- **AI自動制作**: テーマを指示するだけで、LLMが企画・章立て・シーン単位の台本とビジュアル指示を自動生成
- **画像→動画生成 (実験的)**: 写真をアップロードし、ローカルのStable Video Diffusionモデルで短い動画を生成(`生成`タブ)。完全ローカル・CPU実行、生成結果はMedia Binに自動追加されます。詳細は[動画生成機能](#動画生成機能-実験的)を参照
- **PC / AI環境診断**: CPU・RAM・GPU・ストレージ・FFmpeg・PyTorch等を自動検出し、このPCで何が実行可能かを表示(`PC診断`タブ)
- **レンダリング (書き出し)**: FFmpegでタイムラインを1本の動画に書き出し。字幕の焼き込みにも対応
- **ジョブ進捗表示**: 字幕生成・AI編集・レンダリング・動画生成などの非同期処理をバックグラウンドで実行し、進捗をポーリング表示

## 動作環境

| 項目 | 要件 |
|---|---|
| OS | Windows 10 / 11 (開発・動作確認環境。macOS / Linuxでも動作する設計ですが未検証です) |
| Node.js | `^20.19.0` または `>=22.12.0` (Viteの要件。`node -v` で確認) |
| Python | `3.10.x` (このリポジトリの `backend/.venv` は 3.10.11 で構築・動作確認済み) |
| メモリ (RAM) | 最小 8GB / 推奨 16GB以上（faster-whisperの `medium`/`large` モデルや複数機能の同時利用時は16GB以上を推奨） |
| ディスクの空き容量 | 数GB以上（依存パッケージ、faster-whisperモデル、動画素材・レンダリング結果を保存するため） |
| その他必須ソフト | [FFmpeg](https://www.gyan.dev/ffmpeg/builds/)（動画処理全般に必須）、[LM Studio](https://lmstudio.ai/)（AI編集/自動制作機能を使う場合のみ必須） |

## 必要な前提ソフトウェア

1. **Git** - リポジトリの取得に使用
2. **Node.js** (`^20.19.0` または `>=22.12.0`) - フロントエンドのビルド・実行、および `npm run` によるセットアップ/起動スクリプトの実行に使用
3. **Python 3.10** - バックエンド (FastAPI) の実行に使用
4. **FFmpeg** - 動画の読み込み・トリム・無音検出・レンダリング・字幕焼き込みに必須
5. **LM Studio** (任意・AI機能を使う場合のみ) - AI編集・AI自動制作機能のバックエンドとなるローカルLLMサーバー

### バージョン確認方法 (PowerShell)

```powershell
git --version
node --version
npm --version
python --version      # 見つからない場合は次を試す: py --version
ffmpeg -version
```

### インストールされていない場合 (Windows)

```powershell
# Git
winget install Git.Git

# Node.js (LTS)
winget install OpenJS.NodeJS.LTS

# Python 3.10
winget install Python.Python.3.10

# FFmpeg
winget install Gyan.FFmpeg
```

`winget` コマンド実行後は、PATHを反映させるために **ターミナルを一度閉じて開き直して**から `--version` コマンドで確認してください。Pythonを公式サイト (https://www.python.org/downloads/) からインストールする場合は、インストーラーで **「Add python.exe to PATH」に必ずチェック**を入れてください。

LM Studioは https://lmstudio.ai/ からダウンロードしてインストーラーを実行してください（詳細手順は [LM Studio のセットアップ](#lm-studio-のセットアップ) 参照）。

## インストール手順

```powershell
git clone <このリポジトリのURL>
cd Kairo
npm run setup
```

`npm run setup` は以下をまとめて行います（Windowsパスの問題を避けるため、すべてPowerShellではなくNode.jsスクリプト `scripts/setup.mjs` で実行しています）。

1. `backend/.venv` が無ければ作成 (`python -m venv backend/.venv`)
2. `backend/requirements.txt` を仮想環境にインストール
3. `frontend/` の npm 依存関係をインストール (`package-lock.json` があれば `npm ci`)
4. `backend/.env.example` → `backend/.env`、`frontend/.env.example` → `frontend/.env` を、まだ無い場合のみコピー
5. データ保存用の `data/` フォルダを作成
6. FFmpegがPATH上に見つかるか確認（見つからない場合は警告のみ表示し、処理は継続）

既に `backend/.venv` や `frontend/node_modules` がある場合は、該当ステップをスキップ（または更新のみ）するので、2回目以降の実行でも安全です。

手動で各パーツを個別にセットアップしたい場合は、以下でも同じ結果になります。

```powershell
# バックエンド
py -3 -m venv backend/.venv
backend\.venv\Scripts\pip install -r backend/requirements.txt
Copy-Item backend/.env.example backend/.env

# フロントエンド
npm --prefix frontend ci
Copy-Item frontend/.env.example frontend/.env
```

## 初回セットアップ手順

1. 上記の [インストール手順](#インストール手順) (`npm run setup`) を実行する
2. 必要に応じて `backend/.env` と `frontend/.env` を編集する（詳細は [環境変数の設定方法](#環境変数の設定方法)。デフォルト値のままで通常は動作します）
3. AI編集・AI自動制作機能を使う場合は [LM Studio のセットアップ](#lm-studio-のセットアップ) を行う
4. `npm run dev` で起動する（データベース `data/kairo.db` はバックエンド初回起動時に自動作成されるため、追加の初期化コマンドは不要です）

## 起動方法

### 開発モードの起動方法

バックエンド (uvicorn --reload) とフロントエンド (Vite dev server) を同時に起動します。ファイルを保存すると自動で再読み込みされます。

```powershell
npm run dev
```

- バックエンド: http://127.0.0.1:8756 （Swagger UIは http://127.0.0.1:8756/docs ）
- フロントエンド: http://localhost:5173

バックエンドとフロントエンドを別々のターミナルで個別に起動したい場合:

```powershell
# ターミナル1: バックエンドのみ
backend\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8756 --app-dir backend

# ターミナル2: フロントエンドのみ
npm --prefix frontend run dev
```

### 本番モードの起動方法

フロントエンドをビルドし（`dist/`が無ければ自動でビルドしてから）、ホットリロード無しでバックエンドとフロントエンドのプレビューサーバーを起動します。

```powershell
npm run start
```

- バックエンド: http://127.0.0.1:8756 (`--reload`なし)
- フロントエンド (ビルド済みファイルの配信): http://localhost:4173

フロントエンドだけを先にビルドしたい場合は `npm run build` を単体で実行できます（`frontend/dist/` に出力）。

## 停止方法

`npm run dev` / `npm run start` を実行しているターミナルで **Ctrl+C** を押してください。バックエンド・フロントエンドの両方のプロセスがまとめて停止します（片方が異常終了した場合も、もう片方を自動的に停止します）。

個別に `uvicorn` や `vite` を起動していた場合は、それぞれのターミナルで Ctrl+C を押してください。

## ブラウザからのアクセスURL

| モード | URL |
|---|---|
| 開発 (`npm run dev`) | http://localhost:5173 |
| 本番プレビュー (`npm run start`) | http://localhost:4173 |
| バックエンドAPI | http://127.0.0.1:8756 |
| バックエンドAPIドキュメント (Swagger UI) | http://127.0.0.1:8756/docs |

## LAN内の別端末からアクセスする方法

デフォルトでは `127.0.0.1` / `localhost` からのアクセスのみを許可しており、LAN内の他の端末（スマホ・タブレット・別PCなど）からは開けません。対応させるには以下の手順を行ってください。

1. **このPCのLAN IPアドレスを確認する**

   ```powershell
   ipconfig
   ```

   `IPv4 アドレス` の値（例: `192.168.1.20`）を使います。

2. **バックエンドをLAN公開用に起動する** (`KAIRO_HOST` を `0.0.0.0` に設定)

   `backend/.env` に以下を追加する（`npm run dev` / `npm run start` の両方が読み込みます）:

   ```
   KAIRO_HOST=0.0.0.0
   ```

   一時的にこの回だけ変更したい場合は、`.env` を編集する代わりに実行前にPowerShellの環境変数として設定しても構いません:

   ```powershell
   $env:KAIRO_HOST = "0.0.0.0"
   npm run dev
   ```

3. **バックエンドのCORS許可オリジンにLAN側フロントエンドのURLを追加する**

   `backend/.env` を編集し、以下の行を追加（`192.168.1.20` は手順1で確認した自分のIPに置き換え）:

   ```
   KAIRO_CORS_ORIGINS=http://192.168.1.20:5173
   ```

4. **フロントエンドのAPI接続先をこのPCのIPに向ける**

   `frontend/.env` を編集し、以下のように設定:

   ```
   VITE_API_BASE=http://192.168.1.20:8756
   ```

5. **フロントエンドもLAN待受で起動する**

   ```powershell
   npm --prefix frontend run dev -- --host 0.0.0.0
   ```

6. 別の端末のブラウザで `http://192.168.1.20:5173` を開く

Windows Defender ファイアウォールの確認ダイアログが出た場合は、プライベートネットワークでのアクセスを許可してください。設定を元に戻す場合は、`backend/.env` の `KAIRO_HOST` / `KAIRO_CORS_ORIGINS` と `frontend/.env` の `VITE_API_BASE` の変更行を削除またはコメントアウトしてください（PowerShellの `$env:KAIRO_HOST` で一時設定した場合は、新しいターミナルを開けば解除されます）。

## 環境変数の設定方法

環境変数は `backend/.env` と `frontend/.env` の2つのファイルで管理します（どちらも `.gitignore` 対象で、Gitにはコミットされません）。`npm run setup` を実行すると、それぞれのサンプルファイルから自動生成されます。手動で作る場合は次の通りです。

```powershell
Copy-Item backend/.env.example backend/.env
Copy-Item frontend/.env.example frontend/.env
```

### `.env.example` の説明

- **`backend/.env.example`**: バックエンド (FastAPI) が読む環境変数のサンプルです。データ保存先、LM StudioのURL/モデル名/タイムアウト、faster-whisperのモデルサイズ/実行デバイス/演算精度、LAN公開時の追加CORSオリジンをコメント付きで記載しています。値を省略した項目は、コード側 (`backend/app/core/config.py`) のデフォルト値が使われます。
- **`frontend/.env.example`**: フロントエンド (Vite) が読む環境変数のサンプルです。バックエンドAPIのベースURL (`VITE_API_BASE`) のみを定義しています。Viteの仕様上、`VITE_` で始まる変数だけがブラウザ側コードから参照可能です。

主な設定項目 (`backend/.env`):

| 変数名 | デフォルト値 | 説明 |
|---|---|---|
| `KAIRO_DATA_ROOT` | `<リポジトリルート>/data` | 動画・DB・ログの保存先ディレクトリ |
| `KAIRO_LLM_BASE_URL` | `http://localhost:1234/v1` | LM Studio (OpenAI互換API) のベースURL |
| `KAIRO_LLM_MODEL` | `local-model` | LM Studioに渡すモデル名 |
| `KAIRO_LLM_TIMEOUT` | `120` | LLMリクエストのタイムアウト秒数 |
| `KAIRO_WHISPER_MODEL` | `small` | faster-whisperのモデルサイズ (`tiny`/`base`/`small`/`medium`/`large-v3`) |
| `KAIRO_WHISPER_DEVICE` | `cpu` | 文字起こしの実行デバイス (`cpu` / `cuda`) |
| `KAIRO_WHISPER_COMPUTE` | `int8` | 演算精度 |
| `KAIRO_CORS_ORIGINS` | (空、未設定) | LAN公開時などに追加で許可するオリジン（カンマ区切り） |
| `KAIRO_HOST` | `127.0.0.1` | (npm scriptsが参照) バックエンドの待受アドレス |
| `KAIRO_PORT` | `8756` | (npm scriptsが参照) バックエンドの待受ポート |

主な設定項目 (`frontend/.env`):

| 変数名 | デフォルト値 | 説明 |
|---|---|---|
| `VITE_API_BASE` | `http://127.0.0.1:8756` | フロントエンドが呼び出すバックエンドAPIのURL |

## データベースの初期化

Kairo は SQLite (`data/kairo.db`) を使用しています。テーブルはバックエンド起動時 (`backend/app/main.py` の `on_startup`) に `SQLAlchemy` の `create_all` で **自動作成**されるため、通常は追加の初期化コマンドは不要です。

明示的にDBだけを初期化したい場合（初回セットアップの動作確認や、DBファイルを作り直した直後の確認など）は以下を実行してください。

```powershell
npm run db:init
```

> このプロジェクトには現時点でマイグレーションツール（Alembic等）は導入されていません。テーブル定義 (`backend/app/models/`) を変更した場合は、開発中であれば `data/kairo.db` を削除して `npm run db:init` するか、次回起動時の自動作成に任せてください（既存データが必要な場合は事前にバックアップしてください）。

## LM Studio のセットアップ

AI編集（自然言語での編集指示）とAI自動制作（企画・台本の自動生成）機能は、ローカルで動くLLMサーバーを利用します。このプロジェクトは [LM Studio](https://lmstudio.ai/) を前提にしていますが、OpenAI互換の `/v1/chat/completions` APIを持つ他のローカルサーバーでも動作します。**クラウドAPIへのフォールバックは一切行われません**（LM Studioに接続できない場合は、AI機能がはっきりしたエラーメッセージで失敗します）。

1. **LM Studioをインストール**: https://lmstudio.ai/ からダウンロードし、インストーラーを実行
2. **モデルを用意**: LM Studioのホーム画面の検索から、日本語に対応したチャット/instructモデル（例: `google/gemma-3-...`, `Qwen2.5-...-Instruct` など、お使いのPCのメモリに合ったサイズのもの）をダウンロード
3. **LM Studioを起動**: アプリを開き、ダウンロードしたモデルを画面上部からロード
4. **Local Serverを起動**: 左側のサイドバーから `Developer` (`</>` アイコン) タブを開き、`Start Server` をクリック（デフォルトポートは `1234`）
5. **必要なAPI URLを設定**: デフォルトでは `backend/.env` の `KAIRO_LLM_BASE_URL=http://localhost:1234/v1` のままで動作します。LM Studioのポートを変更した場合のみ、この値をLM Studio側の表示に合わせて変更してください
6. **アプリを起動**: `npm run dev` でKairoを起動し、エディタ画面上部（編集タブ）またはAI制作タブに表示される **「LM Studio: 接続済み」** の表示を確認

接続状況は `GET /api/llm/status` でも確認できます。

```powershell
curl http://127.0.0.1:8756/api/llm/status
```

LM Studioが起動していない・Local Serverが無効な場合は、UI上に **「LM Studio: 未接続」** と表示され、AI編集/AI自動制作を実行するとジョブが失敗し、「LM Studioに接続できません」という具体的な日本語エラーメッセージがジョブのステータス欄に表示されます（`backend/app/services/llm_client.py`）。動画の読み込み・タイムライン編集・字幕生成・レンダリングなど、LM Studioを使わない機能は影響を受けず通常通り利用できます。

## 動画生成機能 (実験的)

写真をアップロードして短いImage-to-Video動画をローカルで生成できます(エディタ画面の`生成`タブ)。クラウドAPIは一切使用せず、[Stable Video Diffusion (img2vid)](https://huggingface.co/stabilityai/stable-video-diffusion-img2vid) をCPU上でPyTorch/diffusers経由で実行します。

### セットアップ

`npm run setup` では動画生成用の依存関係(PyTorch/diffusersなど、数百MB)はインストールされません。マルチGBのダウンロードを伴うため、使う場合のみ明示的にインストールしてください。

```powershell
backend\.venv\Scripts\pip install -r backend/requirements-videogen.txt
```

初回生成時にStable Video Diffusionのモデル本体(約9.5GB)を自動ダウンロードし、`data/models/`に保存します(以降はオフラインで再利用されます)。

### 使い方と制約

1. `生成`タブを開き、画像(JPG/PNG/WebP)をドラッグ&ドロップ
2. 「Generate」を押すとジョブが開始し、進捗が表示されます
3. 完了すると生成された動画がプロジェクトのMedia Binに自動追加されます(通常の読み込み動画と同じように編集・タイムライン追加が可能)

**重要な制約(実機検証済み)**:

- **CPU実行のみ**: このPC(Intel Core Ultra 7 155H / Arc内蔵GPU)にはIntel GPU/OpenVINO/DirectML等のアクセラレーションは未実装です。生成は非常に低速です(下記実測値参照)。
- **テキストプロンプト非対応**: Stable Video Diffusionのimg2vidパイプラインには文字起こしタキストエンコーダがなく、入力画像と動きの強さのみから生成されます。プロンプト欄はUI上に残していますが、このエンジンでは無視されます(将来、プロンプトに対応するエンジンを追加する際のための共通インターフェースです)。
- **非商用ライセンス**: Stable Video Diffusion Non-Commercial Research Community Licenseのため、商用利用不可です。個人利用・検証目的に限られます。

### 実機検証結果 (このPC: Intel Core Ultra 7 155H / RAM 32GB / CPU実行)

| 設定 | 解像度 | フレーム数 | ステップ数 | 実測時間(推論のみ) |
|---|---|---|---|---|
| 軽量(APIデフォルト) | 384×256 | 8 | 6〜10 | 約4.7分(6ステップ時、47秒/ステップ) |
| モデルデフォルト | 512×320 | 14 | 15 | 約35分以上(135秒/ステップ、実測は5/15ステップで打ち切り時点の推定) |

軽量設定をAPI/UIのデフォルトとしています。`推定生成時間`はこの実測値から機械が算出した目安で、確定値ではありません(design doc section 15の方針通り)。

### 動画生成エンジンの追加

`backend/app/services/video_engines/`配下に`VideoGenerationEngine`を実装したクラスを追加し、`video_engines/__init__.py`の`_REGISTRY`に登録することで、別のモデル(将来的なIntel GPU対応版・より高品質なモデルなど)に差し替え/追加できます。Kairo本体やUIは特定モデルに依存しません。

## トラブルシューティング

### よくあるエラーと対処方法

| 症状 / エラー | 原因 | 対処方法 |
|---|---|---|
| `npm run setup` で `Python 3.10以上が見つかりません` | PythonがPATHに無い、または未インストール | Python 3.10をインストールし、インストール時に「Add python.exe to PATH」をチェック。インストール後はターミナルを開き直す |
| `backend/.venv が見つかりません。先に npm run setup を実行してください。` | セットアップ未実行、または `backend/.venv` を削除した | `npm run setup` を実行 |
| 起動時に `'ffmpeg' was not found on PATH` | FFmpeg未インストール、またはPATH未反映 | `winget install Gyan.FFmpeg` を実行後、ターミナルを開き直す。`ffmpeg -version` で確認 |
| ブラウザで開いても真っ白 / APIエラーが出る | バックエンドが起動していない、またはポート不一致 | `npm run dev` の出力でバックエンド (`uvicorn`) がエラー無く起動しているか確認。`http://127.0.0.1:8756/api/health` が `{"status":"ok"}` を返すか確認 |
| `LM Studio: 未接続` と表示される / AI編集が失敗する | LM StudioのLocal Serverが起動していない | LM Studioを起動し、`Developer`タブで`Start Server`を押す。ポートを変更している場合は `backend/.env` の `KAIRO_LLM_BASE_URL` を合わせる |
| 字幕生成の初回実行が非常に遅い / フリーズしたように見える | faster-whisperのモデルをHugging Faceから初回ダウンロード中 | 初回のみインターネット接続が必要です。しばらく待ってください（`KAIRO_WHISPER_MODEL` を `tiny` や `base` に下げると軽くなります） |
| `EADDRINUSE` / ポートが既に使用されています (`8756` または `5173`) | 他プロセスが同じポートを使用中、前回のプロセスが終了していない | タスクマネージャーで `python.exe` / `node.exe` を確認して終了するか、`KAIRO_PORT` で別ポートを指定して起動 |
| 別端末からアクセスできない | LAN公開の設定が未対応（デフォルトは`localhost`限定） | [LAN内の別端末からアクセスする方法](#lan内の別端末からアクセスする方法) を参照 |
| `npm run build` / `npm run dev` で `EPERM` や権限エラー | ウイルス対策ソフトやOneDriveの同期がファイルをロックしている | リポジトリをOneDrive等の同期対象外のフォルダに置く、または対象ソフトの除外設定に追加 |
| PowerShellで `.ps1 は実行できません` のようなエラー | 実行ポリシーの制限（このプロジェクトのスクリプトは `.mjs`/Node.js製のため通常は該当しません） | `npm run <script>` はNode.jsで実行されるため影響を受けません。他のツールで発生した場合はそのツールのドキュメントを参照 |

### それでも解決しない場合

1. `npm run check` を実行し、フロントエンドの型エラー・lintエラーやバックエンドのimportエラーが無いか確認してください
2. バックエンドのログ（`npm run dev` を実行しているターミナルの出力）にPythonの例外スタックトレースが出ていないか確認してください
3. `data/projects/<プロジェクトID>/logs/` にレンダリングジョブのログが出力される場合があります

## プロジェクトのディレクトリ構成

```
Kairo/
├── package.json          # ルートのnpmスクリプト (setup/dev/build/start/db:init/check)
├── scripts/               # ルートnpmスクリプトの実装 (Node.js, OS非依存)
│   ├── lib.mjs
│   ├── setup.mjs
│   ├── dev.mjs
│   ├── start.mjs
│   ├── db-init.mjs
│   └── check.mjs
├── backend/                # FastAPI バックエンド
│   ├── .venv/               # Python仮想環境 (npm run setupで作成, Git管理外)
│   ├── .env.example          # 環境変数サンプル
│   ├── requirements.txt      # Python依存パッケージ (基本機能)
│   ├── requirements-videogen.txt  # 動画生成用の追加依存関係 (任意インストール)
│   ├── app/
│   │   ├── main.py            # FastAPIアプリのエントリーポイント
│   │   ├── core/               # 設定・DB接続・パス解決
│   │   ├── api/                 # APIルーター (projects/media/timeline/jobs/subtitles/cut/ai_edit/production/generation/system)
│   │   ├── models/               # SQLAlchemyモデル
│   │   ├── schemas/               # Pydanticスキーマ
│   │   └── services/               # ビジネスロジック
│   │       ├── video_engines/        # 動画生成エンジン抽象化 (VideoGenerationEngine, SVDEngine)
│   │       ├── video_generation_service.py  # 画像→動画生成ジョブ
│   │       ├── system_info_service.py       # PC/AI環境診断
│   │       ├── generation_diagnostics.py    # 生成失敗時のエラー原因分析
│   │       └── (FFmpeg連携, LLMクライアント, 文字起こし 等)
│   └── tests/                # (現状テストファイルは未追加)
├── frontend/                # React + Vite フロントエンド
│   ├── .env.example           # 環境変数サンプル
│   ├── package.json
│   ├── src/
│   │   ├── main.tsx / App.tsx
│   │   ├── pages/               # ProjectList, Editor
│   │   ├── components/          # MediaBin, Timeline, AIEditPanel, ProductionPanel 等
│   │   ├── api/client.ts        # バックエンドAPIクライアント
│   │   └── hooks/ , utils/
│   └── dist/                 # `npm run build` の出力 (Git管理外)
└── data/                    # 実行時に自動生成される保存先 (Git管理外)
    ├── kairo.db               # SQLiteデータベース
    └── projects/<project_id>/   # プロジェクトごとの素材・レンダリング結果・ログ
```

## 開発者向け情報

### npm scripts 一覧 (リポジトリルート)

| コマンド | 内容 |
|---|---|
| `npm run setup` | 初回セットアップ（Python venv作成・pip install・npm install・.env作成・ffmpeg確認） |
| `npm run dev` | 開発サーバー起動（バックエンド `--reload` + フロントエンド Vite dev server） |
| `npm run build` | フロントエンドの本番ビルド (`frontend/dist/` を生成) |
| `npm run start` | 本番モード起動（未ビルドなら自動ビルドしてから、`--reload`無しのバックエンド + `vite preview`） |
| `npm run db:init` | SQLiteデータベースのテーブルを明示的に初期化（通常は起動時に自動実行されるため任意） |
| `npm run check` | フロントエンドのlint (`oxlint`) + 型チェック (`tsc -b`)、バックエンドのimport確認をまとめて実行 |

いずれもリポジトリのルートで実行してください（内部で `backend/` `frontend/` 双方のプロセスを起動・管理します）。

### バックエンド個別コマンド

```powershell
# 仮想環境を有効化（任意。npm scriptsは有効化なしで直接venvのpythonを呼びます）
backend\.venv\Scripts\Activate.ps1

# APIドキュメント (Swagger UI)
# npm run dev 実行中に http://127.0.0.1:8756/docs を開く
```

### フロントエンド個別コマンド

```powershell
npm --prefix frontend run dev       # devサーバーのみ
npm --prefix frontend run build     # ビルドのみ
npm --prefix frontend run preview   # ビルド済みdistの配信のみ
npm --prefix frontend run lint      # oxlintのみ
```

### テストについて

現状、`backend/tests/` にテストファイルは未追加です。フロントエンドにも自動テストは未設定です。`npm run check` によるlint・型チェック・importチェックが、現在利用可能な自動検証手段です。

### 技術スタック

- バックエンド: FastAPI, SQLAlchemy (SQLite), faster-whisper, FFmpeg (subprocess経由)
- フロントエンド: React 19, TypeScript, Vite
- AI (テキスト): LM Studio等のローカルLLM (OpenAI互換 `/v1/chat/completions`)
- AI (動画生成・実験的): PyTorch (CPU版) + diffusers + Stable Video Diffusion (`requirements-videogen.txt`、任意インストール)
