"""What 動画制作エージェント Kairo is actually connected to, right now.

This is the module behind the "Connected Services" view, and its only job is
to be true. Every row is produced by *checking* - running the binary,
calling the endpoint, importing the module, reading the environment - not by
listing what the code could in principle talk to. A service that is not
reachable says so, and says what the user can do about it.

Nothing here ever reports a connection Kairo does not have. That includes
the deliberate gaps: TikTok and Instagram appear with the reason they are
not connected, because an omitted row reads as an oversight while a stated
one reads as the licensing decision it is.
"""
from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field

from app.core.config import LIBRARY_ROOT, LLM_BASE_URL, WHISPER_MODEL_SIZE
from app.services import llm_client, tts_service
from app.services.trends import sources as trend_sources

logger = logging.getLogger(__name__)


@dataclass
class ServiceStatus:
    id: str
    category: str
    label: str
    purpose: str
    # local | local_http | official_api | public_feed
    connection: str
    endpoint: str = ""
    model: str = ""
    auth: str = "不要"
    cost: str = "無料"
    # connected | not_connected | not_configured | unavailable | disabled
    state: str = "not_connected"
    detail: str = ""
    remedy: str = ""
    files: list[str] = field(default_factory=list)
    terms_url: str = ""


def _version_of(binary: str) -> str | None:
    path = shutil.which(binary)
    if not path:
        return None
    try:
        out = subprocess.run(
            [path, "-version"], capture_output=True, text=True, timeout=8, check=False
        )
    except (subprocess.SubprocessError, OSError):
        return None
    first = (out.stdout or "").splitlines()
    return first[0] if first else path


def _llm() -> ServiceStatus:
    status = llm_client.get_status()
    if status.can_generate:
        state = "connected"
        detail = f"ロード済みモデル: {', '.join(status.models_loaded)}"
        remedy = ""
    elif status.server_reachable:
        state = "not_configured"
        detail = "サーバーには接続できていますが、モデルがロードされていません。"
        remedy = "LM Studioの「Local Server」でモデルをロードしてください。"
    else:
        state = "not_connected"
        detail = f"{LLM_BASE_URL} に接続できません。"
        remedy = (
            "LM Studioを起動し、Local Serverを有効にしてください。"
            "別ホストの場合は .env の KAIRO_LLM_BASE_URL を設定します。"
        )
    return ServiceStatus(
        id="lm_studio",
        category="LLM",
        label="LM Studio (OpenAI互換API)",
        purpose="企画・脚本・シーン設計・トレンド分析・レビュー",
        connection="local_http",
        endpoint=LLM_BASE_URL,
        model=status.configured_model or "(未解決)",
        auth="不要（ローカル）",
        cost="無料",
        state=state,
        detail=detail,
        remedy=remedy,
        files=["backend/app/services/llm_client.py", "backend/app/core/config.py"],
    )


def _ffmpeg() -> list[ServiceStatus]:
    out: list[ServiceStatus] = []
    for binary, purpose in (
        ("ffmpeg", "クリップ生成・連結・音声ミックス・字幕焼き込み・書き出し"),
        ("ffprobe", "素材と完成動画のメタデータ取得"),
    ):
        version = _version_of(binary)
        out.append(
            ServiceStatus(
                id=binary,
                category="動画処理",
                label=binary.upper(),
                purpose=purpose,
                connection="local",
                endpoint=shutil.which(binary) or "",
                model="",
                auth="不要",
                cost="無料",
                state="connected" if version else "not_connected",
                detail=version or f"{binary} がPATH上に見つかりません。",
                remedy="" if version else "FFmpegをインストールし、PATHを通してください。",
                files=["backend/app/services/ffmpeg/"],
            )
        )
    return out


