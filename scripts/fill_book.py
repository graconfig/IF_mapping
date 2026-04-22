"""为一份空白设计书从知识库查找 SAP 字段候选，直接回填到 Excel。

用法：
  python3 scripts/fill_book.py --project kaps2 <input.xls_or_xlsx>
  python3 scripts/fill_book.py --project kaps2 --schema <path.yaml> <input>

默认会在同目录寻找 <stem>.schema.yaml 作为输入格式描述。
产物：同目录下 <stem>_候选.xlsx（追加 3 列：推荐 SAP 字段 / 信心 / 说明）
  - "推荐 SAP 字段" 列带下拉菜单，可选 Top-3 或手动
  - 原 .xls 不修改；产物为 .xlsx（openpyxl 不支持写 .xls）

匹配信号（按优先级合并打分）：
  L1 ext_tech 精确命中  (权重 1.0)
  L2 ext_name 精确命中  (权重 0.7)
  L3 ext_name 归一化命中 (权重 0.5) —— NFKC 归一化去空白/符号
  本书上下文 sap_struct 聚集 → 每命中加分 +0.15（需 ≥3 次聚集）
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import openpyxl
import yaml
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

ROOT = Path(__file__).resolve().parent.parent
TOP_N = 3

# 追加列的起始位置（L 列 = 12）。若原表宽度已超过，动态推后。
DEFAULT_APPEND_START = 12

# 说明列颜色
FILL_NO_MATCH = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")   # 浅黄
FILL_STRONG   = PatternFill(start_color="D9EAD3", end_color="D9EAD3", fill_type="solid")   # 浅绿
FILL_WEAK     = PatternFill(start_color="FCE5CD", end_color="FCE5CD", fill_type="solid")   # 浅橙
FILL_HEADER   = PatternFill(start_color="CFE2F3", end_color="CFE2F3", fill_type="solid")   # 浅蓝

NO_MATCH_OPTION = "（无历史映射 — 可能为接口内部字段）"


# ------------- 基础工具 ------------- #

def _col_to_idx(spec: Any) -> int:
    if isinstance(spec, int):
        return spec
    s = str(spec).strip()
    if s.isdigit():
        return int(s)
    n = 0
    for ch in s.upper():
        if not ('A' <= ch <= 'Z'):
            raise ValueError(f"invalid column spec: {spec!r}")
        n = n * 26 + (ord(ch) - ord('A') + 1)
    return n


def _clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return v


def normalize_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\s・\-_／/、。．\.№:：（）()\[\]【】]+", "", s)
    return s.lower()


def normalize_struct(s: str | None) -> str:
    """把 'LIPS\\nLIPS' 这类合并单元格残留归一化到单一 struct。"""
    if not s:
        return ""
    parts = [p.strip() for p in re.split(r"\n", str(s)) if p.strip()]
    return parts[0] if parts else ""


def normalize_multiline(s: str | None) -> str:
    """合并单元格多行 'NTGEW\\nBRGEW' → 'NTGEW+BRGEW'（人类可读地合并）。"""
    if not s:
        return ""
    parts = [p.strip() for p in re.split(r"\n", str(s)) if p.strip()]
    if len(parts) <= 1:
        return parts[0] if parts else ""
    # 去重保序
    seen = set()
    uniq = [p for p in parts if not (p in seen or seen.add(p))]
    return "+".join(uniq)


# ------------- .xls → .xlsx 自动转换 ------------- #

def ensure_xlsx(path: Path) -> Path:
    if path.suffix.lower() == ".xlsx":
        return path
    if path.suffix.lower() != ".xls":
        raise ValueError(f"unsupported extension: {path.suffix}")
    tmp = Path(tempfile.mkdtemp(prefix="fillbook_xls2xlsx_"))
    cmd = ["soffice", "--headless", "--convert-to", "xlsx", "--outdir", str(tmp), str(path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"soffice convert failed: {res.stderr}")
    out = tmp / f"{path.stem}.xlsx"
    if not out.exists():
        candidates = list(tmp.glob("*.xlsx"))
        if not candidates:
            raise RuntimeError(f"no xlsx in {tmp}")
        out = candidates[0]
    return out


# ------------- schema & 字段抽取 ------------- #

def load_input_schema(input_path: Path, override: Path | None = None) -> dict:
    p = override if override else input_path.with_suffix(".schema.yaml")
    if not p.exists():
        p = input_path.parent / (input_path.stem + ".schema.yaml")
    if not p.exists():
        raise FileNotFoundError(
            f"input schema not found: expected {input_path.with_suffix('.schema.yaml')} or pass --schema"
        )
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_blank_book(xlsx_path: Path, schema: dict) -> tuple[list[dict], dict]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    sheet_name = schema.get("sheet") or wb.sheetnames[0]
    ws = wb[sheet_name]

    data_start_row = schema["data_start_row"]
    cols_cfg = schema["columns"]
    col_idx = {sem: _col_to_idx(spec) for sem, spec in cols_cfg.items()}

    skip_names = set(schema.get("skip", {}).get("names") or [])
    skip_techs = set(schema.get("skip", {}).get("techs") or [])

    fields: list[dict] = []
    for r in range(data_start_row, ws.max_row + 1):
        rec = {"row_idx": r}
        for sem, c in col_idx.items():
            rec[sem] = _clean(ws.cell(row=r, column=c).value)
        if rec.get("ext_name") is None and rec.get("ext_tech") is None:
            continue
        no_val = rec.get("ext_no")
        if no_val is None:
            continue
        if not (isinstance(no_val, (int, float)) or str(no_val).strip().isdigit()):
            break  # 末尾页脚
        name = rec.get("ext_name") or ""
        tech = rec.get("ext_tech") or ""
        if name in skip_names or tech in skip_techs:
            rec["skip"] = True
        fields.append(rec)
    return fields, schema.get("if_meta") or {}


# ------------- 候选检索 ------------- #

def query_by_ext_tech(kb: sqlite3.Connection, tech: str) -> list[sqlite3.Row]:
    return list(kb.execute("""
        SELECT sap_struct, sap_tech, sap_name,
               COUNT(*) AS freq,
               GROUP_CONCAT(DISTINCT ifid) AS ifs
        FROM field_mappings
        WHERE ext_tech = ? AND sap_tech IS NOT NULL
        GROUP BY sap_struct, sap_tech, sap_name
        ORDER BY freq DESC
    """, (tech,)))


def query_by_ext_name(kb: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    return list(kb.execute("""
        SELECT sap_struct, sap_tech, sap_name,
               COUNT(*) AS freq,
               GROUP_CONCAT(DISTINCT ifid) AS ifs
        FROM field_mappings
        WHERE ext_name = ? AND sap_tech IS NOT NULL
        GROUP BY sap_struct, sap_tech, sap_name
        ORDER BY freq DESC
    """, (name,)))


def count_ext_tech_in_kb(kb: sqlite3.Connection, tech: str) -> int:
    """历史里 ext_tech 出现总次数（含 SAP 侧为空的行）。"""
    row = kb.execute("SELECT COUNT(*) FROM field_mappings WHERE ext_tech = ?", (tech,)).fetchone()
    return row[0] if row else 0


def build_norm_index(kb: sqlite3.Connection) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = defaultdict(set)
    for (name,) in kb.execute("SELECT DISTINCT ext_name FROM field_mappings WHERE ext_name IS NOT NULL"):
        idx[normalize_name(name)].add(name)
    return idx


def pass1_candidates(field: dict, kb: sqlite3.Connection, norm_index: dict) -> list[dict]:
    agg: dict[tuple, dict] = {}

    def add(sap_struct, sap_tech, sap_name, freq, ifs, hit_type, weight):
        struct_n = normalize_struct(sap_struct)
        tech_n = normalize_multiline(sap_tech)
        name_n = normalize_multiline(sap_name)
        key = (struct_n, tech_n)
        if key not in agg:
            agg[key] = {
                "sap_struct": struct_n, "sap_tech": tech_n, "sap_name": name_n,
                "signals": {}, "weighted_freq": 0.0, "raw_freq": 0,
                "ifs": set(),
            }
        c = agg[key]
        c["signals"][hit_type] = c["signals"].get(hit_type, 0) + freq
        c["weighted_freq"] += freq * weight
        c["raw_freq"] += freq
        if ifs:
            c["ifs"].update(ifs.split(","))

    if field.get("ext_tech"):
        for r in query_by_ext_tech(kb, field["ext_tech"]):
            add(r["sap_struct"], r["sap_tech"], r["sap_name"], r["freq"], r["ifs"],
                "tech_exact", 1.0)

    if field.get("ext_name"):
        for r in query_by_ext_name(kb, field["ext_name"]):
            add(r["sap_struct"], r["sap_tech"], r["sap_name"], r["freq"], r["ifs"],
                "name_exact", 0.7)

        nq = normalize_name(field["ext_name"])
        hit_names = norm_index.get(nq, set()) - {field["ext_name"]}
        for hn in hit_names:
            for r in query_by_ext_name(kb, hn):
                add(r["sap_struct"], r["sap_tech"], r["sap_name"], r["freq"], r["ifs"],
                    "name_norm", 0.5)

    return sorted(agg.values(), key=lambda x: x["weighted_freq"], reverse=True)


def context_structs(pairs: list[tuple[dict, list[dict]]]) -> Counter:
    c: Counter = Counter()
    for field, cands in pairs:
        if field.get("skip") or not cands:
            continue
        c[cands[0]["sap_struct"]] += 1
    return c


def pass2_score(cand: dict, total_weighted: float, ctx: Counter) -> float:
    base = cand["weighted_freq"] / total_weighted if total_weighted else 0.0
    bonus = 0.15 if ctx.get(cand["sap_struct"], 0) >= 3 else 0.0
    return min(1.0, base + bonus)


# ------------- 业务化说明文案 ------------- #

def confidence_label(score: float, raw_freq_top: int) -> str:
    # 单次历史样本警告：历史仅 1 次的，最多给 ★★，提示人工复核
    if raw_freq_top <= 1 and score >= 0.85:
        return "★★（历史仅1次，需复核）"
    if score >= 0.85:
        return "★★★"
    if score >= 0.6:
        return "★★"
    if score >= 0.3:
        return "★"
    return "需确认"


def cand_label(c: dict) -> str:
    """候选在下拉里的显示字符串。"""
    name = c.get("sap_name") or ""
    if name:
        return f"{c['sap_struct']}.{c['sap_tech']}（{name}）"
    return f"{c['sap_struct']}.{c['sap_tech']}"


def explain_no_match(field: dict, kb: sqlite3.Connection) -> str:
    """无候选时的说明，尽量根据历史数据给出具体结论。"""
    tech = field.get("ext_tech")
    name = field.get("ext_name") or "?"
    if tech:
        hist = count_ext_tech_in_kb(kb, tech)
        if hist > 0:
            return (
                f"在历史 {hist} 份映射中出现过"
                f"「{name}（{tech}）」，但都没有对应到 SAP 表字段。"
                f"推测为接口控制字段（文件ID/序号/状态码 等），不需映射。"
            )
    return (
        f"历史中没有「{name}」的 SAP 映射记录。可能是本接口新增字段或接口内部控制信息；"
        f"若确属业务字段，请人工指定对应的 SAP 字段。"
    )


def explain_matched(
    cands: list[dict], total_w: float, ctx: Counter, top_score: float
) -> str:
    top = cands[0]
    top_name = top.get("sap_name") or top["sap_tech"]
    top_loc = f"{top['sap_struct']}.{top['sap_tech']}"
    ifs_ref = sorted(top["ifs"])[:3]
    ifs_str = "、".join(ifs_ref)

    ctx_hit = ctx.get(top["sap_struct"], 0) >= 3

    if len(cands) == 1:
        msg = (
            f"历史上一致映射到「{top_name}」（{top_loc}），"
            f"共 {top['raw_freq']} 次，参考：{ifs_str}。"
            f"建议直接采用。"
        )
        return msg

    top2 = cands[1]
    top_share = top["weighted_freq"] / total_w if total_w else 0.0
    t2_name = top2.get("sap_name") or top2["sap_tech"]
    t2_loc = f"{top2['sap_struct']}.{top2['sap_tech']}"

    if top_share >= 0.7:
        return (
            f"多数历史映射到「{top_name}」（{top_loc}），"
            f"少数映射到「{t2_name}」（{t2_loc}）。"
            f"建议采用主选项，除非业务场景特殊。"
            + (f" 本书已有多个字段指向 {top['sap_struct']}，该推荐更可信。" if ctx_hit else "")
        )
    elif abs(top["weighted_freq"] - top2["weighted_freq"]) / max(total_w, 1) < 0.15:
        # 并列
        return (
            f"历史上存在多种映射方式，「{top_name}」（{top_loc}）与"
            f"「{t2_name}」（{t2_loc}）频次相近。"
            f"两个 SAP 字段语义不同，请根据实际业务判断应使用哪一个。"
        )
    else:
        return (
            f"主要映射是「{top_name}」（{top_loc}），也有若干映射到"
            f"「{t2_name}」（{t2_loc}）。请结合业务判断。"
        )


# ------------- Excel 回填 ------------- #

def render_excel(
    xlsx_path: Path, fields: list[dict],
    results: list[tuple[dict, list[dict], float]],
    ctx: Counter, schema: dict, out_path: Path, kb: sqlite3.Connection,
) -> None:
    wb = openpyxl.load_workbook(xlsx_path)
    sheet_name = schema.get("sheet") or wb.sheetnames[0]
    ws = wb[sheet_name]

    # 追加列起点（取原 max_column 与默认起点中的较大者）
    start_col = max(DEFAULT_APPEND_START, ws.max_column + 1)
    header_row = schema["header_row"]

    # 表头
    headers = ["推奨 SAP 字段", "信心", "備考（业务判断）"]
    for i, h in enumerate(headers):
        cell = ws.cell(row=header_row, column=start_col + i, value=h)
        cell.font = Font(bold=True)
        cell.fill = FILL_HEADER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # 列宽
    for i, w in enumerate([36, 10, 60]):
        ws.column_dimensions[get_column_letter(start_col + i)].width = w

    # 每字段一行写入
    for f, (_, cands, total_w) in zip(fields, results):
        r = f["row_idx"]
        if f.get("skip"):
            ws.cell(row=r, column=start_col, value="（填充字段，跳过）")
            ws.cell(row=r, column=start_col + 1, value="—")
            ws.cell(row=r, column=start_col + 2, value="填充/占位字段，无需映射。")
            for i in range(3):
                ws.cell(row=r, column=start_col + i).fill = FILL_NO_MATCH
            continue

        if not cands:
            # 无候选：只给一个下拉项 + 说明
            ws.cell(row=r, column=start_col, value=NO_MATCH_OPTION)
            ws.cell(row=r, column=start_col + 1, value="—")
            ws.cell(row=r, column=start_col + 2, value=explain_no_match(f, kb))
            for i in range(3):
                ws.cell(row=r, column=start_col + i).fill = FILL_NO_MATCH
            dv = DataValidation(
                type="list",
                formula1=_dv_formula([NO_MATCH_OPTION, "（手动指定）"]),
                allow_blank=True,
            )
            dv.add(ws.cell(row=r, column=start_col).coordinate)
            ws.add_data_validation(dv)
            continue

        # 有候选
        top3 = cands[:TOP_N]
        labels = [cand_label(c) for c in top3]
        top_score = pass2_score(top3[0], total_w, ctx)
        stars = confidence_label(top_score, top3[0]["raw_freq"])
        explanation = explain_matched(top3, total_w, ctx, top_score)

        ws.cell(row=r, column=start_col, value=labels[0])  # 默认 Top-1
        ws.cell(row=r, column=start_col + 1, value=stars).alignment = Alignment(
            horizontal="center"
        )
        ws.cell(row=r, column=start_col + 2, value=explanation).alignment = Alignment(
            wrap_text=True, vertical="top"
        )

        fill = FILL_STRONG if top_score >= 0.6 else FILL_WEAK
        for i in range(3):
            ws.cell(row=r, column=start_col + i).fill = fill

        # 下拉（Top-3 + 手动指定）
        dv_values = list(dict.fromkeys(labels + ["（手动指定）"]))  # 去重保序
        dv = DataValidation(
            type="list",
            formula1=_dv_formula(dv_values),
            allow_blank=True,
            showDropDown=False,  # openpyxl 语义反的：False=显示下拉
        )
        dv.add(ws.cell(row=r, column=start_col).coordinate)
        ws.add_data_validation(dv)

    wb.save(out_path)


def _dv_formula(values: list[str]) -> str:
    """Data validation list 的 formula1 字符串。Excel 用英文逗号分隔，
    单元内引号转义。单元格值不能含英文逗号（会被当分隔），若含则整体
    失败——本工具的候选字符串不会含英文逗号。"""
    safe = [v.replace('"', '""').replace(",", "，") for v in values]
    return '"' + ",".join(safe) + '"'


# ------------- 主流程 ------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="空白设计书 .xls/.xlsx 路径")
    ap.add_argument("--project", required=True, help="使用哪个项目的知识库")
    ap.add_argument("--schema", help="输入 schema yaml 路径（默认 <stem>.schema.yaml）")
    ap.add_argument("--out", help="输出 .xlsx 路径（默认 <stem>_候选.xlsx）")
    args = ap.parse_args()

    in_path = Path(args.input).resolve()
    if not in_path.exists():
        print(f"not found: {in_path}", file=sys.stderr)
        return 1
    schema_path = Path(args.schema).resolve() if args.schema else None

    kb_path = ROOT / "projects" / args.project / "knowledge" / "ifs.db"
    if not kb_path.exists():
        print(f"knowledge base not found: {kb_path}", file=sys.stderr)
        return 1

    schema = load_input_schema(in_path, schema_path)
    xlsx_path = ensure_xlsx(in_path)
    fields, if_meta = read_blank_book(xlsx_path, schema)

    # 写入到产物副本（不改原 xlsx/xls）
    out_path = (
        Path(args.out).resolve()
        if args.out
        else in_path.with_name(in_path.stem + "_候选.xlsx")
    )
    # 把转换后的 xlsx 复制一份做基础
    shutil.copy(xlsx_path, out_path)

    kb = sqlite3.connect(kb_path)
    kb.row_factory = sqlite3.Row
    norm_index = build_norm_index(kb)

    pairs = [
        (f, pass1_candidates(f, kb, norm_index) if not f.get("skip") else [])
        for f in fields
    ]
    ctx = context_structs(pairs)

    results = [
        (f, cands, sum(c["weighted_freq"] for c in cands) or 1.0)
        for f, cands in pairs
    ]

    render_excel(out_path, fields, results, ctx, schema, out_path, kb)
    n_cand = sum(1 for _, c, _ in results if c)
    n_skip = sum(1 for f in fields if f.get("skip"))
    print(f"wrote → {out_path}")
    print(f"fields: {len(fields)} | w/cand: {n_cand} | skip: {n_skip} | ctx: {dict(ctx.most_common(5))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
