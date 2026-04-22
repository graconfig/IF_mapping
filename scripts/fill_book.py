"""为一份空白设计书从知识库查找 SAP 字段候选，输出审阅 Markdown。

用法：
  python3 scripts/fill_book.py --project kaps2 <input.xls_or_xlsx>
  python3 scripts/fill_book.py --project kaps2 --schema <path.yaml> <input>

默认会在同目录寻找 <stem>.schema.yaml 作为输入格式描述。
产物：同目录下 <stem>_candidates.md

匹配信号（按优先级合并打分）：
  L1 ext_tech 精确命中  (权重 1.0)
  L2 ext_name 精确命中  (权重 0.7)
  L3 ext_name 归一化命中 (权重 0.5) —— NFKC 归一化去空白/符号
  本书上下文 sap_struct 聚集 → 每命中加分 +0.15 (需 ≥3 次聚集)
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
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl
import yaml

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

ROOT = Path(__file__).resolve().parent.parent
TOP_N = 3


def _col_to_idx(spec: Any) -> int:
    """'A'→1, 'B'→2, 数字按原样。"""
    if isinstance(spec, int):
        return spec
    s = str(spec).strip()
    if s.isdigit():
        return int(s)
    # 字母列 (A,B,C,...AA,AB,...)
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
    """全角→半角 + 去空白/常见符号 + 小写。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\s・\-_／/、。．\.№:：（）()\[\]【】]+", "", s)
    return s.lower()


# ---------- .xls → .xlsx 自动转换 ---------- #

def ensure_xlsx(path: Path) -> Path:
    """.xls 自动转 .xlsx；.xlsx 原样返回。"""
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
        # soffice 有时用不同文件名，直接取目录下第一个 .xlsx
        candidates = list(tmp.glob("*.xlsx"))
        if not candidates:
            raise RuntimeError(f"no xlsx in {tmp}")
        out = candidates[0]
    return out


# ---------- schema 读取 & 字段抽取 ---------- #

def load_input_schema(input_path: Path, override: Path | None = None) -> dict:
    p = override if override else input_path.with_suffix(".schema.yaml")
    # 考虑 .xls 后缀情况
    if not p.exists():
        alt = input_path.parent / (input_path.stem + ".schema.yaml")
        p = alt
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

    header_row = schema["header_row"]
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
        # 跳空行
        if rec.get("ext_name") is None and rec.get("ext_tech") is None:
            continue
        # 终止条件：ext_no 不是数字即视为跨出字段表（常见为 Excel 页脚/作成者信息）
        no_val = rec.get("ext_no")
        if no_val is None:
            continue
        if not (isinstance(no_val, (int, float)) or str(no_val).strip().isdigit()):
            break
        # 跳占位
        name = rec.get("ext_name") or ""
        tech = rec.get("ext_tech") or ""
        if name in skip_names or tech in skip_techs:
            rec["skip"] = True
        fields.append(rec)
    return fields, schema.get("if_meta") or {}


# ---------- 候选检索 ---------- #

def query_by_ext_tech(kb: sqlite3.Connection, tech: str) -> list[sqlite3.Row]:
    return list(kb.execute("""
        SELECT sap_struct, sap_tech, sap_name,
               COUNT(*) AS freq,
               GROUP_CONCAT(DISTINCT ifid) AS ifs,
               GROUP_CONCAT(DISTINCT ext_name) AS ext_names
        FROM field_mappings
        WHERE ext_tech = ? AND sap_tech IS NOT NULL
        GROUP BY sap_struct, sap_tech, sap_name
        ORDER BY freq DESC
    """, (tech,)))