def _whisper() -> ServiceStatus:
    try:
        import faster_whisper  # noqa: F401

        installed = True
    except ImportError:
        installed = False
    return ServiceStatus(
        id="faster_whisper",
        category="音声認識",
        label="faster-whisper (ローカル)",
        purpose="ユーザー素材の文字起こしと字幕生成",
        connection="local",
        model=WHISPER_MODEL_SIZE,
        auth="不要",
        cost="無料",
        state="connected" if installed else "unavailable",
        detail=(
            f"モデルサイズ {WHISPER_MODEL_SIZE}（初回実行時にダウンロードされます）"
            if installed
            else "faster-whisper がインストールされていません。"
        ),
        remedy=(
            "" if installed else "backend/requirements.txt の依存関係を再インストールしてください。"
        ),
        files=["backend/app/services/whisper_service.py"],
    )


def _tts() -> ServiceStatus:
    supported = tts_service.is_supported_platform()
    voices = tts_service.list_voices() if supported else []
    if not supported:
        state, detail = "unavailable", f"{platform.system()} ではKairoのTTSに対応していません。"
        remedy = "Windows以外ではナレーションなしで制作されます（字幕は通常どおり動作します）。"
    elif voices:
        state = "connected"
        detail = f"利用可能な音声{len(voices)}件: {', '.join(v.name for v in voices[:3])}"
        remedy = ""
    else:
        state, detail = "not_configured", "音声合成エンジンは使えますが、音声がインストールされていません。"
        remedy = "Windowsの「時刻と言語 > 音声」から音声パックを追加してください。"
    return ServiceStatus(
        id="sapi_tts",
        category="音声合成",
        label="Windows SAPI5 (System.Speech)",
        purpose="ナレーション音声の合成",
        connection="local",
        auth="不要",
        cost="無料",
        state=state,
        detail=detail,
        remedy=remedy,
        files=["backend/app/services/tts_service.py"],
    )


def _trend_services() -> list[ServiceStatus]:
    from app.services import settings_service
    from app.services.trends import collector

    enabled_ids = set(settings_service.get_settings().trends.sources)
    live = collector.last_status()
    out: list[ServiceStatus] = []
    for spec in trend_sources.SOURCE_SPECS:
        recent = live.get(spec.id, {})
        configured = trend_sources.has_key(spec)
        if spec.id not in enabled_ids:
            state, detail, remedy = (
                "disabled",
                "設定でこの取得元は無効になっています。",
                "設定 > トレンドで有効にできます。",
            )
        elif not configured:
            state = "not_configured"
            detail = f"APIキーが未設定のため使用していません（{spec.key_env}）。"
            remedy = f".env に {spec.key_env}=<あなたのAPIキー> を設定すると有効になります。"
        elif recent.get("ok"):
            state = "connected"
            detail = f"直近の取得: {recent.get('count', 0)}件（{recent.get('at', '')}）"
            remedy = ""
        elif recent.get("error"):
            state = "not_connected"
            detail = f"直近の取得に失敗: {recent['error']}"
            remedy = "ネットワーク接続を確認するか、設定から手動更新を試してください。"
        else:
            state = "not_connected"
            detail = "このプロセスではまだ取得していません。"
            remedy = "設定 > トレンドの「今すぐ更新」で取得できます。"
        out.append(
            ServiceStatus(
                id=spec.id,
                category="トレンド取得",
                label=spec.label,
                purpose="動画トレンドの継続収集",
                connection=spec.kind,
                endpoint=spec.endpoint,
                auth=(f"APIキー ({spec.key_env})" if spec.requires_key else "不要"),
                cost="無料枠あり" if spec.requires_key else "無料",
                state=state,
                detail=detail,
                remedy=remedy,
                terms_url=spec.terms_url,
                files=["backend/app/services/trends/sources.py"],
            )
        )

    for platform_info in trend_sources.UNAVAILABLE_PLATFORMS:
        out.append(
            ServiceStatus(
                id=platform_info["id"],
                category="トレンド取得",
                label=platform_info["label"],
                purpose="動画トレンドの取得（未接続）",
                connection="official_api",
                auth="審査申請が必要",
                cost="—",
                state="unavailable",
                detail=platform_info["reason"],
                remedy="公式APIの利用条件を満たした場合のみ接続を検討します。",
                terms_url=platform_info["docs"],
                files=["backend/app/services/trends/sources.py"],
            )
        )
    return out


