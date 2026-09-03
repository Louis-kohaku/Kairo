# Kairo

ローカル環境で完結する **AI動画制作スタジオ** です。一言の指示から、Webリサーチ・制作戦略・企画・脚本・シーン設計・素材生成・ナレーション・BGM/効果音・字幕・編集・品質チェック・自動改善・MP4書き出しまでをAIが一貫して実行します。制作中は「AIが今なにをしているのか」が常に画面に表示され、チャットから「もっとテンポよくして」のように介入して実際のプロジェクトを変更できます。手動編集も従来どおり利用でき、AI生成と自由に組み合わせられます。

動画素材を1つも持っていなくても、最後まで再生できるMP4が完成します。外部クラウドサービスにデータを送ることはありません（唯一の例外として、任意機能のWebリサーチのみ検索クエリを送信します）。

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
- [3つの制作モード](#3つの制作モード)
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
- [AIモデルの準備](#aiモデルの準備)
- [ユーザー素材（写真・動画）について](#ユーザー素材写真動画について)
- [字幕について](#字幕について)
- [Webリサーチについて](#webリサーチについて)
- [動画生成機能 (実験的)](#動画生成機能-実験的)
- [トラブルシューティング](#トラブルシューティング)
- [プロジェクトのディレクトリ構成](#プロジェクトのディレクトリ構成)
- [開発者向け情報](#開発者向け情報)

---

## プロジェクト概要

Kairo は、動画素材の取り込み → タイムライン編集 → 無音部分の自動カット → 字幕の自動生成 → AI (ローカルLLM) による編集指示・企画/台本の自動生成 → FFmpegでの書き出し、という一連の動画制作フローをブラウザUIから行えるローカル動作のツールです。クラウドAPIキーは不要で、AI機能は LM Studio 等のローカルLLMサーバーと通信して動作します。

## 3つの制作モード

Kairoを開くと、まず作り方を選びます。どのモードで作ったプロジェクトも、後からモードを行き来できます。

| モード | 概要 | 向いている場面 |
|---|---|---|
| **⚡ Full Auto** | 一言入力して放置するだけ。企画から書き出しまでAIが最後まで進めます | とにかく1本作りたい |
| **💬 AI Co-Creation** | AIが制作を進めつつ、チャットの指示で実際のプロジェクトを変更します | 方向性を調整しながら作りたい |
| **✂ Manual** | 素材読み込み・タイムライン編集・字幕・書き出しを自分で行います | 自分の素材で細かく作りたい |

### Full Auto の流れ

```
一言の指示（＋あれば自分の写真・動画）
  ↓ 制作環境確認 → AIモデル確認 → 素材解析 → Webリサーチ → トレンド分析 → 制作戦略
  ↓ 企画 → 脚本 → Scene設計 → 素材マッチング → 素材生成 → 音声 → BGM/SFX → 字幕 → 編集
  ↓ 品質チェック → 自動改善 → 再チェック → プレビュー → 書き出し
MP4完成
```

21の工程それぞれについて、**現在のフェーズ / 現在の作業 / 対象 / 目的 / 使用モデル / 次の処理** が画面に表示されます。制作中はいつでも一時停止・停止でき、再開すると完了済みの工程はやり直さず途中から続きます。

素材を渡した場合は、**素材解析**（何が写っているかを把握）が脚本より先に走り、脚本はその素材で撮れている画を前提に書かれます。**素材マッチング**でどのシーンにどの素材を使うかが決まり、足りないカットだけが補完されます。素材を渡さない場合、この2工程は「素材なし」としてスキップされ、これまでどおり最後まで自動で完成します。

### AI Co-Creation の流れ

チャットの指示は返答で終わりません。AIが現在のScene・尺・字幕・タイムラインを読んだうえで**変更案**を提示し、「適用」を押すと実際のプロジェクトが書き換わります（尺が変わったシーンは映像も再生成され、字幕とBGMも同期し直されます）。気に入らなければ「元に戻す」で戻せます。

```
「もっとテンポよくして」
  → AIが現在の構成を分析
  → 変更案: 全体の尺 69秒 → 59秒（理由付き）
  → [適用] → 全シーン再生成 + 字幕再同期 + タイムライン更新
  → [元に戻す] でいつでも復元
```

## 主な機能

- **AI制作スタジオ (Full Auto / AI Co-Creation)**: 一言の指示からMP4完成まで。19工程の進捗・AI作業状況・使用モデルをリアルタイム表示
- **Webリサーチ → 制作戦略**: 同じテーマの動画がどう作られているかを調べ、「共通トレンド」と「差別化機会」に分けて抽出し、Hook・テンポ・字幕方針・音・終わり方を決めた制作戦略に落とし込みます（模倣ではなく傾向の参考として利用）
- **ショート動画向けScene設計**: シーンごとに尺・目的・感情・カメラ・映像内容・字幕・効果音・トランジションを設計。ナレーションと画面上の字幕は別物として扱います
- **ユーザー素材からの自動編集**: オートモードの開始画面で写真・動画をドラッグ＆ドロップすると、AIが内容を解析し、台本・ナレーション・構成に合わせて並び順・使用時間・カット位置を決めて編集します。詳細は[ユーザー素材について](#ユーザー素材写真動画について)
- **素材ゼロでの制作**: 手持ち素材がなくても、シーンの感情と内容から配色・光・粒子・構図を組み立てて映像素材を生成します（ダウンロード不要・CPUのみ）。ユーザー素材がある場合は必ずそちらが優先されます
- **ナレーション・BGM・効果音**: Windows標準の音声合成でナレーションを生成し、実測の長さに合わせてシーン尺を自動調整。BGMは雰囲気に合わせて生成し、ナレーション中は自動的に音量が下がります（サイドチェイン・ダッキング）
- **品質チェックと自動改善**: 完成後に構成・テンポ・Hook・つながり・字幕・音・終わり方などを点検し、直せる問題は自動修正して理由とともに提示。直せない指摘は「自動修正不可」と明示します
- **AIモデル管理**: 今回どのAIを何に使うのかを動的に表示。LM Studioのモデルは「ダウンロード済み」と「メモリに読み込み済み」を区別し、未準備の場合は具体的な対処手順を案内します
- **一時停止 / 停止 / 再開**: 制作中に中断でき、再開時は完了済み工程をスキップして途中から続行します
- **ユーザー向けログと技術ログの分離**: 通常は日本語の作業ログ、必要なときだけリクエストやFFmpegの詳細を展開
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
| `KAIRO_LLM_MODEL` | (未設定=自動検出) | LM Studioに渡すモデル名。未設定の場合、Kairoが起動時にLM Studioの`/v1/models`から利用可能なモデルを自動検出し、PC性能に応じて推奨されるモデルを自動選択します（Kairo UIの「設定 > AI」からAuto/Manualの切り替え・モデル変更も可能）。 |
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

## AIモデルの準備

Kairoは制作を始める前に、**今回どのAIを何に使うのか**を一覧で表示します（Full Auto / AI Co-Creationの開始画面右側、および制作中の左サイドバー）。モデル名はすべてLM Studioとこのマシンの実際の状態から解決され、ハードコードされたモデル名は一つもありません。

| 役割 | 使用するもの |
|---|---|
| 企画・構成 / 脚本・Scene生成 / リサーチ分析 / 品質チェック / AI Co-Creation | LM Studio のチャットモデル |
| 映像素材生成 | Kairo Composer（ローカル合成・ダウンロード不要） |
| 音声合成 | Windows SAPI（インストール済みの音声） |
| 動画編集・書き出し | FFmpeg |

### ダウンロード済みとロード済みの違い

LM Studioの `/v1/models` は「ダウンロード済み」のモデルをすべて返すため、メモリに読み込まれていないモデルも一覧に出ます。Kairoは LM Studio の `/api/v0/models` から実際の状態を取得し、以下を区別して表示します。

- **● メモリに読み込み済み** — すぐに応答が返ります
- **○ ダウンロード済み** — 最初のリクエスト時にLM Studioが自動で読み込むため、**初回だけ数十秒〜数分かかります**（この旨は開始画面に警告として表示されます）

「今すぐ読み込む」ボタンから事前に読み込んでおくこともできます。

### 必要なモデルが無い場合

Kairoが**勝手に大容量モデルをダウンロードすることはありません**。未準備のときは、開始画面に何が足りないかと具体的な手順が表示され、制作開始ボタンは無効になります。

```
⚠ このままでは制作を開始できません
LM Studio(http://localhost:1234/v1)に接続できません。

・LM Studioを起動する
・LM StudioのDeveloper(Server)タブでLocal Serverを起動する
・エンドポイントが合っているか確認する
```

### モデルの選び方

「モデルを選ぶ」から、用途・量子化・サイズ・コンテキスト長・読み込み状態つきの一覧を見て選べます。「自動選択に戻す」を押すと、KairoがPCのメモリとGPUに合わせて選び直します。

**モデルサイズと速度**: 7B前後のモデルをCPU/内蔵GPUで動かす場合、脚本生成の1リクエストに数分かかることがあります。制作が遅いと感じたら、より小さいモデル（2B〜4B級）に切り替えると大幅に速くなります。応答が制限時間内に返らない場合は「AIモデルの応答が時間内に返りませんでした」という専用のエラーが表示され、小さいモデルへの切り替えが提案されます（待ち時間の上限は `KAIRO_LLM_TIMEOUT`、既定600秒）。

## ユーザー素材（写真・動画）について

オートモード（Full Auto / AI Co-Creation）の開始画面は、次の順番になっています。

```
① 作りたい動画   「この写真と動画を使って沖縄旅行の30秒Shortsを作って」
② 素材           写真・動画をドラッグ＆ドロップ（任意）
③ 動画設定       縦型 9:16 / 30秒
④ 制作開始       素材プランを確認して開始
```

**素材は必須ではありません。** 何も渡さなければ、必要な素材はKairoが用意します。

### 対応形式

| 種類 | 拡張子 |
|---|---|
| 写真 | `.jpg` `.jpeg` `.png` `.webp` `.bmp` `.gif` `.tif` `.tiff` |
| 動画 | `.mp4` `.mov` `.mkv` `.webm` `.avi` `.m4v` |
| 音声 | `.mp3` `.wav` `.m4a` `.aac` `.flac` `.ogg` |

複数ファイルを一度に投入できます。読み込めなかったファイルがあっても、他のファイルの取り込みは続行され、**そのファイルだけ**「何が原因か」と「どうすればよいか」が表示されます（例:「動画コーデックが対応していません」「ファイルサイズが大きすぎます」）。

### 素材解析

アップロードされた素材は次のように解析され、タグが付きます。

- **Vision対応モデルがLM Studioにロードされている場合**: 画像/動画のフレームをそのモデルに見せ、写っているもの（海・飛行機・夕日・人物・食事など）を認識します。素材カードには「AI画像解析」と表示されます
- **ロードされていない場合**: 画像認識は行いません。解像度・向き・明るさ・動きの量・ファイル名から推定し、「ファイル名・画像情報から推定」と明示します（AIが見たかのように見せることはしません）

動画については、長さ・縦横・明るさ・動きの量に加えて、**使用可能な区間**（先頭や末尾の真っ暗な部分を除いた範囲）を判定し、カットはその区間から取られます。

### 素材の使い方

| モード | 動作 |
|---|---|
| **AIにおまかせ**（既定） | 内容が合う素材をAIが選び、順番・使用時間・カット位置を決めます |
| **できるだけ全部使う** | アップロードした素材をできる限りすべて登場させます |
| **選択した素材だけ使う** | チェックを入れた素材だけを使います |

### 素材の優先順位

映像に使う素材は、必ずこの順で選ばれます。

1. ユーザーがアップロードした**動画**
2. ユーザーがアップロードした**写真**
3. ローカル素材（※Kairoにはまだ共通のローカル素材ライブラリがないため、現状この段は常に空です）
4. ライセンスを確認できるWeb素材（Openverse / Wikimedia Commons。CC・パブリックドメインのみ）
5. AI生成素材（Stable Diffusionを導入している場合のみ）
6. 抽象背景（Kairoが構成する映像）

**ユーザー素材が残っているのに抽象背景が使われることはありません。** 内容が一致する素材がない場合でも、余っているユーザー素材が先に配置されます（その場合は「内容の一致は確認できていません」と理由に表示されます）。

補完に使えるソースは環境によって変わるため、**実際に使えるものだけ**が素材プランに表示されます。ネットワークが使えない場合は「Web素材は利用できません」、Stable Diffusion未導入なら「AI画像生成モデルは未導入です」と明示され、抽象背景で補完されます。

### 素材プラン

制作開始前に、素材の状況が表示されます。

```
素材プラン
  ユーザー素材   写真：8枚 / 動画：3本
  不足素材       沖縄のブランコ：1 / 海岸の動画：1
  補完方法       Web素材：1 / AI生成：1
```

開始前は**見込み**（シーン数がまだ決まっていないため）、素材マッチング工程の完了後はシーンごとの実際の割り当てが表示されます。

### 完成後の確認

完成した動画の「使用素材」タブで、**どのカットがどこから来たのか**を時間つきで確認できます。

```
使用素材
  ユーザー素材   IMG_001.jpg  0:03〜0:06
                 beach.mp4    0:08〜0:11（元素材 0:02〜）
  AI生成         ○○           0:13〜0:15
```

プレビューのタイムラインでクリップをクリックすると、そのカットの出所がタイムライン下に表示されます。

### 後から素材を追加する

制作が終わったあとでも「素材」タブから追加できます。「追加素材を反映して作り直す」を押すと、追加分を含めて全シーンを再評価し、**素材が変わったシーンだけ**を作り直してタイムラインを更新し、MP4を書き出し直します。変わらなかったシーンは再エンコードされません。

## 字幕について

字幕は制作フェーズで自動生成され、ナレーションとは別の「画面に出す短い言葉」として設計されます。

- **字幕サイズは実際の出力ピクセル数です**（設定 > 字幕）。既定値は88pxで、1080×1920のショート動画でサムネイルサイズでも読める大きさです
- 1行の文字数は、フレーム幅と字幕サイズから自動計算されます（88pxなら約10文字）。それを超える字幕は2行に折り返され、収まらない場合は「…」で明示的に省略されます
- スマートフォンのUIと重ならないよう、左右7.5%・下12%のセーフエリアを確保しています
- 焼き込みにはKairoが生成したASSファイルを使用します。フレームサイズと同じ`PlayRes`を宣言しているため、設定した数値がそのまま出力ピクセルになります（SRTをFFmpegに渡す方式では、変換時の基準解像度に応じて数倍の大きさで描画されてしまいます）
- 他の編集ソフトで使える`.srt`も同時に書き出されます

## Webリサーチについて

Full Auto / AI Co-Creationの「Webリサーチ」工程は、同じテーマの動画がどう作られているかを調べ、**共通トレンド**と**差別化機会**に分けて整理し、制作戦略に反映します。

- 送信されるのは検索クエリのみです。プロジェクトの内容や素材が外部に送られることはありません
- 取得したページの文章をそのまま使うことはありません。構成・テンポ・字幕の傾向といった抽象的な参考としてのみ利用します
- 参照したページは「調査・戦略」タブに一覧表示され、リンクから確認できます
- **オフラインでも問題ありません**。検索できない場合は「Webリサーチは実行できませんでした」と理由が表示され、ショート動画の一般的な定石を使って制作が続行します
- 取得先のURLは検証され、内部ネットワーク宛（localhost・プライベートIP等）やhttp/https以外のURLは取得しません

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
| 制作が「AIモデルの応答が時間内に返りませんでした」で止まる | モデルが大きく、PCの処理能力に対して生成が遅い | 「モデルを選ぶ」からより小さいモデル（2B〜4B級）に切り替える。または `backend/.env` の `KAIRO_LLM_TIMEOUT` を延ばす。停止した制作は「続きから再開」で途中から再開できます |
| 制作の最初のリクエストだけ極端に遅い | モデルがダウンロード済みだがメモリに読み込まれておらず、LM Studioが読み込み中 | 正常な動作です。開始画面の「モデルを選ぶ → 今すぐ読み込む」で事前に読み込んでおけます |
| 「Webリサーチは実行できませんでした」と表示される | オフライン、または検索サービスに到達できない | 制作は一般的な定石を使って続行されるため、対処は不要です。リサーチを使いたい場合はネットワーク接続を確認してください |
| ナレーションが入らない / 「音声合成が使えない」と表示される | Windows以外のOS、または音声がインストールされていない | Windowsの「設定 > 時刻と言語 > 音声」から音声を追加。無い場合は字幕のみの動画として完成します |
| チャットで指示しても「制作の実行中は変更を適用できません」と出る | Full Autoの実行中は競合を避けるため変更を受け付けません | 「一時停止」を押してから指示するか、完成を待ってください |
| 品質チェックに「自動修正不可」の指摘が残る | 構成や映像の作り直しなど、機械的に直せない内容 | AI Co-Creationのチャットから「Scene 3をもっと面白くして」のように具体的に指示してください |
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
│   │   ├── api/                 # APIルーター (projects/media/materials/timeline/jobs/subtitles/cut/ai_edit/production/generation/system/studio)
│   │   ├── models/               # SQLAlchemyモデル (studio.py = 制作ラン・イベント・変更案・チャット)
│   │   ├── schemas/               # Pydanticスキーマ (studio.py = 各AI工程のJSON契約)
│   │   └── services/               # ビジネスロジック
│   │       ├── studio/               # AI制作スタジオ
│   │       │   ├── phases.py            # 21工程の定義 (唯一の正)
│   │       │   ├── pipeline.py          # Full Autoオーケストレーター
│   │       │   ├── events.py            # 制作イベント (進捗UI・ログの共通ソース)
│   │       │   ├── control.py           # 一時停止 / 停止 / 再開
│   │       │   ├── run_service.py       # 制作ランのライフサイクル
│   │       │   ├── model_service.py     # 使用AIの解決・LM Studio状態・モデル準備案内
│   │       │   ├── research_service.py  # Webリサーチ + トレンド分析 (SSRF対策込み)
│   │       │   ├── planning_service.py  # 制作戦略 → 企画 → 脚本 → Scene設計
│   │       │   ├── material_service.py  # 映像素材・ナレーション・シーンクリップ生成・不足素材の補完
│   │       │   ├── material_analysis.py # ユーザー素材の解析 (Vision AI / 画素計測 / ファイル名)
│   │       │   ├── material_plan.py     # どのシーンにどの素材を使うかの決定と不足の洗い出し
│   │       │   ├── material_usage.py    # 完成動画の「使用素材」レポート
│   │       │   ├── material_reeval.py   # 後から追加した素材の反映 (再マッチ→再生成→再書き出し)
│   │       │   ├── web_material_service.py # ライセンス確認済みWeb素材の検索・取得 (Openverse)
│   │       │   ├── assembly_service.py  # 字幕生成・BGM生成・タイムライン組み立て
│   │       │   ├── quality_service.py   # 品質チェックと自動改善
│   │       │   └── cocreation_service.py # チャット指示 → 変更案 → 適用 / 取り消し
│   │       ├── image_engines/        # 映像素材生成 (procedural = 常時利用可, sd = 任意)
│   │       ├── ffmpeg/                # engine.py (唯一のffmpeg実行点) + compose.py (素材合成)
│   │       ├── video_engines/        # 動画生成エンジン抽象化 (VideoGenerationEngine, SVDEngine)
│   │       ├── system_info_service.py       # PC/AI環境診断
│   │       ├── ai_diagnostics.py             # 失敗時のエラー原因分析
│   │       └── (LLMクライアント, 文字起こし, TTS 等)
│   └── tests/                # (現状テストファイルは未追加)
├── frontend/                # React + Vite フロントエンド
│   ├── .env.example           # 環境変数サンプル
│   ├── package.json
│   ├── src/
│   │   ├── main.tsx / App.tsx
│   │   ├── pages/               # Home, Studio, Editor, ProjectList, SettingsPage
│   │   ├── studio.css           # 制作スタジオのスタイル (レスポンシブ対応)
│   │   ├── components/
│   │   │   ├── studio/            # ProductionProgress, AIActivity, ModelPlanPanel,
│   │   │   │                      # StudioLauncher, CoCreationChat, QualityPanel,
│   │   │   │                      # ResearchPanel, SceneBoard, ProductionLog, StudioCompletion,
│   │   │   │                      # MaterialPanel, MaterialPlanPanel, MaterialUsagePanel
│   │   │   └── (MediaBin, Timeline, AIEditPanel, ProductionPanel 等)
│   │   ├── api/client.ts        # バックエンドAPIクライアント
│   │   └── hooks/ , utils/
│   └── dist/                 # `npm run build` の出力 (Git管理外)
└── data/                    # 実行時に自動生成される保存先 (Git管理外)
    ├── kairo.db               # SQLiteデータベース
    ├── settings.json           # ユーザー設定 (外部送信なし)
    └── projects/<project_id>/   # プロジェクトごとのデータ
        ├── scenes/               # シーンのキー画像と中間クリップ
        ├── audio/                # ナレーション・効果音
        ├── assets/               # 完成したシーンクリップ・BGM・取り込み素材・ユーザー素材
        ├── thumbnails/            # 素材一覧用のサムネイル (自動生成)
        ├── subtitles/            # 生成された .srt
        ├── renders/               # 書き出したMP4
        └── logs/                  # ジョブごとのログ
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
- AI (テキスト): LM Studio等のローカルLLM (OpenAI互換 `/v1/chat/completions`、状態取得は LM Studio の `/api/v0/models` も利用)
- 映像素材生成: Pillow によるプロシージャル合成 (追加ダウンロード不要) / 任意で diffusers
- 音声: Windows SAPI (System.Speech) によるナレーション、FFmpegによるBGM・効果音の合成
- AI (動画生成・実験的): PyTorch (CPU版) + diffusers + Stable Video Diffusion (`requirements-videogen.txt`、任意インストール)
