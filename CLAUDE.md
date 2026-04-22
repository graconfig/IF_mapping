# IF_mapping 项目说明（给未来的 Claude 对话）

这是一个 **SAP 接口字段映射知识库** 项目。目标是把 `历史设计书/` 下的
インタフェース項目定義書 (.xlsx) 抽成结构化数据，用于在新接口设计时
快速找到"外部字段 → SAP 字段"的对应。

## 目录约定

- `021_インタフェース一覧_R1.01.xlsx` — 根目录：全 IF 元数据总览（当前 pilot 阶段未使用）
- `历史设计书/` — 44 份既有设计书（.xlsx）
- `knowledge/` — 抽取后的结构化数据
  - `field_mappings.jsonl` — 主数据
  - `ifs.db` — SQLite 索引库
  - `README.md` — 使用说明
- `scripts/` — 工具脚本
  - `extract_mapping.py` / `build_index.py` / `match_field.py`

## 核心约定

1. **当前只抽取 `項目マッピング(受信)` 与 `項目マッピング(返信)` 两张表**。
   不抽 `IFレイアウト`、协议表等（用户已明确）。
2. **SAP 侧靠"構造"列内容识别**（大写字母组成的表名），不要相信工作表
   R4 行的 `K-Warranty` / `部品SAP` 表头（模板残留，返信表中位置是反的）。
3. **方向语义**：
   - `direction=inbound` 对应受信表 = 外部→SAP
   - `direction=outbound` 对应返信表 = SAP→外部
4. **存储分工**：JSONL 作为信息源（git 友好、易复核）；SQLite 仅作为索引（可随时从 JSONL 重建）。

## 新增一份参考文档的标准流程

```bash
# 放到 历史设计书/ 或 参考资料/ 下
python3 scripts/extract_mapping.py <新文件.xlsx> -o knowledge/field_mappings.jsonl --append
python3 scripts/build_index.py
```

若新文档格式与既有模板差异较大（列位置不同），先 probe 列结构，再考虑在
`extract_mapping.py` 里加个 sheet 模板识别分支，而不是魔改现有的列索引常量。

## 被用户问到"某某外部字段对应 SAP 什么"时的标准响应

先跑 `python3 scripts/match_field.py --name <字段名>`（或 `--tech`），
把 Top-N 结果交给用户复核再定。不要凭记忆回答。

## 阶段性状态

- [x] Pilot 跑通：`IFZ9000003 無償受注連携` — 80 条记录，26 条映射到 SAP
- [ ] 全量：批量抽取剩余 43 份
- [ ] 后续：同义词字典 `synonyms.yaml`、コード体系手册 `codebook.md`（全量后再做）
