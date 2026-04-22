"""
字段匹配查询工具。

用法
----
python scripts/match_field.py --name 得意先コード
python scripts/match_field.py --name 品番 --length 10
python scripts/match_field.py --tech KUNNR
python scripts/match_field.py --name 納所コード --ifid IFZ9000003

匹配信号
--------
1. 精确命中: external_name / external_tech_name == 查询
2. 子串包含: external_name LIKE '%name%'
3. SAP 侧命中: sap_name / sap_tech_name 含有查询词（适用于反查：给 SAP 字段找外部字段）
4. 长度/属性一致性加分

返回 Top-N 候选 SAP 字段，带来源 IFID、变换仕様、信心度。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path


def _score(row: dict, q_name: str, q_tech: str, q_length: str | None) -> float:
    s = 0.0
    reasons: list[str] = []
    en = (row["external_name"] or "").lower()
    et = (row["external_tech_name"] or "").lower()
    sn = (row["sap_name"] or "").lower()
    st = (row["sap_tech_name"] or "").lower()
    n = q_name.lower() if q_name else ""
    t = q_tech.lower() if q_tech else ""

    if n:
        if en == n:
            s += 10; reasons.append("ext_name=exact")
        elif en and n in en:
            s += 5; reasons.append("ext_name⊇q")
        elif en and en in n:
            s += 3; reasons.append("q⊇ext_name")
        if sn == n:
            s += 8; reasons.append("sap_name=exact")
        elif sn and n in sn:
            s += 4; reasons.append("sap_name⊇q")
    if t:
        if et == t:
            s += 10; reasons.append("ext_tech=exact")
        elif et and t in et:
            s += 4; reasons.append("ext_tech⊇q")
        if st == t:
            s += 10; reasons.append("sap_tech=exact")
        elif st and t in st:
            s += 5; reasons.append("sap_tech⊇q")
    if q_length and str(row.get("external_length")) == str(q_length):
        s += 1; reasons.append("len=")

    # 有 SAP 映射的才算有价值（没映射的记下来作为参考）
    if row.get("has_sap_mapping"):
        s += 0.5

    row["_reasons"] = ";".join(reasons)
    return s


def search(db: Path, q_name: str, q_tech: str, q_length: str | None,
           ifid: str | None, direction: str | None, topn: int) -> list[dict]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    # 用宽过滤先拿候选集
    where = ["1=1"]
    params: list = []
    if ifid:
        where.append("ifid=?")
        params.append(ifid)
    if direction:
        where.append("direction=?")
        params.append(direction)
    # 至少命中名字或技术名的子串；不限则全表
    like_parts = []
    if q_name:
        like_parts.append("""(
            external_name LIKE ? OR sap_name LIKE ?
            OR current_spec LIKE ? OR note LIKE ?
        )""")
        for _ in range(4):
            params.append(f"%{q_name}%")
    if q_tech:
        like_parts.append("(external_tech_name LIKE ? OR sap_tech_name LIKE ?)")
        params.append(f"%{q_tech}%"); params.append(f"%{q_tech}%")
    if like_parts:
        where.append("(" + " OR ".join(like_parts) + ")")

    sql = f"SELECT * FROM mappings WHERE {' AND '.join(where)}"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    scored = []
    for r in rows:
        sc = _score(r, q_name or "", q_tech or "", q_length)
        if sc > 0:
            r["_score"] = sc
            scored.append(r)
    scored.sort(key=lambda x: -x["_score"])

    # 按 (sap_struct, sap_tech_name) 去重，保留得分最高者+其它来源 IFID 列表
    seen: dict[tuple, dict] = {}
    for r in scored:
        key = (r.get("sap_struct") or "", r.get("sap_tech_name") or "", r.get("external_name") or "")
        if key not in seen:
            r["_also_seen_in"] = []
            seen[key] = r
        else:
            seen[key]["_also_seen_in"].append(r["ifid"])

    return list(seen.values())[:topn]


def format_result(rows: list[dict]) -> str:
    out = []
    for i, r in enumerate(rows, 1):
        sap = f"{r['sap_struct']}.{r['sap_tech_name']}" if r["has_sap_mapping"] else "（未映射）"
        out.append(f"#{i}  score={r['_score']:.1f}  [{r['direction']}] {r['ifid']} {r['if_name']}")
        out.append(f"    外部: {r['external_no']} {r['external_name']}  ({r['external_length']} {r['external_attr']})  tech={r['external_tech_name'] or '-'}")
        out.append(f"    SAP : {sap}  {r['sap_name'] or ''}  ({r['sap_length']} {r['sap_attr']})")
        if r["conversion_spec"]:
            out.append(f"    変換: {r['conversion_spec'][:140]}")
        if r["current_spec"]:
            out.append(f"    仕様: {r['current_spec'][:140]}")
        if r.get("_reasons"):
            out.append(f"    matched_on: {r['_reasons']}")
        if r.get("_also_seen_in"):
            out.append(f"    同字段也见于: {', '.join(sorted(set(r['_also_seen_in'])))}")
        out.append("")
    return "\n".join(out) if out else "（无匹配）"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="knowledge/ifs.db")
    ap.add_argument("--name", default="", help="源字段项目名称（日文）")
    ap.add_argument("--tech", default="", help="源字段技术名称 或 SAP 字段名")
    ap.add_argument("--length", default=None, help="字段长度（过滤）")
    ap.add_argument("--ifid", default=None)
    ap.add_argument("--direction", default=None, choices=[None, "inbound", "outbound"])
    ap.add_argument("-n", "--topn", type=int, default=5)
    args = ap.parse_args()

    if not args.name and not args.tech:
        print("must provide --name or --tech", file=sys.stderr)
        return 2

    rows = search(Path(args.db), args.name, args.tech, args.length,
                  args.ifid, args.direction, args.topn)
    print(format_result(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
