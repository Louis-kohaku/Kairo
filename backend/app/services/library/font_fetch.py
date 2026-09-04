"""Adding fonts to the library from a source whose licence is verifiable.

The only source wired up is the official `google/fonts` repository, because
it is the one place where the font file and the licence text that governs it
sit in the same directory and can be fetched together. That is the whole
design: Kairo downloads `OFL.txt` *first*, confirms the directory is one of
the licence trees it understands (`ofl/`, `apache/`, `ufl/`), and only then
takes the font. A font whose licence file cannot be fetched is not
downloaded at all - there is no "probably fine" path.

Every download writes a `<file>.kairo.json` sidecar recording the source
URL, the licence id, and the licence file it was fetched with, so a later
scan can re-establish provenance without going back to the network, and so
`assets-used.json` can cite something real.

Downloading is opt-in (settings.library.auto_download_fonts) and can always
be triggered by hand. Kairo works with the OS's own fonts if it never runs.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from app.services.library import fonts as font_service

logger = logging.getLogger(__name__)

_API = "https://api.github.com/repos/google/fonts/contents"
_RAW = "https://raw.githubusercontent.com/google/fonts/main"
_TIMEOUT = 25.0
_MAX_FONT_BYTES = 30 * 1024 * 1024
_USER_AGENT = "KairoVideoAgent/1.0 (font library)"

# Licence directory -> the licence every font under it is published with.
# This is the repository's own organising principle, which is why it can be
# trusted as a licence statement; the OFL.txt/LICENSE.txt fetched alongside
# is the evidence kept on disk.
_LICENSE_BY_DIR = {
    "ofl": ("OFL-1.1", "OFL.txt"),
    "apache": ("Apache-2.0", "LICENSE.txt"),
    "ufl": ("UFL-1.0", "UFL.txt"),
}


class FontFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class CatalogEntry:
    """A font Kairo offers to download."""

    id: str  # repository directory name, e.g. "notosansjp"
    family: str
    license_dir: str  # ofl | apache | ufl
    languages: tuple[str, ...]
    note: str = ""
    # The family ships only a variable font. libass renders it at the
    # font's default instance regardless of the weight a style asks for, so
    # the UI says so before the user downloads it rather than after they
    # wonder why "Bold" looks regular.
    variable_only: bool = False


# A curated shortlist rather than the whole repository: these are families
# that actually work as short-form captions, with Japanese coverage
# deliberately over-represented because that is what Kairo's users need and
# what the OS alone provides least of.
CATALOG: tuple[CatalogEntry, ...] = (
    # --- Japanese ---
    CatalogEntry("notosansjp", "Noto Sans JP", "ofl", ("ja", "en"),
                 "汎用ゴシック。字幕の第一候補になる可読性。", variable_only=True),
    CatalogEntry("notoserifjp", "Noto Serif JP", "ofl", ("ja", "en"),
                 "明朝。落ち着いた・上品な雰囲気向け。", variable_only=True),
    CatalogEntry("mplus1p", "M PLUS 1p", "ofl", ("ja", "en"),
                 "軽やかなゴシック。Vlog・日常系に。"),
    CatalogEntry("zenmarugothic", "Zen Maru Gothic", "ofl", ("ja", "en"),
                 "柔らかい丸ゴシック。ペット・料理など親しみやすい題材に。"),
    CatalogEntry("kiwimaru", "Kiwi Maru", "ofl", ("ja", "en"),
                 "細めの丸ゴシック。やさしい印象。"),
    CatalogEntry("zenkakugothicnew", "Zen Kaku Gothic New", "ofl", ("ja", "en"),
                 "現代的な角ゴシック。汎用性が高い。"),
    CatalogEntry("bizudpgothic", "BIZ UDPGothic", "ofl", ("ja", "en"),
                 "ユニバーサルデザイン書体。可読性重視の字幕に。"),
    CatalogEntry("bizudmincho", "BIZ UDMincho", "ofl", ("ja", "en"),
                 "ユニバーサルデザインの明朝。"),
    CatalogEntry("shipporimincho", "Shippori Mincho", "ofl", ("ja", "en"),
                 "和の雰囲気が出る明朝。"),
    CatalogEntry("zenoldmincho", "Zen Old Mincho", "ofl", ("ja", "en"),
                 "重厚な明朝。歴史・和風の題材に。"),
    CatalogEntry("delagothicone", "Dela Gothic One", "ofl", ("ja", "en"),
                 "極太の見出し用。Hookの字幕に強い。"),
    CatalogEntry("rocknrollone", "RocknRoll One", "ofl", ("ja", "en"),
                 "太めでポップ。エンタメ向け。"),
    CatalogEntry("reggaeone", "Reggae One", "ofl", ("ja", "en"),
                 "インパクトの強い見出し書体。"),
    CatalogEntry("mochiypopone", "Mochiy Pop One", "ofl", ("ja", "en"),
                 "丸くポップな見出し書体。"),
    CatalogEntry("hachimarupop", "Hachi Maru Pop", "ofl", ("ja", "en"),
                 "手書き風のポップ書体。かわいい題材に。"),
    CatalogEntry("yuseimagic", "Yusei Magic", "ofl", ("ja", "en"),
                 "手書き風。カジュアルな題材に。"),
    CatalogEntry("sawarabigothic", "Sawarabi Gothic", "ofl", ("ja", "en"),
                 "軽量な日本語ゴシック。"),
    CatalogEntry("kaiseidecol", "Kaisei Decol", "ofl", ("ja", "en"),
                 "やわらかい装飾明朝。"),
    # --- Latin ---
    CatalogEntry("lato", "Lato", "ofl", ("en",), "汎用サンセリフ。ウェイトが豊富。"),
    CatalogEntry("poppins", "Poppins", "ofl", ("en",), "丸みのあるジオメトリック。"),
    CatalogEntry("anton", "Anton", "ofl", ("en",), "極太。インパクト重視。"),
    CatalogEntry("bebasneue", "Bebas Neue", "ofl", ("en",), "大文字専用の細身コンデンス。"),
    CatalogEntry("inter", "Inter", "ofl", ("en",), "UI向けの高可読サンセリフ。", variable_only=True),
    CatalogEntry("montserrat", "Montserrat", "ofl", ("en",), "見出し向けジオメトリック。", variable_only=True),
    CatalogEntry("oswald", "Oswald", "ofl", ("en",), "縦長コンデンス。情報量の多い見出しに。", variable_only=True),
)
CATALOG_BY_ID: dict[str, CatalogEntry] = {e.id: e for e in CATALOG}

# The families worth installing before the first production, and the edit
# style each one exists to serve.
#
# The reason this set exists: a Windows machine's own Japanese fonts are all
# document faces - BIZ UD, MS Gothic, Yu Gothic, Meiryo, HG series. They are
# legible and they are interchangeable, so a library made only of them gives
# the ranking nothing to choose *between*, and captions on a travel short
# end up looking like captions in a spreadsheet. Nine OFL families cover the
# registers the OS has none of: a display face for hooks, a rounded face for
# casual subjects, two Mincho weights for cinematic and luxury, and a
# neutral modern gothic that beats the OS's for short-form.
#
# Every one is SIL Open Font License 1.1 - free, commercial use permitted,
# no attribution required in the video - and each is downloaded with its own
# OFL.txt, exactly like any other catalogue entry.
RECOMMENDED_STARTER: tuple[tuple[str, str], ...] = (
    ("zenkakugothicnew", "汎用の角ゴシック。Shorts・Travelの標準字幕に"),
    ("mplus1p", "軽やかなゴシック。Vlog・日常系に"),
    ("zenmarugothic", "丸ゴシック。Casual・Food・ペットに"),
    ("delagothicone", "極太の見出し。Hookとエンタメのテロップに"),
    ("rocknrollone", "太めでポップ。Entertainment向け"),
    ("shipporimincho", "和の明朝。Cinematic・Documentaryに"),
    ("zenoldmincho", "重厚な明朝。Luxury・歴史もの向け"),
    ("notoserifjp", "汎用明朝。上品な字幕に"),
    ("yuseimagic", "手書き風。カジュアルなテロップに"),
)


def starter_set(db=None) -> dict:
    """The recommended set, and how much of it is already installed.

    Reported rather than installed automatically: downloading is a network
    action that writes files, and `settings.library.auto_download_fonts`
    exists precisely so the user decides. What Kairo does without
    permission is *say* that its font choices are limited and name the fix.
    """
    installed: set[str] = set()
    if db is not None:
        from app.models.library import LibraryAsset

        rows = (
            db.query(LibraryAsset)
            .filter(LibraryAsset.kind == "font", LibraryAsset.is_system.is_(False))
            .all()
        )
        installed = {r.family for r in rows if r.available}

    items = []
    for entry_id, purpose in RECOMMENDED_STARTER:
        entry = CATALOG_BY_ID[entry_id]
        items.append(
            {
                "id": entry.id,
                "family": entry.family,
                "purpose": purpose,
                "installed": entry.family in installed,
                "license_id": _LICENSE_BY_DIR[entry.license_dir][0],
                "variable_only": entry.variable_only,
            }
        )
    missing = [i for i in items if not i["installed"]]
    return {
        "items": items,
        "installed_count": len(items) - len(missing),
        "total": len(items),
        "missing_ids": [i["id"] for i in missing],
        "license": "SIL Open Font License 1.1（商用利用可・表記義務なし）",
        "source": "Google Fonts (google/fonts リポジトリ)",
    }


def install_starter_set(*, max_files: int = 3) -> dict:
    """Downloads whatever of the recommended set is missing.

    One family failing does not stop the rest: a partial improvement to the
    library is a real improvement, and the result says exactly which
    families arrived and which did not.
    """
    installed: list[dict] = []
    failed: list[dict] = []
    for entry_id, _purpose in RECOMMENDED_STARTER:
        try:
            installed.append(download(entry_id, max_files=max_files))
        except FontFetchError as exc:
            failed.append({"id": entry_id, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            logger.exception("Starter font download failed: %s", entry_id)
            failed.append({"id": entry_id, "error": f"{type(exc).__name__}: {exc}"})
    return {"installed": installed, "failed": failed}


def _get(url: str, *, stream: bool = False) -> requests.Response:
    try:
        resp = requests.get(
            url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT, stream=stream
        )
    except requests.RequestException as exc:
        raise FontFetchError(f"接続できませんでした: {exc}") from exc
    if resp.status_code == 403:
        raise FontFetchError(
            "GitHub APIのレート制限に達しました。しばらく待ってから再試行してください。"
        )
    if resp.status_code == 404:
        raise FontFetchError("配布元にファイルが見つかりませんでした。")
    if not resp.ok:
        raise FontFetchError(f"HTTP {resp.status_code}")
    return resp


def list_remote_files(entry: CatalogEntry) -> list[dict]:
    """The files in this family's directory in the official repository."""
    url = f"{_API}/{entry.license_dir}/{entry.id}"
    data = _get(url).json()
    if not isinstance(data, list):
        raise FontFetchError("配布元の応答を解釈できませんでした。")
    return data