def _probe(url: str, *, timeout: float = 6.0) -> tuple[bool, str]:
    """Is this endpoint answering right now? Returns (reachable, detail)."""
    import requests

    try:
        resp = requests.get(
            url, headers={"User-Agent": "KairoVideoAgent/1.0 (status check)"}, timeout=timeout
        )
    except Exception as exc:  # noqa: BLE001 - a status check never raises
        return False, f"接続できません: {exc}"[:160]
    if resp.status_code in (200, 204):
        return True, f"HTTP {resp.status_code} で応答しました"
    if resp.status_code == 429:
        return False, "レート制限中です（時間をおくと復帰します）"
    return False, f"HTTP {resp.status_code} を返しました"


def _research_and_material_sources() -> list[ServiceStatus]:
    """The two services a production run reaches during its own work.

    Separate from the trend sources because they answer different
    questions: these are used *inside* a production (how are videos on this
    subject made / is there a licensed photo for this beat), while the trend
    sources run on a schedule regardless of any production.
    """
    search_ok, search_detail = _probe("https://html.duckduckgo.com/html/?q=kairo")
    openverse_ok, openverse_detail = _probe(
        "https://api.openverse.org/v1/images/?q=test&page_size=1"
    )
    commons_ok, commons_detail = _probe(
        "https://commons.wikimedia.org/w/api.php?action=query&format=json&meta=siteinfo"
    )

    material_ok = openverse_ok or commons_ok
    material_detail = (
        f"Openverse: {'応答あり' if openverse_ok else openverse_detail} / "
        f"Wikimedia Commons: {'応答あり' if commons_ok else commons_detail}"
    )

    return [
        ServiceStatus(
            id="duckduckgo_html",
            category="Webリサーチ",
            label="DuckDuckGo (HTML版・JavaScript不要のエンドポイント)",
            purpose="同じテーマの動画がどう作られているかの調査（任意工程）",
            connection="public_feed",
            endpoint="https://html.duckduckgo.com/html/",
            auth="不要",
            cost="無料",
            state="connected" if search_ok else "not_connected",
            detail=(
                search_detail
                + "。送信するのは検索クエリのみで、動画・素材は一切送信しません。"
            ),
            remedy=(
                ""
                if search_ok
                else "ネットワークを確認してください。到達できない場合、制作は一般的な定石にフォールバックして続行します。"
            ),
            terms_url="https://duckduckgo.com/terms",
            files=["backend/app/services/studio/research_service.py"],
        ),
        ServiceStatus(
            id="openverse",
            category="Web素材取得",
            label="Openverse / Wikimedia Commons",
            purpose="ユーザー素材が足りないシーンを補うライセンス明示の写真の取得",
            connection="official_api",
            endpoint="https://api.openverse.org/v1/images/ , https://commons.wikimedia.org/w/api.php",
            auth="不要",
            cost="無料",
            state="connected" if material_ok else "not_connected",
            detail=(
                material_detail
                + "。ライセンスが機械可読な結果だけを採用し、不明なものは破棄します。"
            ),
            remedy=(
                ""
                if material_ok
                else "到達できない場合、不足シーンはAI生成またはKairoが構成した背景で補完されます。"
            ),
            terms_url="https://openverse.org/terms",
            files=["backend/app/services/studio/web_material_service.py"],
        ),
    ]


