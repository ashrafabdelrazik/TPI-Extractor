#!/usr/bin/env python3
"""
TPI/TPD Extractor
==================
Pure-Python re-implementation of the CO2_CORE_DLL TPI/TPD reader
(see src/IO/NetDragonDatPkg/TPI.cs and TPD.cs in rev20.zip).

A ".tpi" file holds a header + a table of file entries.
A ".tpd" file (same base name) holds the actual data, each entry's
bytes being a raw zlib-compressed stream starting at Entry.Offset.

Usage:
    python tpi_extractor.py <path/to/archive.tpi> <output_folder>

    # or point at the .tpd, it will look for the matching .tpi
    python tpi_extractor.py <path/to/archive.tpd> <output_folder>

    # list entries without extracting
    python tpi_extractor.py <path/to/archive.tpi> --list
"""

import argparse
import os
import struct
import sys
import zlib

IDENTIFIER = b"NetDragonDatPkg"
MAX_IDENTIFIER_SIZE = 0x10
VERSION = 1000

# TPI header: 16s identifier, q version, i unk1, i unk2, i unk3, I number, I offset, i reserved
TPI_HEADER_FMT = "<16sqiiiIIi"
TPI_HEADER_SIZE = struct.calcsize(TPI_HEADER_FMT)

# TPD header: 16s identifier, q version, i unk1, i unk2
TPD_HEADER_FMT = "<16sqii"
TPD_HEADER_SIZE = struct.calcsize(TPD_HEADER_FMT)

ENCODING = "cp1252"  # Windows-1252


class TpiEntry:
    __slots__ = ("path", "unknown1", "uncompressed_size", "compressed_size", "offset")

    def __init__(self, path, unknown1, uncompressed_size, compressed_size, offset):
        self.path = path
        self.unknown1 = unknown1
        self.uncompressed_size = uncompressed_size
        self.compressed_size = compressed_size
        self.offset = offset

    def __repr__(self):
        return (f"TpiEntry(path={self.path!r}, uncompressed={self.uncompressed_size}, "
                f"compressed={self.compressed_size}, offset={self.offset})")


def _check_identifier(raw_identifier: bytes, label: str):
    # The C# code reads a fixed 16-byte buffer and does a C-string compare
    # (stops at the first NUL byte).
    ident = raw_identifier.split(b"\x00", 1)[0]
    if ident != IDENTIFIER:
        raise ValueError(f"Invalid {label} header: identifier {ident!r} != {IDENTIFIER!r}")


def read_tpd_header(tpd_path: str):
    with open(tpd_path, "rb") as f:
        raw = f.read(TPD_HEADER_SIZE)
        if len(raw) < TPD_HEADER_SIZE:
            raise ValueError(f"TPD file too small to contain a header: {tpd_path}")
        identifier, version, unk1, unk2 = struct.unpack(TPD_HEADER_FMT, raw)
    _check_identifier(identifier, "TPD")
    if version != VERSION:
        raise ValueError(f"Unsupported TPD version: {version}")
    return {"identifier": identifier, "version": version, "unknown1": unk1, "unknown2": unk2}


def read_tpi(tpi_path: str):
    """Parse a .tpi file and return (header_dict, list_of_TpiEntry)."""
    with open(tpi_path, "rb") as f:
        raw = f.read(TPI_HEADER_SIZE)
        if len(raw) < TPI_HEADER_SIZE:
            raise ValueError(f"TPI file too small to contain a header: {tpi_path}")

        identifier, version, unk1, unk2, unk3, number, offset, reserved = struct.unpack(
            TPI_HEADER_FMT, raw
        )
        _check_identifier(identifier, "TPI")
        if version != VERSION:
            raise ValueError(f"Unsupported TPI version: {version}")

        header = {
            "identifier": identifier,
            "version": version,
            "unknown1": unk1,
            "unknown2": unk2,
            "unknown3": unk3,
            "number": number,
            "offset": offset,
            "reserved": reserved,
        }

        entries = []
        for _ in range(number):
            path_len_b = f.read(1)
            if not path_len_b:
                break
            path_len = path_len_b[0]

            path_bytes = f.read(path_len)
            path = path_bytes.decode(ENCODING, errors="replace")

            unknown1 = struct.unpack("<h", f.read(2))[0]
            uncompressed_size = struct.unpack("<I", f.read(4))[0]
            compressed_size = struct.unpack("<I", f.read(4))[0]
            compressed_size2 = struct.unpack("<I", f.read(4))[0]
            uncompressed_size2 = struct.unpack("<I", f.read(4))[0]
            entry_offset = struct.unpack("<I", f.read(4))[0]

            # Mirrors the C# code: skip malformed entries whose duplicated
            # size fields don't match.
            if compressed_size2 != compressed_size:
                continue
            if uncompressed_size2 != uncompressed_size:
                continue

            entries.append(TpiEntry(path, unknown1, uncompressed_size, compressed_size, entry_offset))

    return header, entries


