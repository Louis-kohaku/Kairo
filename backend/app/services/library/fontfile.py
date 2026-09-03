"""Reading what a font file actually says about itself.

A minimal sfnt (TrueType/OpenType) reader: the `name`, `OS/2`, `head`,
`hhea` and `cmap` tables, which between them answer the questions Font
Intelligence needs to ask - what is this family called, how heavy is it, is
it monospaced, and can it render Japanese.

Written by hand rather than adding fontTools as a dependency. fontTools is a
large install for what amounts to four table reads, and Kairo's rule is that
an optional capability must not enlarge the required environment. Everything
here is bounded and defensive: a corrupt or unsupported file returns
`None`/defaults rather than raising, because a font-scanning pass runs over
hundreds of files from the OS and one bad one must not stop it.

The one thing this module never does is guess. `supports_japanese` is
answered by looking up real codepoints in the font's own cmap, not by
matching "Gothic" in the filename.
"""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc"}

# Codepoints that decide "can this render Japanese captions?". Hiragana あ,
# katakana ア, and two common kanji - a font with all four can set ordinary
# Japanese text; a Latin-only font has none of them.
_JAPANESE_PROBES = (0x3042, 0x30A2, 0x65E5, 0x672C)
# Basic Latin probes, for the reverse question.
_LATIN_PROBES = (0x41, 0x61, 0x30)

# Name table IDs (OpenType spec).
_NAME_FAMILY = 1
_NAME_SUBFAMILY = 2
_NAME_FULL = 4
_NAME_TYPOGRAPHIC_FAMILY = 16
_NAME_TYPOGRAPHIC_SUBFAMILY = 17
_NAME_LICENSE = 13
_NAME_LICENSE_URL = 14
_NAME_DESIGNER = 9
_NAME_VENDOR_URL = 11


@dataclass
class FontInfo:
    family: str = ""
    subfamily: str = ""
    full_name: str = ""
    postscript_family: str = ""
    weight_class: int = 400
    width_class: int = 5
    is_italic: bool = False
    is_monospace: bool = False
    units_per_em: int = 1000
    cap_height: int = 0
    x_height: int = 0
    ascender: int = 0
    descender: int = 0
    supports_japanese: bool = False
    supports_latin: bool = True
    glyph_count: int = 0
    license_description: str = ""
    license_url: str = ""
    designer: str = ""
    vendor_url: str = ""
    is_variable: bool = False
    collection_index: int = 0
    # The 10 PANOSE classification bytes from OS/2. This is the font's own
    # statement about whether it is serif, sans, rounded, decorative or
    # handwritten - which is why Kairo reads it instead of matching
    # "Mincho" against the filename.
    panose: tuple = ()
    names: dict = field(default_factory=dict)


def _read_exact(handle, offset: int, size: int) -> bytes:
    handle.seek(offset)
    data = handle.read(size)
    if len(data) != size:
        raise ValueError("truncated font table")
    return data


def _decode_name(raw: bytes, platform_id: int, encoding_id: int) -> str:
    """Name records are UTF-16BE on Windows/Unicode platforms, else Latin-1."""
    if platform_id == 3 or platform_id == 0:
        try:
            return raw.decode("utf-16-be", errors="ignore").strip("\x00").strip()
        except Exception:
            return ""
    if platform_id == 1 and encoding_id == 0:
        return raw.decode("mac-roman", errors="ignore").strip()
    return raw.decode("latin-1", errors="ignore").strip()


def _parse_name_table(handle, offset: int, length: int) -> dict[int, str]:
    """nameID -> string, preferring English/Unicode records.

    A font carries the same name several times for different platforms and
    languages. Later records only overwrite earlier ones when they are a
    better match (Windows-Unicode-English beats a Mac-Roman record), so a
    Japanese-language family name does not clobber the ASCII one a renderer
    needs.
    """
    header = _read_exact(handle, offset, 6)
    _fmt, count, string_offset = struct.unpack(">HHH", header)
    records = _read_exact(handle, offset + 6, 12 * count)

    best: dict[int, tuple[int, str]] = {}
    for i in range(count):
        pid, eid, lid, nid, rec_len, rec_off = struct.unpack_from(">HHHHHH", records, i * 12)
        if rec_off + rec_len > length:
            continue
        try:
            raw = _read_exact(handle, offset + string_offset + rec_off, rec_len)
        except ValueError:
            continue
        text = _decode_name(raw, pid, eid)
        if not text:
            continue
        # Preference: Windows/Unicode English (1033) > any Windows > Mac English
        if pid == 3 and lid == 0x409:
            rank = 3
        elif pid == 3:
            rank = 2
        elif pid == 0:
            rank = 2
        elif pid == 1 and lid == 0:
            rank = 1
        else:
            rank = 0
        current = best.get(nid)
        if current is None or rank > current[0]:
            best[nid] = (rank, text)
    return {nid: value for nid, (_rank, value) in best.items()}