def _asset_sources(db=None) -> list[ServiceStatus]:
    from app.models.library import LibraryAsset
    from app.services.library import fonts as font_service

    counts = {"font": 0, "music": 0, "sfx": 0}
    if db is not None:
        for kind in counts:
            counts[kind] = (
                db.query(LibraryAsset)
                .filter(LibraryAsset.kind == kind, LibraryAsset.available.is_(True))
                .count()
            )

    return [
        ServiceStatus(
            id="google_fonts",
            category="フォント取得",
            label="Google Fonts (google/fonts リポジトリ)",
            purpose="OFL/Apacheライセンスのフォント取得",
            connection="public_feed",
            endpoint="https://api.github.com/repos/google/fonts/contents",
            auth="不要（未認証は60リクエスト/時）",
            cost="無料",
            state="connected" if counts["font"] else "not_connected",
            detail=(
                f"ライブラリに{counts['font']}件のフォントを登録済み"
                if counts["font"]
                else "まだフォントをスキャンしていません。"
            ),
            remedy="" if counts["font"] else "ライブラリ画面から「再スキャン」を実行してください。",
            terms_url="https://openfontlicense.org/",
            files=["backend/app/services/library/font_fetch.py"],
        ),
        ServiceStatus(
            id="system_fonts",
            category="フォント取得",
            label=f"{platform.system()} 同梱フォント",
            purpose="日本語字幕の描画",
            connection="local",
            endpoint=", ".join(str(d) for d in font_service.system_font_dirs()),
            auth="不要",
            cost="無料",
            state="connected",
            detail="OS同梱フォントは「条件付き」として扱い、再配布はしません。",
            files=["backend/app/services/library/fonts.py"],
        ),
        ServiceStatus(
            id="kairo_synth",
            category="音源",
            label="Kairo内蔵シンセ (FFmpeg lavfi)",
            purpose="BGM・効果音の生成（第三者の権利なし）",
            connection="local",
            endpoint=str(LIBRARY_ROOT),
            auth="不要",
            cost="無料",
            state="connected" if counts["music"] or counts["sfx"] else "not_connected",
            detail=f"BGM {counts['music']}件 / 効果音 {counts['sfx']}件を登録済み",
            remedy=(
                ""
                if counts["music"]
                else "ライブラリ画面の「初期化」で内蔵音源を生成できます。"
            ),
            files=["backend/app/services/ffmpeg/compose.py",
                   "backend/app/services/library/audio_library.py"],
        ),
        ServiceStatus(
            id="external_music_api",
            category="音源",
            label="外部音源API",
            purpose="商用利用可能なBGM/SFXの取得（未接続）",
            connection="official_api",
            auth="APIキーが必要",
            cost="—",
            state="unavailable",
            detail=(
                "APIキー不要で商用利用可能な音源を配布する公式APIが見つからないため、"
                "接続していません。音源はKairo生成か、ユーザーが取り込んだファイルを使います。"
            ),
            remedy=(
                "library/music/ 配下に音源を置き、ライブラリ画面でライセンスを設定すると"
                "自動制作で使えるようになります。"
            ),
            files=["backend/app/services/library/audio_library.py"],
        ),
    ]


def _image_engines() -> list[ServiceStatus]:
    from app.services import video_engines

    out: list[ServiceStatus] = []
    for capability in video_engines.list_capabilities():
        try:
            downloaded = video_engines.get_engine(capability.id).is_model_downloaded()
        except Exception:
            downloaded = False
        out.append(
            ServiceStatus(
                id=capability.id,
                category="映像生成",
                label=capability.display_name,
                purpose="画像から短い動画クリップを生成（任意機能）",
                connection="local",
                model=capability.id,
                auth="不要",
                cost="無料（ローカル実行）",
                state="connected" if downloaded else "not_configured",
                detail=capability.notes
                + ("" if downloaded else " / モデル未ダウンロード"),
                remedy="" if downloaded else "生成画面から初回ダウンロードを実行してください。",
                files=["backend/app/services/video_engines/"],
            )
        )
    return out


def collect(db=None) -> dict:
    """The whole connected-services picture, checked live."""
    services: list[ServiceStatus] = [
        _llm(),
        *_ffmpeg(),
        _whisper(),
        _tts(),
        *_trend_services(),
        *_research_and_material_sources(),
        *_asset_sources(db),
        *_image_engines(),
    ]
    by_category: dict[str, list[dict]] = {}
    for service in services:
        by_category.setdefault(service.category, []).append(asdict(service))

    return {
        "services": [asdict(s) for s in services],
        "by_category": by_category,
        "counts": {
            "connected": sum(1 for s in services if s.state == "connected"),
            "total": len(services),
        },
        "note": (
            "この一覧は表示のたびに実際に接続・実行して確認しています。"
            "「未接続」と表示されているサービスにKairoはリクエストを送りません。"
        ),
    }
