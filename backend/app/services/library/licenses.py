"""The Asset License Manager (design rule 13).

Every asset Kairo can reach carries one of these licence records, and the
`status` on it decides whether an automatic production may use the asset at
all. The point of the module is to make "無料っぽいから使う" impossible as a
code path: there is no branch anywhere that consults a price, a "free" label
or a filename. There is only `status`.

The six statuses map onto the six outcomes the design asks for:

===================== ======================================================
usable                使用可能 - no conditions Kairo must act on
attribution_required  帰属表示必要 - usable, and the credit is recorded in the
                      production's assets-used report automatically
conditional           条件付き - usable in a specific, stated situation only
                      (an OS-bundled font: fine to render with on this
                      machine, not fine to redistribute)
non_commercial        商用利用不可
not_usable            利用不可
unknown               ライセンス不明 - never auto-selected
===================== ======================================================

A licence that is not in `LICENSES` resolves to `unknown`, which is the safe
direction: an unrecognised licence blocks automatic use rather than being
optimistically waved through.
"""
from __future__ import annotations

from dataclasses import dataclass

USABLE = "usable"
ATTRIBUTION_REQUIRED = "attribution_required"
CONDITIONAL = "conditional"
NON_COMMERCIAL = "non_commercial"
NOT_USABLE = "not_usable"
UNKNOWN = "unknown"

STATUS_LABELS: dict[str, str] = {
    USABLE: "使用可能",
    ATTRIBUTION_REQUIRED: "帰属表示必要",
    CONDITIONAL: "条件付き",
    NON_COMMERCIAL: "商用利用不可",
    NOT_USABLE: "利用不可",
    UNKNOWN: "ライセンス不明",
}

# Statuses an automatic production may draw from. `conditional` is included
# because its one condition (OS-bundled fonts stay on this machine) is
# satisfied by what Kairo does with them - it renders locally and never
# redistributes the file - and excluding it would leave a Japanese Windows
# install with no Japanese font to render captions with.
AUTO_USABLE_STATUSES: frozenset[str] = frozenset(
    {USABLE, ATTRIBUTION_REQUIRED, CONDITIONAL}
)


@dataclass(frozen=True)
class License:
    id: str
    name: str
    url: str
    status: str
    commercial_use: bool
    attribution_required: bool
    redistribution: bool
    # What the user needs to know, in one sentence, in Japanese.
    summary: str