def _cmap_has(handle, offset: int, codepoints: tuple[int, ...]) -> tuple[bool, int]:
    """Whether the font maps these codepoints, and how many glyphs it has.

    Only the two subtable formats that matter in practice are decoded:
    format 4 (BMP, used by virtually every font) and format 12 (full
    Unicode). Anything else is reported as "not found" rather than guessed.
    """
    header = _read_exact(handle, offset, 4)
    _version, num_tables = struct.unpack(">HH", header)
    records = _read_exact(handle, offset + 4, 8 * num_tables)

    subtables: list[tuple[int, int, int]] = []
    for i in range(num_tables):
        pid, eid, sub_off = struct.unpack_from(">HHI", records, i * 8)
        subtables.append((pid, eid, offset + sub_off))
    # Prefer a full-Unicode subtable when the font has one.
    subtables.sort(key=lambda s: (s[0] == 3 and s[1] == 10, s[0] == 3 and s[1] == 1), reverse=True)

    found = set()
    mapped_glyphs = 0
    for _pid, _eid, sub_off in subtables:
        try:
            fmt = struct.unpack(">H", _read_exact(handle, sub_off, 2))[0]
        except ValueError:
            continue
        if fmt == 4:
            head = _read_exact(handle, sub_off, 14)
            seg_x2 = struct.unpack_from(">H", head, 6)[0]
            seg_count = seg_x2 // 2
            body = _read_exact(handle, sub_off + 14, seg_x2 * 4 + 2)
            ends = struct.unpack_from(f">{seg_count}H", body, 0)
            starts = struct.unpack_from(f">{seg_count}H", body, seg_x2 + 2)
            mapped_glyphs = max(mapped_glyphs, sum(e - s + 1 for s, e in zip(starts, ends) if e >= s and e != 0xFFFF))
            for cp in codepoints:
                if cp > 0xFFFF:
                    continue
                for s, e in zip(starts, ends):
                    if s <= cp <= e:
                        found.add(cp)
                        break
        elif fmt == 12:
            head = _read_exact(handle, sub_off, 16)
            n_groups = struct.unpack_from(">I", head, 12)[0]
            n_groups = min(n_groups, 20000)  # bounded read
            groups = _read_exact(handle, sub_off + 16, 12 * n_groups)
            total = 0
            for i in range(n_groups):
                start, end, _gid = struct.unpack_from(">III", groups, i * 12)
                total += end - start + 1
                for cp in codepoints:
                    if start <= cp <= end:
                        found.add(cp)
            mapped_glyphs = max(mapped_glyphs, total)
        if len(found) == len(codepoints):
            break
    return (len(found) > 0, mapped_glyphs)


def _table_directory(handle, offset: int) -> tuple[dict[str, tuple[int, int]], bool]:
    """Reads one sfnt table directory. Returns (tables, is_collection_entry)."""
    tag = _read_exact(handle, offset, 4)
    if tag == b"ttcf":
        raise ValueError("nested collection")
    header = _read_exact(handle, offset, 12)
    num_tables = struct.unpack_from(">H", header, 4)[0]
    raw = _read_exact(handle, offset + 12, 16 * num_tables)
    tables: dict[str, tuple[int, int]] = {}
    for i in range(num_tables):
        name, _checksum, off, length = struct.unpack_from(">4sIII", raw, i * 16)
        tables[name.decode("latin-1").strip()] = (off, length)
    return tables, False


