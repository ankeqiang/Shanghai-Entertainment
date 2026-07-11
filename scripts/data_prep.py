"""
Build a clean SQLite database from the raw FileMaker exports of the
Shanghai Entertainment (Leisure_ALL) database.

The raw exports are quirky:
  * Records are separated by a carriage return (\\r), old-Mac style, not \\n.
    Python's csv reader handles this transparently when the file is opened
    with newline=''.
  * Line breaks *inside* a cell are encoded as a vertical tab (0x0B); we
    convert those to real newlines.
  * There are no header rows. Column order follows the FileMaker export
    layout, so the mapping below was derived by inspecting the data against
    the DDR (Leisure_ALL_fmp12.xml).
  * Performers.csv and Performers_List.csv are byte-for-byte identical, so
    we only read one.

Table model (three linked tables):

    shows ──show_id──< performed_items ──item_id──< performers

Run:
    python scripts/data_prep.py
"""

from __future__ import annotations

import csv
import os
import re
import sqlite3
import sys

# Allow very large fields (some cells hold long concatenated text).
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw")
# DB_PATH can be overridden with the SE_DB_PATH env var. This is useful when
# the repo lives on a cloud-synced filesystem (Dropbox, iCloud, etc.), where
# SQLite can raise "disk I/O error" mid-write; build to local disk, then copy.
DB_PATH = os.environ.get(
    "SE_DB_PATH", os.path.join(ROOT, "data", "shanghai_entertainment.db")
)

VT = "\x0b"  # vertical tab used as an in-cell line break


def clean(value: str) -> str:
    """Normalize a single cell value."""
    if value is None:
        return ""
    return value.replace(VT, "\n").strip()


def parse_date(raw: str):
    """Convert FileMaker 'YYYY=MM=DD' to ISO 'YYYY-MM-DD' plus a year int.

    Returns (iso_date_or_None, year_or_None). Handles partial dates.
    """
    raw = clean(raw)
    if not raw:
        return None, None
    m = re.match(r"^(\d{4})=(\d{1,2})=(\d{1,2})", raw)
    if m:
        y, mo, d = m.groups()
        try:
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}", int(y)
        except ValueError:
            return None, int(y)
    m = re.match(r"^(\d{4})", raw)
    if m:
        return None, int(m.group(1))
    return None, None


def read_rows(filename: str):
    path = os.path.join(RAW, filename)
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.reader(f):
            yield row


def build():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.executescript(
        """
        CREATE TABLE shows (
            show_id       TEXT PRIMARY KEY,
            date_iso      TEXT,
            year          INTEGER,
            venue         TEXT,
            ticket_price  TEXT,
            source        TEXT
        );
        CREATE TABLE performed_items (
            item_id            TEXT PRIMARY KEY,
            show_id            TEXT,
            title              TEXT,
            genre              TEXT,
            advertising_label  TEXT,
            show_time          TEXT,
            source             TEXT
        );
        CREATE TABLE performers (
            row_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id        TEXT,
            performer_name TEXT,
            performer_id   TEXT
        );
        """
    )

    # ---- shows (from Shows_List.csv; keep rows that carry a show_id) --------
    # col0=date  col6=venue  col11=show_id  col15=ticket_price  col17=source
    shows = {}
    for r in read_rows("Shows_List.csv"):
        if len(r) < 18:
            continue
        show_id = clean(r[11])
        if not show_id:
            continue
        if show_id in shows:
            continue
        iso, year = parse_date(r[0])
        shows[show_id] = (
            show_id,
            iso,
            year,
            clean(r[6]),
            clean(r[15]),
            clean(r[17]),
        )
    cur.executemany(
        "INSERT OR IGNORE INTO shows VALUES (?,?,?,?,?,?)", shows.values()
    )

    # ---- performed_items (from Performed_items.tab.csv) --------------------
    # col1=genre col5=item_id col6=advertising_label col7=show_id
    # col8=show_time col9=source col10=title
    items = []
    for r in read_rows("Performed_items.tab.csv"):
        if len(r) < 11:
            continue
        item_id = clean(r[5])
        if not item_id:
            continue
        items.append(
            (
                item_id,
                clean(r[7]),
                clean(r[10]),
                clean(r[1]),
                clean(r[6]),
                clean(r[8]),
                clean(r[9]),
            )
        )
    cur.executemany(
        "INSERT OR IGNORE INTO performed_items VALUES (?,?,?,?,?,?,?)", items
    )

    # ---- performers (from Performers.csv) ----------------------------------
    # col0=item_id  col3=performer_name  col4=performer_id
    performers = []
    for r in read_rows("Performers.csv"):
        if len(r) < 5:
            continue
        name = clean(r[3])
        item_id = clean(r[0])
        if not name and not item_id:
            continue
        performers.append((item_id, name, clean(r[4])))
    cur.executemany(
        "INSERT INTO performers (item_id, performer_name, performer_id) "
        "VALUES (?,?,?)",
        performers,
    )

    # ---- indexes -----------------------------------------------------------
    cur.executescript(
        """
        CREATE INDEX idx_items_show   ON performed_items(show_id);
        CREATE INDEX idx_items_genre  ON performed_items(genre);
        CREATE INDEX idx_perf_item    ON performers(item_id);
        CREATE INDEX idx_perf_name    ON performers(performer_name);
        CREATE INDEX idx_shows_year   ON shows(year);
        """
    )
    con.commit()

    # ---- report ------------------------------------------------------------
    for t in ("shows", "performed_items", "performers"):
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:16s}: {n:>8,} rows")
    con.close()
    print(f"\nDatabase written to {DB_PATH}")


if __name__ == "__main__":
    print("Building Shanghai Entertainment database...")
    build()