LICENSES: dict[str, License] = {
    "OFL-1.1": License(
        "OFL-1.1",
        "SIL Open Font License 1.1",
        "https://openfontlicense.org/",
        USABLE,
        commercial_use=True,
        attribution_required=False,
        redistribution=True,
        summary="商用利用・埋め込み・再配布が可能なオープンフォントライセンス。フォント単体の販売のみ不可。",
    ),
    "Apache-2.0": License(
        "Apache-2.0",
        "Apache License 2.0",
        "https://www.apache.org/licenses/LICENSE-2.0",
        USABLE,
        commercial_use=True,
        attribution_required=False,
        redistribution=True,
        summary="商用利用・改変・再配布が可能。著作権表示の保持が必要。",
    ),
    "CC0-1.0": License(
        "CC0-1.0",
        "Creative Commons Zero 1.0",
        "https://creativecommons.org/publicdomain/zero/1.0/",
        USABLE,
        commercial_use=True,
        attribution_required=False,
        redistribution=True,
        summary="権利放棄。クレジット不要で商用利用できます。",
    ),
    "CC-BY-4.0": License(
        "CC-BY-4.0",
        "Creative Commons Attribution 4.0",
        "https://creativecommons.org/licenses/by/4.0/",
        ATTRIBUTION_REQUIRED,
        commercial_use=True,
        attribution_required=True,
        redistribution=True,
        summary="商用利用可。作者クレジットの表示が必須です。",
    ),
    "CC-BY-SA-4.0": License(
        "CC-BY-SA-4.0",
        "Creative Commons Attribution-ShareAlike 4.0",
        "https://creativecommons.org/licenses/by-sa/4.0/",
        ATTRIBUTION_REQUIRED,
        commercial_use=True,
        attribution_required=True,
        redistribution=True,
        summary="商用利用可。クレジット表示と、同一ライセンスでの公開が必要です。",
    ),
    "CC-BY-NC-4.0": License(
        "CC-BY-NC-4.0",
        "Creative Commons Attribution-NonCommercial 4.0",
        "https://creativecommons.org/licenses/by-nc/4.0/",
        NON_COMMERCIAL,
        commercial_use=False,
        attribution_required=True,
        redistribution=True,
        summary="非商用に限り利用可。商用作品には使用できません。",
    ),
    "IPA-1.0": License(
        "IPA-1.0",
        "IPAフォントライセンス v1.0",
        "https://moji.or.jp/ipafont/license/",
        USABLE,
        commercial_use=True,
        attribution_required=False,
        redistribution=True,
        summary="商用利用可。改変・再配布には条件があります（フォント自体の販売は不可）。",
    ),
    "system-bundled": License(
        "system-bundled",
        "OS同梱フォント（この端末での利用）",
        "",
        CONDITIONAL,
        commercial_use=True,
        attribution_required=False,
        redistribution=False,
        summary=(
            "OSに同梱されているフォントです。この端末での描画には使えますが、"
            "フォントファイル自体の再配布はできません。商用可否はOS/フォントの"
            "使用許諾に従います。"
        ),
    ),
    "kairo-generated": License(
        "kairo-generated",
        "Kairo生成（第三者の権利なし）",
        "",
        USABLE,
        commercial_use=True,
        attribution_required=False,
        redistribution=True,
        summary="KairoがFFmpegで合成した音です。第三者の権利が含まれないため自由に使えます。",
    ),
    "user-owned": License(
        "user-owned",
        "ユーザー所有素材",
        "",
        USABLE,
        commercial_use=True,
        attribution_required=False,
        redistribution=True,
        summary="ユーザー自身の素材として登録されています。権利の確認はユーザーの責任です。",
    ),
    "proprietary": License(
        "proprietary",
        "独自ライセンス（要確認）",
        "",
        NOT_USABLE,
        commercial_use=False,
        attribution_required=False,
        redistribution=False,
        summary="個別の許諾が必要な素材です。自動制作では使用しません。",
    ),
    UNKNOWN: License(
        UNKNOWN,
        "ライセンス不明",
        "",
        UNKNOWN,
        commercial_use=False,
        attribution_required=False,
        redistribution=False,
        summary=(
            "ライセンスが確認できていません。Kairoは自動制作でこの素材を使いません。"
            "権利を確認したうえでライセンスを設定すると使えるようになります。"
        ),
    ),
}


def get(license_id: str) -> License:
    """The licence record, or the `unknown` record.

    Deliberately total: callers get a usable object for any input, and an
    unrecognised id resolves to the status that blocks automatic use.
    """
    return LICENSES.get((license_id or "").strip(), LICENSES[UNKNOWN])


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, STATUS_LABELS[UNKNOWN])


def is_auto_usable(status: str, *, require_commercial: bool = False, license_id: str = "") -> bool:
    """Whether an automatic production may select an asset with this status.

    `require_commercial` corresponds to settings.library.prefer_commercial_safe:
    with it set, a licence Kairo cannot confirm allows commercial use is
    excluded even when its status would otherwise permit selection.
    """
    if status not in AUTO_USABLE_STATUSES:
        return False
    if require_commercial and license_id:
        return get(license_id).commercial_use
    return True


def describe(license_id: str) -> dict:
    lic = get(license_id)
    return {
        "id": lic.id,
        "name": lic.name,
        "url": lic.url,
        "status": lic.status,
        "status_label": status_label(lic.status),
        "commercial_use": lic.commercial_use,
        "attribution_required": lic.attribution_required,
        "redistribution": lic.redistribution,
        "summary": lic.summary,
    }


def catalog() -> list[dict]:
    """Every licence Kairo understands, for the settings/library UI."""
    return [describe(lid) for lid in LICENSES]
