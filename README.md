# TPI/TPD Extractor

A small, dependency-free Python script for extracting NetDragon `.tpi`/`.tpd` data package archives (the format used by `CO2_CORE_DLL`, originally written in C# by CptSky).

Each archive is a pair of files:
- **`.tpi`** — header + a table of entries (file paths, sizes, offsets)
- **`.tpd`** — the raw data, where each entry's bytes are a zlib-compressed stream starting at its recorded offset

This script parses the `.tpi` table and pulls every entry's data out of the matching `.tpd` file, inflating it with Python's built-in `zlib`.

## Requirements

- Python 3.7+
- No third-party dependencies (uses only `struct`, `zlib`, `os`, `argparse` from the standard library)

## Usage

```bash
# Extract everything to a folder
python tpi_extractor.py path/to/archive.tpi output_folder/

# Also works if you point at the .tpd instead — it finds the matching .tpi
python tpi_extractor.py path/to/archive.tpd output_folder/

# Just list the entries in an archive without extracting
python tpi_extractor.py path/to/archive.tpi --list
```

The `.tpi` and `.tpd` files must sit next to each other with the same base name (e.g. `data.tpi` / `data.tpd`), same as the original tool.

### Example output

```
Archive: data.tpi
  Identifier : NetDragonDatPkg
  Version    : 1000
  Entries    : 63011 (header claims 63011)

[1/63011] data/map/puzzle/woods/dragon/dragon001.dds  (32896 bytes)
[2/63011] data/map/puzzle/woods/dragon/dragon002.dds  (32896 bytes)
...
Done. 63009 extracted, 2 failed, 0 skipped.
```

## Handling corrupted entries

Some archives contain a small number of garbled entries (invalid path bytes, mismatched size fields, etc.). The script is defensive about this:

- Path components with characters that are illegal on Windows (`< > : " | ? *` or control characters) are sanitized to `_` instead of crashing.
- Any entry that still fails to extract (bad zlib data, filesystem error, etc.) is logged and skipped — the rest of the archive keeps extracting.
- A final summary reports how many files were extracted, failed, or skipped.

## How the format works

- **TPI header** (little-endian): 16-byte identifier (`NetDragonDatPkg`), `int64` version, three `int32` unknown fields, `uint32` entry count, `uint32` offset, `int32` reserved.
- **TPD header**: same 16-byte identifier, `int64` version, two `int32` unknown fields.
- **Each TPI entry**: 1-byte path length, path string (Windows-1252), `int16` unknown, `uint32` uncompressed size, `uint32` compressed size (repeated twice), `uint32` uncompressed size (repeated twice), `uint32` offset into the `.tpd` file.
- File data at that offset in the `.tpd` is a raw zlib stream; inflating it yields the original file.

## Credits

Format originally reverse-engineered and implemented in C# by **CptSky** (2012) as part of `CO2_CORE_DLL`. This repository is an independent Python re-implementation of the TPI/TPD reading logic for extraction purposes only (no packing/writing support yet).

## License

Add a license of your choice here (e.g. MIT) before publishing.