def _resolve_pair(input_path: str):
    """Given either a .tpi or .tpd path, return (tpi_path, tpd_path)."""
    lower = input_path.lower()
    if lower.endswith(".tpi"):
        tpi_path = input_path
        tpd_path = input_path[: -len(".tpi")] + ".tpd"
    elif lower.endswith(".tpd"):
        tpd_path = input_path
        tpi_path = input_path[: -len(".tpd")] + ".tpi"
    else:
        raise ValueError("Input file must end in .tpi or .tpd")

    if not os.path.exists(tpi_path):
        raise FileNotFoundError(f"Missing .tpi file: {tpi_path}")
    if not os.path.exists(tpd_path):
        raise FileNotFoundError(f"Missing .tpd file: {tpd_path}")

    return tpi_path, tpd_path


def extract_entry_data(tpd_path: str, entry: TpiEntry) -> bytes:
    """Read+decompress a single entry's bytes from the .tpd file."""
    with open(tpd_path, "rb") as f:
        f.seek(entry.offset)
        compressed = f.read(entry.compressed_size) if entry.compressed_size else f.read()
        data = zlib.decompress(compressed)
    if entry.uncompressed_size and len(data) != entry.uncompressed_size:
        # Not fatal -- just a heads up, some archives have slightly off sizes.
        print(
            f"  [warn] {entry.path}: decompressed {len(data)} bytes, "
            f"expected {entry.uncompressed_size}",
            file=sys.stderr,
        )
    return data


_INVALID_WIN_CHARS = '<>:"|?*'
_INVALID_WIN_CHARS_TABLE = {ord(c): "_" for c in _INVALID_WIN_CHARS}
# Control characters (0x00-0x1F) also aren't allowed in Windows path components
# and show up in corrupted/garbled TPI entries.
_INVALID_WIN_CHARS_TABLE.update({i: "_" for i in range(0x20)})


def _sanitize_path_component(component: str) -> str:
    """Replace characters that are illegal in Windows paths (and any stray
    control characters from corrupted entries) with underscores."""
    cleaned = component.translate(_INVALID_WIN_CHARS_TABLE)
    cleaned = cleaned.rstrip(" .")  # Windows also disallows trailing dot/space
    return cleaned if cleaned else "_"


def _safe_join(destination: str, rel_path: str) -> str:
    parts = [p for p in rel_path.split("/") if p not in ("", ".", "..")]
    parts = [_sanitize_path_component(p) for p in parts]
    if not parts:
        parts = ["_unnamed_entry_"]
    return os.path.join(destination, *parts)


def extract_all(tpi_path: str, tpd_path: str, destination: str):
    header, entries = read_tpi(tpi_path)
    print(f"Archive: {tpi_path}")
    print(f"  Identifier : {header['identifier'].split(chr(0).encode())[0].decode(ENCODING)}")
    print(f"  Version    : {header['version']}")
    print(f"  Entries    : {len(entries)} (header claims {header['number']})")
    print()

    os.makedirs(destination, exist_ok=True)

    ok = 0
    failed = 0
    skipped = 0
    for i, entry in enumerate(entries, 1):
        rel_path = entry.path.replace("\\", "/").lstrip("/")
        print(f"[{i}/{len(entries)}] {rel_path}", end="")

        try:
            out_path = _safe_join(destination, rel_path)
        except Exception as e:
            print(f"  SKIPPED (bad path {entry.path!r}): {e}")
            skipped += 1
            continue

        try:
            out_dir = os.path.dirname(out_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)

            data = extract_entry_data(tpd_path, entry)
            with open(out_path, "wb") as out_f:
                out_f.write(data)
            print(f"  ({len(data)} bytes)")
            ok += 1
        except (OSError, ValueError) as e:
            # Bad/garbled entry (corrupt path, invalid Windows path chars,
            # zlib error, etc.) -- log it and keep going instead of aborting
            # the whole extraction.
            print(f"  FAILED ({type(e).__name__}): {e}")
            failed += 1
        except Exception as e:
            print(f"  FAILED (unexpected {type(e).__name__}): {e}")
            failed += 1

    print()
    print(f"Done. {ok} extracted, {failed} failed, {skipped} skipped.")


def list_entries(tpi_path: str):
    header, entries = read_tpi(tpi_path)
    print(f"Archive: {tpi_path}")
    print(f"  Version : {header['version']}")
    print(f"  Entries : {len(entries)} (header claims {header['number']})")
    print()
    for i, e in enumerate(entries, 1):
        print(f"{i:5d}  offset=0x{e.offset:08X}  comp={e.compressed_size:>10}  "
              f"uncomp={e.uncompressed_size:>10}  {e.path}")


def main():
    parser = argparse.ArgumentParser(description="Extract NetDragon TPI/TPD archives (.tpi/.tpd pairs).")
    parser.add_argument("input", help="Path to the .tpi or .tpd file")
    parser.add_argument("output", nargs="?", help="Destination folder for extracted files")
    parser.add_argument("--list", action="store_true", help="Only list entries, don't extract")
    args = parser.parse_args()

    tpi_path, tpd_path = _resolve_pair(args.input)

    if args.list:
        list_entries(tpi_path)
        return

    if not args.output:
        parser.error("output folder is required unless --list is given")

    extract_all(tpi_path, tpd_path, args.output)


if __name__ == "__main__":
    main()