def query_by_ext_name(kb: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    return list(kb.execute("""
        SELECT sap_struct, sap_tech, sap_name,
               COUNT(*) AS freq,
               GROUP_CONCAT(DISTINCT ifid) AS ifs,
               GROUP_CONCAT(DISTINCT ext_tech) AS ext_techs
        FROM field_mappings
        WHERE ext_name = ? AND sap_tech IS NOT NULL
        GROUP BY sap_struct, sap_tech, sap_name
        ORDER BY freq DESC
    """, (name,)))


def query_by_ext_name_norm(kb: sqlite3.Connection, name_norm: str) -> list[sqlite3.Row]:
    """归一化 ext_name 匹配：只要 normalize(ext_name)==name_norm 就命中。"""
    return list(kb.execute("""
        SELECT ext_name, sap_struct, sap_tech, sap_name,
               COUNT(*) AS freq,
               GROUP_CONCAT(DISTINCT ifid) AS ifs
        FROM field_mappings
        WHERE ext_name IS NOT NULL AND sap_tech IS NOT NULL
        GROUP BY ext_name, sap_struct, sap_tech, sap_name
    """))


def pass1_candidates(field: dict, kb: sqlite3.Connection, norm_index: dict) -> list[dict]:
    """初排：合并 L1/L2/L3 三类命中，同一 (struct,tech) 聚合加权求和。"""
    agg: dict[tuple, dict] = {}

    def add(sap_struct, sap_tech, sap_name, freq, ifs, hit_type, weight):
        key = (sap_struct, sap_tech)
        if key not in agg:
            agg[key] = {
                "sap_struct": sap_struct, "sap_tech": sap_tech, "sap_name": sap_name,
                "signals": [], "weighted_freq": 0.0, "raw_freq": 0,
                "ifs": set(),
            }
        c = agg[key]
        c["signals"].append({"type": hit_type, "freq": freq, "weight": weight})
        c["weighted_freq"] += freq * weight
        c["raw_freq"] += freq
        if ifs:
            c["ifs"].update(ifs.split(","))

    # L1 ext_tech
    if field.get("ext_tech"):
        for r in query_by_ext_tech(kb, field["ext_tech"]):
            add(r["sap_struct"], r["sap_tech"], r["sap_name"], r["freq"], r["ifs"],
                "ext_tech_exact", 1.0)

    # L2 ext_name
    if field.get("ext_name"):
        for r in query_by_ext_name(kb, field["ext_name"]):
            add(r["sap_struct"], r["sap_tech"], r["sap_name"], r["freq"], r["ifs"],
                "ext_name_exact", 0.7)

    # L3 ext_name normalize
    if field.get("ext_name"):
        nq = normalize_name(field["ext_name"])
        hit_names = norm_index.get(nq, set()) - {field["ext_name"]}
        for hn in hit_names:
            for r in query_by_ext_name(kb, hn):
                add(r["sap_struct"], r["sap_tech"], r["sap_name"], r["freq"], r["ifs"],
                    f"ext_name_norm({hn})", 0.5)

    return sorted(agg.values(), key=lambda x: x["weighted_freq"], reverse=True)


def build_norm_index(kb: sqlite3.Connection) -> dict[str, set[str]]:
    """归一化名称 → 原始 ext_name 集合。"""
    idx: dict[str, set[str]] = defaultdict(set)
    for (name,) in kb.execute("SELECT DISTINCT ext_name FROM field_mappings WHERE ext_name IS NOT NULL"):
        idx[normalize_name(name)].add(name)
    return idx


def context_structs(fields_with_pass1: list[tuple[dict, list[dict]]]) -> Counter:
    """统计本书所有字段 top-1 候选的 sap_struct 分布。"""
    c: Counter = Counter()
    for field, cands in fields_with_pass1:
        if field.get("skip") or not cands:
            continue
        c[cands[0]["sap_struct"]] += 1
    return c


def pass2_score(cand: dict, total_weighted: float, ctx: Counter) -> tuple[float, list[str]]:
    """最终评分 + 解释。"""
    base = cand["weighted_freq"] / total_weighted if total_weighted else 0.0
    bonus = 0.0
    reasons = []
    if ctx.get(cand["sap_struct"], 0) >= 3:
        bonus += 0.15
        reasons.append(f"上下文+0.15（{cand['sap_struct']} 在本书聚集 ×{ctx[cand['sap_struct']]}）")
    score = min(1.0, base + bonus)
    return score, reasons


# ---------- Markdown 输出 ---------- #

def format_field_header(f: dict) -> str:
    parts = [f"№{f.get('ext_no')}", f.get("ext_name") or "", f.get("ext_tech") or ""]
    tail = []
    if f.get("ext_type"):
        tail.append(f"Type={f['ext_type']}")
    if f.get("ext_len") not in (None, ""):
        tail.append(f"Len={f['ext_len']}")
    if f.get("ext_byte") not in (None, ""):
        tail.append(f"Byte={f['ext_byte']}")
    header = " | ".join(p for p in parts if p)
    if tail:
        header += " | " + " ".join(tail)
    if f.get("remark"):
        header += f" | 備考: {f['remark']}"
    return header


def format_candidate_line(rank: int, cand: dict, score: float, reasons: list[str]) -> list[str]:
    # 按 type 合并信号频次
    agg: dict[str, int] = {}
    for s in cand["signals"]:
        agg[s["type"]] = agg.get(s["type"], 0) + s["freq"]
    signals = ", ".join(f"{t}×{n}" for t, n in sorted(agg.items(), key=lambda x: -x[1]))
    ifs = sorted(cand["ifs"])
    if ifs:
        if_display = ", ".join(ifs[:5])
        if len(ifs) > 5:
            if_display += f" …+{len(ifs)-5}"
    else:
        if_display = "-"
    lines = [
        f"- [ ] **Top-{rank}** 信心 {score:.2f} — `{cand['sap_struct']}.{cand['sap_tech']}` ({cand['sap_name'] or ''})",
        f"  - 信号: {signals}",
        f"  - 历史 IF: {if_display}",
    ]
    for rsn in reasons:
        lines.append(f"  - {rsn}")
    return lines


def render_markdown(
    input_path: Path, if_meta: dict, fields: list[dict],
    field_results: list[tuple[dict, list[dict], float]],
    ctx: Counter,
) -> str:
    n_total = sum(1 for f in fields if not f.get("skip"))
    n_with = sum(1 for _, cands, _ in field_results if cands)
    n_without = n_total - n_with

    lines = [
        f"# {if_meta.get('if_name') or input_path.stem} — SAP 映射候选审阅",
        "",
        f"- 源文件: `{input_path.name}`",
        f"- IFID（推测）: {if_meta.get('ifid_guess') or '?'}",
        f"- 字段总数: {len(fields)}（跳过填充 {sum(1 for f in fields if f.get('skip'))}）",
        f"- 有候选 / 无候选: {n_with} / {n_without}",
        f"- 生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 本书上下文聚集（各字段 Top-1 候选的 SAP 结构分布）",
    ]
    for struct, n in ctx.most_common(8):
        lines.append(f"- `{struct}`: {n} 字段")
    lines.append("")
    lines.append("---")
    lines.append("")

    for (field, cands, total_w), _ in zip(field_results, range(10**9)):
        header = format_field_header(field)
        lines.append(f"## {header}")
        if field.get("skip"):
            lines.append("")
            lines.append("*（填充字段，跳过映射）*")
            lines.append("")
            lines.append("---")
            lines.append("")
            continue
        if not cands:
            lines.append("")
            # 诊断：是否在库里出现过（但 SAP 侧为空）
            lines.append("**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表")
            lines.append("")
            lines.append("---")
            lines.append("")
            continue
        lines.append("")
        for rank, cand in enumerate(cands[:TOP_N], start=1):
            score, reasons = pass2_score(cand, total_w, ctx)
            lines.extend(format_candidate_line(rank, cand, score, reasons))
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


# ---------- 主流程 ---------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="空白设计书 .xls/.xlsx 路径")
    ap.add_argument("--project", required=True, help="使用哪个项目的知识库")
    ap.add_argument("--schema", help="输入 schema yaml 路径（默认 <stem>.schema.yaml）")
    ap.add_argument("--out", help="输出 Markdown 路径（默认 <stem>_candidates.md）")
    args = ap.parse_args()

    in_path = Path(args.input).resolve()
    if not in_path.exists():
        print(f"not found: {in_path}", file=sys.stderr)
        return 1
    schema_path = Path(args.schema).resolve() if args.schema else None

    kb_path = ROOT / "projects" / args.project / "knowledge" / "ifs.db"
    if not kb_path.exists():
        print(f"knowledge base not found: {kb_path}  (run build_index.py first)", file=sys.stderr)
        return 1

    schema = load_input_schema(in_path, schema_path)
    xlsx_path = ensure_xlsx(in_path)
    fields, if_meta = read_blank_book(xlsx_path, schema)

    kb = sqlite3.connect(kb_path)
    kb.row_factory = sqlite3.Row
    norm_index = build_norm_index(kb)

    # Pass 1
    pass1 = [(f, pass1_candidates(f, kb, norm_index) if not f.get("skip") else []) for f in fields]
    ctx = context_structs(pass1)

    # Pass 2: score in render
    results: list[tuple[dict, list[dict], float]] = []
    for f, cands in pass1:
        total_w = sum(c["weighted_freq"] for c in cands) or 1.0
        results.append((f, cands, total_w))

    md = render_markdown(in_path, if_meta, fields, results, ctx)
    out_path = Path(args.out) if args.out else in_path.with_name(in_path.stem + "_candidates.md")
    out_path.write_text(md, encoding="utf-8")
    print(f"wrote → {out_path}")
    print(f"fields: {len(fields)} | w/cand: {sum(1 for _,c,_ in results if c)} | ctx: {dict(ctx.most_common(5))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
