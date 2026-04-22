"""
将 knowledge/field_mappings.jsonl 导入 SQLite，建立多维索引。

表结构
------
mappings : 字段映射主表 (每行一条映射记录)
ifs      : 从 mappings 聚合出的 IF 清单 (IFID, IF名, 映射数, 参与的 SAP 表)

索引
----
- 源字段名 / 技术名
- SAP 構造 (表) / SAP 技术名 (字段)
- IFID
- direction
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DDL = """
DROP TABLE IF EXISTS mappings;
DROP TABLE IF EXISTS ifs;

CREATE TABLE mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ifid TEXT NOT NULL,
    if_name TEXT,
    direction TEXT NOT NULL,             -- inbound | outbound
    row_no INTEGER,

    external_no TEXT,
    external_name TEXT,
    external_struct TEXT,
    external_tech_name TEXT,
    external_length TEXT,
    external_attr TEXT,

    sap_no TEXT,
    sap_name TEXT,
    sap_struct TEXT,
    sap_tech_name TEXT,
    sap_length TEXT,
    sap_attr TEXT,
    sap_side_pos TEXT,

    conversion_spec TEXT,
    io TEXT,
    current_spec TEXT,
    code_system TEXT,
    digits TEXT,
    note TEXT,
    adj_remark TEXT,

    has_sap_mapping INTEGER NOT NULL DEFAULT 0,
    source_file TEXT
);

CREATE INDEX idx_map_ifid           ON mappings(ifid);
CREATE INDEX idx_map_direction      ON mappings(direction);
CREATE INDEX idx_map_ext_name       ON mappings(external_name);
CREATE INDEX idx_map_ext_tech       ON mappings(external_tech_name);
CREATE INDEX idx_map_sap_struct     ON mappings(sap_struct);
CREATE INDEX idx_map_sap_tech       ON mappings(sap_tech_name);
CREATE INDEX idx_map_has_sap        ON mappings(has_sap_mapping);

CREATE TABLE ifs (
    ifid TEXT PRIMARY KEY,
    if_name TEXT,
    source_file TEXT,
    n_inbound INTEGER,
    n_outbound INTEGER,
    n_mapped INTEGER,
    sap_tables TEXT  -- 逗号分隔，用到的 SAP 表
);
"""

COLUMNS = [
    "ifid", "if_name", "direction", "row_no",
    "external_no", "external_name", "external_struct", "external_tech_name",
    "external_length", "external_attr",
    "sap_no", "sap_name", "sap_struct", "sap_tech_name",
    "sap_length", "sap_attr", "sap_side_pos",
    "conversion_spec", "io", "current_spec", "code_system",
    "digits", "note", "adj_remark",
    "has_sap_mapping", "source_file",
]


def build(jsonl_path: Path, db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    conn.executescript(DDL)

    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            rows.append(tuple(
                int(r.get(c, 0)) if c == "has_sap_mapping"
                else r.get(c, "") for c in COLUMNS
            ))

    placeholders = ",".join(["?"] * len(COLUMNS))
    conn.executemany(
        f"INSERT INTO mappings ({','.join(COLUMNS)}) VALUES ({placeholders})",
        rows,
    )

    # 聚合 ifs
    conn.execute("""
        INSERT INTO ifs (ifid, if_name, source_file, n_inbound, n_outbound, n_mapped, sap_tables)
        SELECT
            ifid,
            MAX(if_name),
            MAX(source_file),
            SUM(CASE WHEN direction='inbound'  THEN 1 ELSE 0 END),
            SUM(CASE WHEN direction='outbound' THEN 1 ELSE 0 END),
            SUM(has_sap_mapping),
            (SELECT GROUP_CONCAT(DISTINCT sap_struct)
               FROM mappings m2
              WHERE m2.ifid = m1.ifid AND has_sap_mapping=1)
        FROM mappings m1
        GROUP BY ifid
    """)

    conn.commit()
    stats = conn.execute("SELECT COUNT(*), SUM(has_sap_mapping) FROM mappings").fetchone()
    n_ifs = conn.execute("SELECT COUNT(*) FROM ifs").fetchone()[0]
    print(f"[ok] mappings={stats[0]} with_sap={stats[1]} ifs={n_ifs} -> {db_path}", file=sys.stderr)
    conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="knowledge/field_mappings.jsonl")
    ap.add_argument("-d", "--db", default="knowledge/ifs.db")
    args = ap.parse_args()
    build(Path(args.input), Path(args.db))
    return 0


if __name__ == "__main__":
    sys.exit(main())