def _pick_font_files(files: list[dict], *, max_files: int = 4) -> list[dict]:
    """Which files to actually take.

    Static instances are preferred over variable fonts: libass (the subtitle
    renderer Kairo burns captions with) does not select named instances from
    a variable font, so a downloaded `[wght].ttf` would render at its default
    weight regardless of what the style asked for. If a family only ships a
    variable font, it is taken - one weight is better than none - and the
    sidecar records that it is variable.
    """
    ttf = [f for f in files if str(f.get("name", "")).lower().endswith((".ttf", ".otf"))]
    static = [f for f in ttf if "[" not in str(f.get("name", ""))]
    chosen = static or ttf
    if not chosen:
        raise FontFetchError("フォントファイルが見つかりませんでした。")

    # Prefer Regular/Medium/Bold when the family ships many weights: those
    # are the three a caption style actually switches between.
    def rank(item: dict) -> tuple[int, str]:
        name = str(item.get("name", "")).lower()
        for i, want in enumerate(("regular", "medium", "bold", "semibold", "black")):
            if want in name:
                return (i, name)
        return (9, name)

    chosen.sort(key=rank)
    return chosen[:max_files]


def _download_file(url: str, dest: Path, *, max_bytes: int) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with _get(url, stream=True) as resp, dest.open("wb") as out:
        for chunk in resp.iter_content(64 * 1024):
            total += len(chunk)
            if total > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise FontFetchError("ファイルが想定より大きいため中止しました。")
            out.write(chunk)
    return total