def read(path: Path, *, collection_index: int = 0) -> FontInfo | None:
    """Reads one font file. Returns None if it cannot be understood."""
    try:
        with path.open("rb") as handle:
            magic = handle.read(4)
            base = 0
            if magic == b"ttcf":
                # A collection: read the requested face's directory offset.
                handle.seek(8)
                count = struct.unpack(">I", handle.read(4))[0]
                if count == 0:
                    return None
                index = min(collection_index, count - 1)
                handle.seek(12 + 4 * index)
                base = struct.unpack(">I", handle.read(4))[0]
            elif magic not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf"):
                return None

            tables, _ = _table_directory(handle, base)
            info = FontInfo(collection_index=collection_index)
            info.is_variable = "fvar" in tables

            if "name" in tables:
                off, length = tables["name"]
                try:
                    names = _parse_name_table(handle, off, length)
                except (ValueError, struct.error):
                    names = {}
                info.names = names
                info.family = names.get(_NAME_TYPOGRAPHIC_FAMILY) or names.get(_NAME_FAMILY, "")
                info.subfamily = (
                    names.get(_NAME_TYPOGRAPHIC_SUBFAMILY) or names.get(_NAME_SUBFAMILY, "")
                )
                info.full_name = names.get(_NAME_FULL, "")
                info.license_description = (names.get(_NAME_LICENSE, "") or "")[:2000]
                info.license_url = names.get(_NAME_LICENSE_URL, "")
                info.designer = names.get(_NAME_DESIGNER, "")
                info.vendor_url = names.get(_NAME_VENDOR_URL, "")

            if "head" in tables:
                off, _length = tables["head"]
                try:
                    head = _read_exact(handle, off, 54)
                    info.units_per_em = struct.unpack_from(">H", head, 18)[0] or 1000
                    mac_style = struct.unpack_from(">H", head, 44)[0]
                    info.is_italic = bool(mac_style & 0x2)
                except (ValueError, struct.error):
                    pass

            if "OS/2" in tables:
                off, length = tables["OS/2"]
                try:
                    size = min(length, 96)
                    os2 = _read_exact(handle, off, size)
                    version = struct.unpack_from(">H", os2, 0)[0]
                    info.weight_class = struct.unpack_from(">H", os2, 4)[0] or 400
                    info.width_class = struct.unpack_from(">H", os2, 6)[0] or 5
                    fs_selection = struct.unpack_from(">H", os2, 62)[0]
                    info.is_italic = info.is_italic or bool(fs_selection & 0x1)
                    if len(os2) >= 42:
                        info.panose = tuple(os2[32:42])
                    panose_proportion = os2[35] if len(os2) > 35 else 0
                    info.is_monospace = panose_proportion == 9
                    if version >= 2 and size >= 90:
                        info.x_height = struct.unpack_from(">h", os2, 86)[0]
                        info.cap_height = struct.unpack_from(">h", os2, 88)[0]
                except (ValueError, struct.error):
                    pass

            if "hhea" in tables:
                off, _length = tables["hhea"]
                try:
                    hhea = _read_exact(handle, off, 36)
                    info.ascender = struct.unpack_from(">h", hhea, 4)[0]
                    info.descender = struct.unpack_from(">h", hhea, 6)[0]
                except (ValueError, struct.error):
                    pass

            if "cmap" in tables:
                off, _length = tables["cmap"]
                try:
                    info.supports_japanese, glyphs = _cmap_has(handle, off, _JAPANESE_PROBES)
                    info.supports_latin, _ = _cmap_has(handle, off, _LATIN_PROBES)
                    info.glyph_count = glyphs
                except (ValueError, struct.error):
                    pass

            if not info.family:
                info.family = path.stem
            return info
    except (OSError, ValueError, struct.error):
        return None
    except Exception:
        logger.debug("Unexpected failure reading font %s", path, exc_info=True)
        return None


def face_count(path: Path) -> int:
    """Faces in a .ttc/.otc collection (1 for a plain font file)."""
    try:
        with path.open("rb") as handle:
            if handle.read(4) != b"ttcf":
                return 1
            handle.seek(8)
            return max(1, min(struct.unpack(">I", handle.read(4))[0], 64))
    except (OSError, struct.error):
        return 1
