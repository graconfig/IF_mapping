"""按项目配置批量抽取 + 建 SQLite 索引。

用法：
  python3 scripts/build_index.py --project kaps2
  python3 scripts/build_index.py --config projects/kaps2/config.yaml   # 等价

产物（写入 projects/<name>/<out_dir>/）：
  field_mappings.jsonl   — 字段映射主库
  ifs.db                 — SQLite 索引
  extract_report.md      — 统计报告
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_mapping import extract_file, load_config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


SCHEMA = """
DROP TABLE IF EXISTS field_mappings;
CREATE TABLE field_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    sheet TEXT NOT NULL,
    row_idx INTEGER NOT NULL,
    ifid TEXT,
    if_name TEXT,
    counterpart_system TEXT,
    sap_side_label TEXT,
    sap_side TEXT,
    direction TEXT,
    ext_no TEXT, ext_name TEXT, ext_struct TEXT, ext_tech TEXT, ext_len TEXT, ext_attr TEXT,
    sap_no TEXT, sap_name TEXT, sap_struct TEXT, sap_tech TEXT, sap_len TEXT, sap_attr TEXT,
    conv_spec TEXT, conv_current TEXT,
    sap_digits TEXT, sap_code_system TEXT, sap_supplement TEXT,
    unrealizable_no TEXT, unrealizable_class TEXT, remark TEXT
);
CREATE INDEX idx_fm_ifid ON field_mappings(ifid);
CREATE INDEX idx_fm_ext_name ON field_mappings(ext_name);
CREATE INDEX idx_fm_ext_tech ON field_mappings(ext_tech);
CREATE INDEX idx_fm_sap_tech ON field_mappings(sap_tech);
CREATE INDEX idx_fm_sap_struct ON field_mappings(sap_struct);
CREATE INDEX idx_fm_counterpart ON field_mappings(counterpart_system);
CREATE INDEX idx_fm_direction ON field_mappings(direction);
"""


def _resolve_config(args: argparse.Namespace) -> Path:
    if args.config:
        return Path(args.config)
    if args.project:
        return ROOT / "projects" / args.project / "config.yaml"
    print("need --project <name> or --config <path>", file=sys.stderr)
    sys.exit(2)


def _insert_sql_from_keys(keys: list[str]) -> str:
    cols = ", ".join(keys)
    params = ", ".join(f":{k}" for k in keys)
    return f"INSERT INTO field_mappings ({cols}) VALUES ({params})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", help="项目名（projects/<name>/config.yaml）")
    ap.add_argument("--config", help="直接指定 config.yaml 路径")
    args = ap.parse_args()

    config_path = _resolve_config(args).resolve()
    config = load_config(config_path)
    cfg_root = config_path.parent
    src_dir = (cfg_root / config.get("sources_dir", "sources")).resolve()
    out_dir = (cfg_root / config.get("out_dir", "knowledge")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    out_jsonl = out_dir / "field_mappings.jsonl"
    out_db = out_dir / "ifs.db"
    out_report = out_dir / "extract_report.md"

    xlsx_files = sorted(src_dir.glob("*.xlsx"))
    print(f"[{config.get('name', '?')}] scanning {len(xlsx_files)} files in {src_dir}")

    all_records: list[dict] = []
    per_file: list[tuple[str, int, str | None]] = []
    errors: list[tuple[str, str]] = []

    for p in xlsx_files:
        try:
            recs = extract_file(p, config)
            all_records.extend(recs)
            ifid = recs[0]["ifid"] if recs else None
            per_file.append((p.name, len(recs), ifid))
        except Exception as e:
            errors.append((p.name, f"{type(e).__name__}: {e}"))
            per_file.append((p.name, 0, None))

    with out_jsonl.open("w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"wrote {len(all_records)} records → {out_jsonl}")

    conn = sqlite3.connect(out_db)
    conn.executescript(SCHEMA)
    if all_records:
        keys = list(all_records[0].keys())
        conn.executemany(_insert_sql_from_keys(keys), all_records)
    conn.commit()
    conn.close()

    stats = {
        "project": config.get("name"),
        "files_scanned": len(xlsx_files),
        "files_failed": len(errors),
        "total_records": len(all_records),
        "with_sap_tech": sum(1 for r in all_records if r.get("sap_tech")),
        "with_sap_struct": sum(1 for r in all_records if r.get("sap_struct")),
        "with_ext_tech": sum(1 for r in all_records if r.get("ext_tech")),
        "unique_sap_structs": len({r["sap_struct"] for r in all_records if r.get("sap_struct")}),
        "unique_counterparts": len({r["counterpart_system"] for r in all_records if r.get("counterpart_system")}),
        "direction_dist": Counter(r.get("direction") or "unknown" for r in all_records),
    }
    top_structs = Counter(r["sap_struct"] for r in all_records if r.get("sap_struct")).most_common(20)
    top_cp = Counter(r["counterpart_system"] for r in all_records if r.get("counterpart_system")).most_common(15)
    top_ext = Counter(r["ext_name"] for r in all_records if r.get("ext_name")).most_common(15)

    lines = [
        f"# 抽取统计报告 — {stats['project']}",
        "",
        f"- 配置: `{config_path}`",
        f"- 数据源: `{src_dir}`",
        f"- 扫描文件: {stats['files_scanned']}",
        f"- 抽取失败: {stats['files_failed']}",
        f"- 记录总数: {stats['total_records']}",
        f"- 方向分布: {dict(stats['direction_dist'])}",
        f"- 有 SAP 技术名: {stats['with_sap_tech']} "
        f"({stats['with_sap_tech']*100//max(1,stats['total_records'])}%)",
        f"- 有 SAP 构造: {stats['with_sap_struct']}",
        f"- 有 外部技术名: {stats['with_ext_tech']}",
        f"- 不同 SAP 构造数: {stats['unique_sap_structs']}",
        f"- 不同対向先系统数: {stats['unique_counterparts']}",
        "",
        "## SAP 构造 Top 20",
    ]
    for k, v in top_structs:
        lines.append(f"- {k}: {v}")
    lines.append("\n## 対向先系统 Top 15")
    for k, v in top_cp:
        lines.append(f"- {k}: {v}")
    lines.append("\n## 外部字段名 Top 15")
    for k, v in top_ext:
        lines.append(f"- {k}: {v}")
    lines.append("\n## 每文件抽取条数")
    for name, n, ifid in per_file:
        lines.append(f"- [{ifid or '?'}] {name}: {n}")
    if errors:
        lines.append("\n## 错误")
        for name, err in errors:
            lines.append(f"- {name}: {err}")
    out_report.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote report → {out_report}")
    print(f"wrote sqlite → {out_db}")
    print()
    print(
        f"records: {stats['total_records']} | w/ sap_tech: {stats['with_sap_tech']} | "
        f"w/ sap_struct: {stats['with_sap_struct']} | w/ ext_tech: {stats['with_ext_tech']}"
    )
    print(
        f"unique SAP structs: {stats['unique_sap_structs']} | counterparts: {stats['unique_counterparts']}"
    )
    print(f"direction: {dict(stats['direction_dist'])}")
    if errors:
        print(f"errors in {len(errors)} files — see report")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