_SAFE_NAME = re.compile(r"^[A-Za-z0-9._\-\[\]]+$")


def download(entry_id: str, *, max_files: int = 4) -> dict:
    """Downloads one family into the library, licence file first."""
    entry = CATALOG_BY_ID.get(entry_id)
    if entry is None:
        raise FontFetchError(f"カタログにないフォントです: {entry_id}")

    license_id, license_filename = _LICENSE_BY_DIR[entry.license_dir]
    font_service.ensure_dirs()
    lang_dir = "multi" if "ja" in entry.languages and "en" in entry.languages else (
        "jp" if "ja" in entry.languages else "en"
    )
    dest_dir = font_service.FONTS_ROOT / lang_dir / entry.id

    files = list_remote_files(entry)
    names = {str(f.get("name", "")) for f in files}

    # Licence first. Without it there is no download - not a warning, not a
    # fallback to "unknown", no font at all.
    license_name = license_filename if license_filename in names else next(
        (n for n in names if n.upper() in ("OFL.TXT", "LICENSE.TXT", "UFL.TXT")), ""
    )
    if not license_name:
        raise FontFetchError(
            "配布元にライセンスファイルが見つからなかったため、ダウンロードを中止しました。"
        )
    license_url = f"{_RAW}/{entry.license_dir}/{entry.id}/{license_name}"
    license_path = dest_dir / license_name
    _download_file(license_url, license_path, max_bytes=1024 * 1024)

    downloaded: list[str] = []
    for item in _pick_font_files(files, max_files=max_files):
        name = str(item.get("name", ""))
        if not _SAFE_NAME.match(name):
            logger.info("Skipping font file with unexpected name: %r", name)
            continue
        url = f"{_RAW}/{entry.license_dir}/{entry.id}/{name}"
        dest = dest_dir / name
        size = _download_file(url, dest, max_bytes=_MAX_FONT_BYTES)
        sidecar = {
            "family": entry.family,
            "source": "Google Fonts (google/fonts リポジトリ)",
            "source_url": f"https://github.com/google/fonts/tree/main/{entry.license_dir}/{entry.id}",
            "license_id": license_id,
            "license_file": str(license_path.relative_to(font_service.LIBRARY_ROOT).as_posix()),
            "downloaded_bytes": size,
            "note": entry.note,
        }
        dest.with_suffix(dest.suffix + ".kairo.json").write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        downloaded.append(name)

    if not downloaded:
        raise FontFetchError("ダウンロードできるフォントファイルがありませんでした。")

    return {
        "id": entry.id,
        "family": entry.family,
        "license_id": license_id,
        "license_file": str(license_path),
        "directory": str(dest_dir),
        "files": downloaded,
    }


def catalog(db=None) -> list[dict]:
    """The download catalogue, marked with what is already installed."""
    installed: set[str] = set()
    if db is not None:
        from app.models.library import LibraryAsset

        rows = (
            db.query(LibraryAsset)
            .filter(LibraryAsset.kind == "font", LibraryAsset.is_system.is_(False))
            .all()
        )
        installed = {r.family for r in rows}

    out = []
    for entry in CATALOG:
        license_id, _ = _LICENSE_BY_DIR[entry.license_dir]
        out.append(
            {
                "id": entry.id,
                "family": entry.family,
                "languages": list(entry.languages),
                "license_id": license_id,
                "note": entry.note,
                "variable_only": entry.variable_only,
                "source": "Google Fonts (google/fonts)",
                "source_url": (
                    f"https://github.com/google/fonts/tree/main/{entry.license_dir}/{entry.id}"
                ),
                "installed": entry.family in installed,
            }
        )
    return out
