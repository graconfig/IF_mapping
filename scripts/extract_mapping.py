"""
从一份 SAP 接口设计书 (インタフェース項目定義書 .xlsx) 中抽取
項目マッピング(受信) 与 項目マッピング(返信) 两张工作表，
把每一行字段映射规范化为一条 JSON 记录，输出到 JSONL。

设计约定
--------
- 工作表统一为 23 列；从第 6 行 (0-based index=5 是表头，=6 起为数据) 开始读。
- 左块  列 0..5    : №/項目名称/構造/技術名称/文字数/属性
- 中间  列 6..9    : №/変換仕様/I-O/現行編集仕様
- 右块  列 10..15  : №/項目名称/構造/技術名称/文字数/属性
- 右尾  列 17..22  : 桁数/コード体系/補足/No./分類/備考

方向识别（SAP 在哪一侧）
-----------------------
- 受信 sheet: SAP 通常在右侧 (連携元=外部、連携先=部品SAP)
- 返信 sheet: SAP 通常在左侧 (連携元=部品SAP、連携先=外部)
不依赖工作表表头文字（模板里有残留），改为根据 "構造" 列内容：
含有 VBAK/VBAP/VBEP/ADRC/MBEW/MAKT/PRCD_ELEMENTS 等大写 SAP 表名样式即判为 SAP 侧。
若两侧都像/都不像，回退到 sheet 名推断。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import openpyxl

MAPPING_SHEETS = {"項目マッピング(受信)": "inbound", "項目マッピング(返信)": "outbound"}

# SAP 表名样式：3-6 位大写字母(可含下划线/数字)。用于判断哪一侧是 SAP。
SAP_STRUCT_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


def _norm(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return s


def _looks_like_sap_struct(s: str) -> bool:
    if not s:
        return False
    # 允许多行（同一行映射到多个 SAP 字段的情况，如 "ADRC\nADRC"）
    parts = [p.strip() for p in re.split(r"[\n,、/]+", s) if p.strip()]
    if not parts:
        return False
    return all(bool(SAP_STRUCT_RE.match(p)) for p in parts)


def _extract_header(ws) -> dict[str, str]:
    """从 sheet 头部读 IFID / IF 名称。"""
    ifid = _norm(ws.cell(row=2, column=1).value)
    if_name = _norm(ws.cell(row=2, column=3).value)
    return {"ifid": ifid, "if_name": if_name}


def _row_cells(row: tuple) -> list[str]:
    return [_norm(c) for c in row]


def _parse_mapping_sheet(ws, sheet_kind: str) -> list[dict]:
    """
    sheet_kind: 'inbound' (受信) | 'outbound' (返信)
    """
    head = _extract_header(ws)
    records: list[dict] = []

    for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if r_idx <= 6:  # 前 6 行是表头/元信息
            continue
        c = _row_cells(row)
        # 保证列数
        while len(c) < 23:
            c.append("")

        left = {
            "no": c[0],
            "name": c[1],
            "struct": c[2],
            "tech_name": c[3],
            "length": c[4],
            "attr": c[5],
        }
        middle = {
            "no_ref": c[6],
            "conversion_spec": c[7],
            "io": c[8],
            "current_spec": c[9],
        }
        right = {
            "no": c[10],
            "name": c[11],
            "struct": c[12],
            "tech_name": c[13],
            "length": c[14],
            "attr": c[15],
        }
        tail = {
            "digits": c[17],
            "code_system": c[18],
            "note": c[19],
            "adj_no": c[20],
            "adj_class": c[21],
            "adj_remark": c[22],
        }

        # 过滤全空行
        if not any(left.values()) and not any(right.values()) and not any(middle.values()):
            continue

        # 判定 SAP 侧
        left_is_sap = _looks_like_sap_struct(left["struct"])
        right_is_sap = _looks_like_sap_struct(right["struct"])
        if left_is_sap and not right_is_sap:
            sap_side, ext_side, sap_pos = left, right, "left"
        elif right_is_sap and not left_is_sap:
            sap_side, ext_side, sap_pos = right, left, "right"
        else:
            # 回退：受信默认 SAP 在右，返信默认 SAP 在左
            if sheet_kind == "inbound":
                sap_side, ext_side, sap_pos = right, left, "right"
            else:
                sap_side, ext_side, sap_pos = left, right, "left"

        record = {
            "ifid": head["ifid"],
            "if_name": head["if_name"],
            "direction": sheet_kind,  # inbound=外部→SAP; outbound=SAP→外部
            "row_no": r_idx,
            "external_no": ext_side["no"],
            "external_name": ext_side["name"],
            "external_struct": ext_side["struct"],
            "external_tech_name": ext_side["tech_name"],
            "external_length": ext_side["length"],
            "external_attr": ext_side["attr"],
            "sap_no": sap_side["no"],
            "sap_name": sap_side["name"],
            "sap_struct": sap_side["struct"],
            "sap_tech_name": sap_side["tech_name"],
            "sap_length": sap_side["length"],
            "sap_attr": sap_side["attr"],
            "sap_side_pos": sap_pos,  # left|right — 便于回溯原表
            "conversion_spec": middle["conversion_spec"],
            "io": middle["io"],
            "current_spec": middle["current_spec"],
            "code_system": tail["code_system"],
            "digits": tail["digits"],
            "note": tail["note"],
            "adj_remark": tail["adj_remark"],
            # 当本行未明确映射到 SAP 字段时标记
            "has_sap_mapping": bool(sap_side["struct"] and sap_side["tech_name"]),
        }
        records.append(record)

    return records


def extract_file(path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    all_records: list[dict] = []
    for sheet_name, kind in MAPPING_SHEETS.items():
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        recs = _parse_mapping_sheet(ws, kind)
        for r in recs:
            r["source_file"] = path.name
        all_records.extend(recs)
    wb.close()
    return all_records


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="设计书 .xlsx 文件路径（可多个）")
    ap.add_argument("-o", "--output", required=True, help="输出 JSONL 路径")
    ap.add_argument("--append", action="store_true", help="追加而非覆盖")
    args = ap.parse_args()

    mode = "a" if args.append else "w"
    total = 0
    with open(args.output, mode, encoding="utf-8") as f:
        for p in args.inputs:
            path = Path(p)
            if not path.exists():
                print(f"[skip] not found: {p}", file=sys.stderr)
                continue
            try:
                recs = extract_file(path)
            except Exception as e:
                print(f"[error] {path.name}: {e}", file=sys.stderr)
                continue
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            total += len(recs)
            print(f"[ok] {path.name}: {len(recs)} records", file=sys.stderr)
    print(f"[done] total={total} -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
