"""Streaming/royalty metrics ingest.

Imports distributor royalty reports (LANDR detailed CSV, Amuse XLSX) from a
drop folder into a local SQLite database. Rows are deduplicated by a content
hash over the normalized values, so re-importing the same file — or an Amuse
date-range export that overlaps a previous one — inserts nothing twice.
"""
from __future__ import annotations

import csv
import hashlib
import os
import sqlite3
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

_EXCEL_EPOCH = date(1899, 12, 30)
_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

LANDR_COLUMNS = {"Payment Date", "Start of reporting period", "Store", "UPC", "ISRC"}
AMUSE_COLUMNS = {"Transaction Date", "Royalty Date", "Service", "UPC", "ISRC"}

_ROW_FIELDS = [
    "distributor", "payment_date", "period_start", "period_end", "store",
    "service", "country", "album", "upc", "track", "isrc", "artist",
    "quantity", "gross", "net", "share",
]


def default_db_path() -> Path:
    return Path(os.environ.get("MRP_METRICS_DB", str(Path.home() / ".mrp" / "metrics.db")))


def open_db(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS royalty_rows (
            id INTEGER PRIMARY KEY,
            row_hash TEXT NOT NULL UNIQUE,
            source_file TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            distributor TEXT NOT NULL,
            payment_date TEXT,
            period_start TEXT,
            period_end TEXT,
            store TEXT,
            service TEXT,
            country TEXT,
            album TEXT,
            upc TEXT,
            track TEXT,
            isrc TEXT,
            artist TEXT,
            quantity INTEGER NOT NULL DEFAULT 0,
            gross REAL,
            net REAL,
            share REAL
        );
        CREATE INDEX IF NOT EXISTS idx_royalty_artist ON royalty_rows (artist);
        CREATE INDEX IF NOT EXISTS idx_royalty_period ON royalty_rows (period_start);
        CREATE INDEX IF NOT EXISTS idx_royalty_isrc ON royalty_rows (isrc);
        CREATE TABLE IF NOT EXISTS import_log (
            id INTEGER PRIMARY KEY,
            imported_at TEXT NOT NULL,
            source_file TEXT NOT NULL,
            distributor TEXT NOT NULL,
            rows_seen INTEGER NOT NULL,
            rows_inserted INTEGER NOT NULL,
            rows_skipped INTEGER NOT NULL,
            rows_ignored INTEGER NOT NULL
        );
    """)
    return conn


def _excel_date(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return (_EXCEL_EPOCH + timedelta(days=int(float(raw)))).isoformat()
    except ValueError:
        return raw  # already a date string


def _num(value: Any) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _row_hash(row: dict[str, Any]) -> str:
    payload = "\x1f".join(str(row.get(field) if row.get(field) is not None else "") for field in _ROW_FIELDS)
    return hashlib.sha256(payload.encode()).hexdigest()


def read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    """Header-keyed rows from the first worksheet (stdlib-only xlsx reader)."""
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for si in ET.fromstring(archive.read("xl/sharedStrings.xml")):
                shared.append("".join(t.text or "" for t in si.iter(f"{_XLSX_NS}t")))
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    def cell_value(cell: ET.Element) -> str:
        if cell.get("t") == "inlineStr":
            return "".join(t.text or "" for t in cell.iter(f"{_XLSX_NS}t"))
        node = cell.find(f"{_XLSX_NS}v")
        value = node.text if node is not None and node.text else ""
        if cell.get("t") == "s" and value:
            return shared[int(value)]
        return value

    def column_index(ref: str | None) -> int | None:
        letters = "".join(ch for ch in str(ref or "") if ch.isalpha())
        if not letters:
            return None
        index = 0
        for ch in letters:
            index = index * 26 + (ord(ch.upper()) - 64)
        return index - 1

    rows: list[list[str]] = []
    for row in sheet.iter(f"{_XLSX_NS}row"):
        values: list[str] = []
        for cell in row.iter(f"{_XLSX_NS}c"):
            idx = column_index(cell.get("r"))
            if idx is None:
                idx = len(values)
            while len(values) <= idx:
                values.append("")
            values[idx] = cell_value(cell)
        rows.append(values)
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    return [
        {header[i]: (row[i] if i < len(row) else "") for i in range(len(header)) if header[i]}
        for row in rows[1:]
    ]


def _landr_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        raw_rows = list(csv.DictReader(handle))
    rows = []
    for raw in raw_rows:
        share = _num(raw.get("Share %"))
        rows.append({
            "distributor": "landr",
            "payment_date": (raw.get("Payment Date") or "").strip() or None,
            "period_start": (raw.get("Start of reporting period") or "").strip() or None,
            "period_end": (raw.get("End of reporting period") or "").strip() or None,
            "store": (raw.get("Store") or "").strip() or None,
            "service": (raw.get("Store service") or "").strip() or None,
            "country": (raw.get("Country of sale or stream") or "").strip() or None,
            "album": (raw.get("Album") or "").strip() or None,
            "upc": (raw.get("UPC") or "").strip() or None,
            "track": (raw.get("Track") or "").strip() or None,
            "isrc": (raw.get("ISRC") or "").strip() or None,
            "artist": (raw.get("Primary artist(s)") or "").strip() or None,
            "quantity": int(_num(raw.get("Quantity of sales or streams")) or 0),
            "gross": _num(raw.get("Gross earnings (USD)")),
            "net": _num(raw.get("Net earnings (USD)")),
            "share": share / 100 if share is not None else None,
        })
    return rows


def _amuse_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for raw in read_xlsx_rows(path):
        royalty_date = _excel_date(raw.get("Royalty Date"))
        rows.append({
            "distributor": "amuse",
            "payment_date": _excel_date(raw.get("Transaction Date")),
            "period_start": royalty_date,
            "period_end": royalty_date,
            "store": (raw.get("Service") or "").strip() or None,
            "service": (raw.get("Product") or "").strip() or None,
            "country": None,
            "album": (raw.get("Release") or "").strip() or None,
            "upc": (raw.get("UPC") or "").strip() or None,
            "track": (raw.get("Track") or "").strip() or None,
            "isrc": (raw.get("ISRC") or "").strip() or None,
            "artist": (raw.get("Artist") or "").strip() or None,
            "quantity": int(_num(raw.get("Quantity")) or 0),
            "gross": _num(raw.get("Amount")),
            "net": _num(raw.get("Total")),
            "share": _num(raw.get("Split")),
        })
    return rows


def sniff_distributor(path: Path) -> str | None:
    """Identify a report file by its header row, not its name."""
    try:
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as handle:
                header = set(next(csv.reader(handle), []))
            return "landr" if LANDR_COLUMNS <= header else None
        if path.suffix.lower() == ".xlsx":
            rows = read_xlsx_rows(path)
            header = set(rows[0].keys()) if rows else set()
            return "amuse" if AMUSE_COLUMNS <= header else None
    except Exception:
        return None
    return None


def import_file(conn: sqlite3.Connection, path: Path) -> dict[str, Any]:
    distributor = sniff_distributor(path)
    if distributor is None:
        raise ValueError(f"Unrecognized report format: {path.name}")
    rows = _landr_rows(path) if distributor == "landr" else _amuse_rows(path)
    imported_at = datetime.now(UTC).isoformat(timespec="seconds")

    inserted = skipped = ignored = 0
    for row in rows:
        if not row["upc"] and not row["isrc"]:
            ignored += 1  # bookkeeping rows (payouts, balance) — not stream data
            continue
        values = {**row, "row_hash": _row_hash(row), "source_file": path.name, "imported_at": imported_at}
        cursor = conn.execute(
            """INSERT OR IGNORE INTO royalty_rows
               (row_hash, source_file, imported_at, distributor, payment_date, period_start,
                period_end, store, service, country, album, upc, track, isrc, artist,
                quantity, gross, net, share)
               VALUES (:row_hash, :source_file, :imported_at, :distributor, :payment_date,
                :period_start, :period_end, :store, :service, :country, :album, :upc,
                :track, :isrc, :artist, :quantity, :gross, :net, :share)""",
            values,
        )
        if cursor.rowcount:
            inserted += 1
        else:
            skipped += 1

    conn.execute(
        "INSERT INTO import_log (imported_at, source_file, distributor, rows_seen, rows_inserted, rows_skipped, rows_ignored)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [imported_at, path.name, distributor, len(rows), inserted, skipped, ignored],
    )
    conn.commit()
    return {
        "file": path.name,
        "distributor": distributor,
        "rows_seen": len(rows),
        "inserted": inserted,
        "skipped": skipped,
        "ignored": ignored,
    }


def import_folder(conn: sqlite3.Connection, folder: Path) -> dict[str, Any]:
    if not folder.is_dir():
        raise ValueError(f"Not a folder: {folder}")
    files: list[dict[str, Any]] = []
    errors: list[str] = []
    unrecognized: list[str] = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in (".csv", ".xlsx") or not path.is_file():
            continue
        if sniff_distributor(path) is None:
            unrecognized.append(path.name)
            continue
        try:
            files.append(import_file(conn, path))
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    return {
        "folder": str(folder),
        "files": files,
        "unrecognized": unrecognized,
        "errors": errors,
        "inserted": sum(f["inserted"] for f in files),
        "skipped": sum(f["skipped"] for f in files),
    }


def streams_by_artist(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT artist, distributor, SUM(quantity) AS streams, SUM(COALESCE(net, 0)) AS net,
                  MIN(period_start) AS first_period, MAX(period_start) AS last_period
           FROM royalty_rows GROUP BY artist, distributor"""
    ).fetchall()
    by_artist: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = by_artist.setdefault(row["artist"] or "(unknown)", {
            "artist": row["artist"] or "(unknown)",
            "landr": 0, "amuse": 0, "total": 0, "net": 0.0,
            "first_period": row["first_period"], "last_period": row["last_period"],
        })
        entry[row["distributor"]] = row["streams"] or 0
        entry["total"] += row["streams"] or 0
        entry["net"] += row["net"] or 0.0
        entry["first_period"] = min(filter(None, [entry["first_period"], row["first_period"]]), default=None)
        entry["last_period"] = max(filter(None, [entry["last_period"], row["last_period"]]), default=None)
    return sorted(by_artist.values(), key=lambda e: e["total"], reverse=True)


def recent_imports(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM import_log ORDER BY id DESC LIMIT ?", [limit]
    ).fetchall()
    return [dict(row) for row in rows]
