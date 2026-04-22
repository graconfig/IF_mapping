---
name: if-ingest
description: 从一个目录的历史接口设计书（SAP 字段映射文档）摄取并建立知识库。当用户说"摄取参考文档/历史设计书"、"建立 SAP 映射知识库"、"加载历史接口设计书"、"扫描参考目录建库"或类似意图时触发。典型入参是项目名 + 参考文档目录路径。
---

# if-ingest — 摄取参考文档，建立字段映射知识库

## 何时使用此 skill

- 用户提供一个装有历史接口设计书（Excel/xlsx 或 xls）的目录，要求"摄取"/"建立知识库"/"读入参考文档"。
- 新项目首次配置，用户给出项目名和参考文档位置。
- 用户已有知识库但追加了新设计书，想重跑扫描刷新索引。

## 产物

- `projects/<project>/config.yaml` — 项目探测配置（自动生成 + 可人工复核）
- `projects/<project>/sources/` — 参考文档目录（软链或直接存放）
- `projects/<project>/knowledge/field_mappings.jsonl` — 字段映射主库
- `projects/<project>/knowledge/ifs.db` — SQLite 索引（供 `if-map` 查询）
- `projects/<project>/knowledge/extract_report.md` — 抽取统计

## 执行步骤

1. **确认输入**
   - 项目名（若未提供则询问；默认用目录名，如 `kaps2`）
   - 参考文档目录的绝对路径
   - 如果目录已存在 `projects/<project>/`，提醒用户是"新建/覆盖" vs "追加重跑"

2. **准备项目目录**
   ```bash
   mkdir -p projects/<project>/{knowledge,fill_out}
   # 把参考文档目录作为 sources（软链或复制均可）
   ln -sfn <absolute_reference_dir> projects/<project>/sources
   ```

3. **自动探测配置**
   - 从参考目录里挑一份有代表性的 xlsx 样本（优先选**含双表式 `項目マッピング(受信)/(返信)` 或最大**的那份）
   - 运行：
     ```bash
     python3 scripts/detect_schema.py --as reference <sample.xlsx> \
       --project <project> --out projects/<project>/config.yaml
     ```
   - 读取生成的 `config.yaml`，向用户展示关键字段：
     - `mapping_sheet.header_row / data_start_row / label_row`
     - `target_side.label_patterns`（SAP 侧 label 正则）
     - `if_meta.ifid_cell / if_name_cell` 位置
   - 明确告诉用户：若任一项异常，可手工编辑 `projects/<project>/config.yaml` 后继续

4. **用户确认**
   - 询问"是否直接建库，还是先让你修改 config.yaml？"
   - 若用户让直接跑，进入下一步；若让 review，等待用户修改完成信号

5. **批量抽取 + 建索引**
   ```bash
   python3 scripts/build_index.py --project <project>
   ```
   这一步会扫描 `sources/` 下所有 xlsx（支持 .xls 需先用 soffice 转换，或提醒用户）。

6. **展示统计**
   读 `projects/<project>/knowledge/extract_report.md`，向用户汇报：
   - 扫描/抽取成功/失败的文件数
   - 总记录数、有 SAP 技术名的记录数
   - 不同 SAP 构造数、対向先系统数
   - 若有 0 条抽取的文件，列出文件名（通常是特殊格式需要手工处理）

7. **下一步提示**
   - 提示用户：知识库已可用；使用 `if-map` skill 对空白设计书回填 SAP 字段

## 关键注意事项

- 若 `sources/` 目录里含 .xls（旧格式）文件，`build_index.py` 目前只读 .xlsx，需要先用 soffice 批量转换或跳过。不要自动删除原 .xls。
- `detect_schema.py` 可能在特殊格式的 Excel 上失败（比如没有标准 "項目マッピング" 工作表）—— 失败时向用户请教样本的实际结构。
- 若用户未提供项目名，默认取参考目录的最后一段（如 `/data/foo/kaps2/` → `kaps2`）。
- **不要**自动删除或覆盖用户现有的 `projects/<project>/config.yaml`：若文件已存在，询问"覆盖 / 保留 / diff"。
- 项目 SAP 通用业务词典无需在此配置 —— `if-map` 会自动加载 `scripts/business_dict.default.yaml` 与 `projects/<project>/business_dict.yaml`（可选）合并使用。
