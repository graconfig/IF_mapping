"""按対向系统聚合知识库，输出业务画像卡片（供 if-map 的 AI 推测引用）。

用法：
  python3 scripts/build_counterpart_cards.py --project kaps2

输入：projects/<name>/knowledge/ifs.db
产物：projects/<name>/knowledge/counterparts/<safe>.md
       projects/<name>/knowledge/counterparts/_index.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path.cwd()


def _safe_name(s: str) -> str:
    return re.sub(r"[^\w\-]+", "_", s).strip("_") or "unknown"


def _normalize_struct(s: str | None) -> str | None:
    if not s:
        return None
    # 多行 / 备选：取首行
    return str(s).splitlines()[0].strip() or None


def _normalize_tech(t: str | None) -> str | None:
    if not t:
        return None
    return str(t).splitlines()[0].strip() or None


def _direction_zh(d: str | None) -> str:
    return {
        "external_to_sap": "外部→SAP",
        "sap_to_external": "SAP→外部",
    }.get(d or "", d or "unknown")


def _aggregate(rows: list[sqlite3.Row]) -> dict:
    """对一组属于同一 counterpart 的记录做聚合。"""
    ifids = Counter()
    if_names: dict[str, str] = {}  # ifid → if_name（取首次见到）
    directions = Counter()
    structs = Counter()
    fingerprints: Counter = Counter()  # (ext_name, struct, tech, sap_name) → freq
    fingerprint_ifs: dict = defaultdict(set)
    ext_lengths: dict = defaultdict(list)  # ext_name → [len, ...]
    fields_total = 0
    fields_with_sap = 0

    for r in rows:
        fields_total += 1
        ifid = r["ifid"]
        if ifid:
            ifids[ifid] += 1
            if ifid not in if_names and r["if_name"]:
                if_names[ifid] = r["if_name"]
        if r["direction"]:
            directions[r["direction"]] += 1
        struct = _normalize_struct(r["sap_struct"])
        tech = _normalize_tech(r["sap_tech"])
        if struct and tech:
            fields_with_sap += 1
            structs[struct] += 1
            ext_name = (r["ext_name"] or "").strip()
            if ext_name:
                key = (ext_name, struct, tech, (r["sap_name"] or "").strip() or None)
                fingerprints[key] += 1
                if ifid:
                    fingerprint_ifs[key].add(ifid)
        if r["ext_name"] and r["ext_len"]:
            try:
                ln = int(str(r["ext_len"]).strip())
                ext_lengths[r["ext_name"].strip()].append(ln)
            except (ValueError, AttributeError):
                pass

    return {
        "ifids": ifids,
        "if_names": if_names,
        "directions": directions,
        "structs": structs,
        "fingerprints": fingerprints,
        "fingerprint_ifs": fingerprint_ifs,
        "fields_total": fields_total,
        "fields_with_sap": fields_with_sap,
        "ext_lengths": ext_lengths,
    }


def _render_card(cp_name: str, agg: dict) -> str:
    lines = [f"# 対向系统画像：{cp_name}", ""]

    lines.append("## 总览")
    lines.append(f"- 历史接口数：{len(agg['ifids'])}")
    lines.append(f"- 字段总数：{agg['fields_total']}")
    lines.append(f"- 已确定 SAP 映射的字段：{agg['fields_with_sap']}")
    if agg["directions"]:
        dist = ", ".join(f"{_direction_zh(d)} {n}" for d, n in agg["directions"].most_common())
        lines.append(f"- 业务方向：{dist}")
    lines.append("")

    if agg["ifids"]:
        lines.append("## 历史接口（Top 10 — IFID：业务名）")
        for ifid, _ in agg["ifids"].most_common(10):
            nm = agg["if_names"].get(ifid, "")
            lines.append(f"- {ifid}：{nm}")
        lines.append("")

    if agg["structs"]:
        lines.append("## 主要 SAP 表（按字段次数）")
        total = sum(agg["structs"].values())
        for struct, n in agg["structs"].most_common(12):
            pct = n * 100 // max(1, total)
            lines.append(f"- {struct}：{n} ({pct}%)")
        lines.append("")

    fp_top = agg["fingerprints"].most_common(20)
    if fp_top:
        lines.append("## 高频字段指纹（出现 ≥2 次）")
        lines.append("> 历史中该対向系统的稳定 ext_name → SAP 字段映射；同一 ext_name 重复出现说明该対向系统的语义稳定。")
        lines.append("")
        for (ext_name, struct, tech, sap_name), freq in fp_top:
            if freq < 2:
                break
            ifs = sorted(agg["fingerprint_ifs"][(ext_name, struct, tech, sap_name)])
            ifs_str = ",".join(ifs[:5]) + ("..." if len(ifs) > 5 else "")
            sn = f"（{sap_name}）" if sap_name else ""
            lines.append(f"- `{ext_name}` → **{struct}.{tech}**{sn} ×{freq} [{ifs_str}]")
        lines.append("")

    # 长度模式：日期/时刻识别
    date_like = [n for n, lens in agg["ext_lengths"].items() if any(ln == 8 for ln in lens) and ("日" in n or "DATE" in n.upper() or "DT" in n.upper())]
    time_like = [n for n, lens in agg["ext_lengths"].items() if any(ln == 6 for ln in lens) and ("時" in n or "刻" in n or "TIME" in n.upper())]
    if date_like or time_like:
        lines.append("## 类型/长度惯例")
        if date_like:
            lines.append(f"- 日付字段（C(8) YYYYMMDD）：{', '.join(date_like[:8])}")
        if time_like:
            lines.append(f"- 時刻字段（C(6) HHMMSS）：{', '.join(time_like[:8])}")
        lines.append("")

    return "\n".join(lines)


def build_cards(db_path: Path, out_dir: Path) -> dict[str, str]:
    """生成所有 counterpart 卡片。返回 counterpart 名 → 相对文件路径。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cps = [r[0] for r in conn.execute(
        "SELECT DISTINCT counterpart_system FROM field_mappings "
        "WHERE counterpart_system IS NOT NULL"
    )]

    index: dict[str, str] = {}
    for cp in cps:
        rows = conn.execute(
            "SELECT * FROM field_mappings WHERE counterpart_system = ?", (cp,)
        ).fetchall()
        if not rows:
            continue
        agg = _aggregate(rows)
        card = _render_card(cp, agg)
        fname = f"{_safe_name(cp)}.md"
        (out_dir / fname).write_text(card, encoding="utf-8")
        index[cp] = fname

    (out_dir / "_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    conn.close()
    return index


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, help="项目名")
    args = ap.parse_args()

    proj_root = ROOT / "projects" / args.project
    db_path = proj_root / "knowledge" / "ifs.db"
    out_dir = proj_root / "knowledge" / "counterparts"

    if not db_path.exists():
        print(f"not found: {db_path} — 先跑 build_index.py", file=sys.stderr)
        return 1

    index = build_cards(db_path, out_dir)
    print(f"wrote {len(index)} counterpart cards → {out_dir}")
    for cp, fname in sorted(index.items()):
        print(f"  - {cp} → {fname}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
