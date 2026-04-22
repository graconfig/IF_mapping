---
name: if-map
description: 对一份待转换的空白接口设计书查询 SAP 字段候选，生成带下拉菜单的 Excel 审阅版。当用户说"把这份设计书映射到 SAP"、"填充 SAP 字段"、"给这份空白文档建议 SAP 候选"、"map xxx.xls"或类似意图时触发。要求先有 `if-ingest` 建好的知识库（projects/<project>/knowledge/ifs.db）。
---

# if-map — 为空白设计书生成 SAP 字段候选

## 何时使用此 skill

- 用户提供一份空白（只填了连携元/源字段）的接口设计书（.xls 或 .xlsx），要求生成 SAP 侧推荐。
- 该项目已通过 `if-ingest` 建好了知识库 —— 通过 `projects/<project>/knowledge/ifs.db` 存在来确认。

## 产物

- `<input_stem>_候选.xlsx` —— 与输入同目录（通常 `projects/<project>/fill_out/`）
  - 追加 3 列：`推奨 SAP 字段`（带 Top-3 下拉）、`信心`（★ 分级）、`備考（业务判断）`
  - 业务化说明文字；复合字段自动拆分
  - 无历史映射的字段也会给出"推测类"候选（带 `[推测]` 前缀）

## 执行步骤

1. **确认输入**
   - 项目名（从上下文提取；若不确定就问）
   - 空白设计书路径
   - 确认 `projects/<project>/knowledge/ifs.db` 存在，若否则提醒先跑 `if-ingest`

2. **自动探测输入 schema**
   - 若 `<input>.schema.yaml` 已在同目录存在，跳过探测
   - 否则运行：
     ```bash
     python3 scripts/detect_schema.py --as blank <input.xls> \
       --if-name "<可选业务名>" \
       --out <input_dir>/<input_stem>.schema.yaml
     ```
   - 读生成的 schema，向用户展示关键字段：
     - `sheet` / `header_row` / `data_start_row`
     - `columns` 语义到列字母的映射（ext_name / ext_tech / ext_type / ext_len / remark）
   - 若有明显错误（如表头行定位不对），提示用户编辑 schema.yaml

3. **用户确认**
   - 询问"schema 可以吗？直接跑还是先编辑？"
   - 确认后进入下一步

4. **运行回填**
   ```bash
   python3 scripts/fill_book.py --project <project> <input.xls>
   ```
   - 支持 .xls 自动转 .xlsx（用 soffice headless）
   - 知识库查询后生成 `<input_stem>_候选.xlsx`

5. **展示统计**
   向用户汇报命令输出里的关键数字：
   - `直接命中` / `推测` / `复合` / `无候选` / `跳过` 数量
   - `ctx top` 上下文聚集的 SAP 结构

6. **下一步提示**
   - 告诉用户产物路径
   - 说明 Excel 中如何使用：
     - `推奨 SAP 字段`列的下拉可切换 Top-3 或"（手动指定）"
     - 信心 ★★★ 可直接采纳；★★ / 需确认 / ★（推测）需人工复核
     - 原 .xls 不变；产物为 .xlsx

## 信心度对照表（向用户解释时用）

| 标签 | 含义 | 建议 |
|---|---|---|
| ★★★ | 历史一致映射或主导（≥85% 频次）| 直接采纳 |
| ★★ | 历史主导候选 + 备选 | 复核后采纳 |
| ★★（历史仅1次，需复核）| 高频次但样本少 | 人工确认 |
| ★ | 并列候选 / 弱主导 | 结合业务判断 |
| 需确认 | 多候选频次相近 | 根据业务语义选 |
| ★（推测）| 无历史映射，推测而来 | 必须复核 |
| — | 无候选或跳过字段 | 接口元数据/填充 |
| 复合字段 | 被拆分成多个 SAP 字段 | 确认每个子字段 |

## 关键注意事项

- **不要**直接改原文件，产物都是独立的 `_候选.xlsx`
- 若探测 schema 失败（如字段布局异常），请用户手工写 schema.yaml
- 若用户说"重新跑"/"刷新"，直接删除同名 `_候选.xlsx` 后重跑即可
- 业务词典路径：默认合并加载 `scripts/business_dict.default.yaml` 与（可选）`projects/<project>/business_dict.yaml`；用户想扩充特定语义时应改后者
