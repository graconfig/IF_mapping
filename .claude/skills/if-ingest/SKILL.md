---
name: if-ingest
description: 从一个目录的历史接口设计书（SAP 字段映射文档）摄取并建立知识库。当用户说"摄取参考文档/历史设计书"、"建立 SAP 映射知识库"、"加载历史接口设计书"、"扫描参考目录建库"或类似意图时触发。典型入参是项目名 + 参考文档目录路径。
---

# if-ingest — 摄取参考文档，建立字段映射知识库

## 何时使用此 skill

- 用户提供一个装有历史接口设计书（Excel）的目录，要求"摄取"/"建立知识库"/"读入参考文档"。
- 新项目首次配置，用户给出项目名与参考文档位置。
- 已有知识库但追加了新设计书，想重跑刷新索引。

## 用户视角

用户**不需要看/编 config.yaml**。整个流程对他是：「给目录 → 稍等 → 拿到知识库统计」。所有格式识别由 skill 和 AI 在后台自动完成；只有 AI 判断存在风险时才用自然语言提简单问题（例如"这些设计书的表头好像不在第 6 行，对吗？"）。

## 执行步骤

### 1. 接收输入
- **项目名**：若未给，默认取参考目录末段（如 `/data/foo/kaps2/` → `kaps2`）。如果仍推不出，用自然语言问。
- **参考文档目录**：绝对路径。
- 如果 `projects/<project>/` 已存在，用自然语言问是"追加重跑"还是"从零新建"（不提 yaml 细节）。

### 2. 准备项目目录
```bash
mkdir -p projects/<project>/{knowledge,fill_out}
ln -sfn <absolute_reference_dir> projects/<project>/sources
```

### 3. 自动探测（后台完成，不向用户展示 yaml）
- 从 `sources/` 挑一份有代表性的 xlsx（优先选文件名含 "受注" / "出荷" / "インボイス" 等明显业务词、或体积较大的）：
  ```bash
  python3 .claude/skills/if-ingest/scripts/detect_schema.py --as reference <sample.xlsx> \
    --project <project> --out projects/<project>/config.yaml
  ```
- 生成的 config.yaml **不向用户展示**，只作为内部缓存。

### 4. AI 语义校验（关键）
用 Read 工具直接打开 1-2 份样本 xlsx（Read 支持 xlsx），检查探测结果是否合理：
- **表头是否在探测出的 `header_row` 行**（看该行是否含"項目名称/Field Name/项目名"等语义词，而不是业务数据）
- **两侧字段块的列位置是否对应"外部字段"和"SAP 字段"**（右侧是否出现 `VBAK/LIKP/MARA` 这类 SAP 表名）
- **SAP 侧识别是否正确**（label 行是否真含"部品SAP/ＳＡＰ"）

如果 Read 无法直接读 xlsx 内容，用 `python3 -c "import openpyxl..."` 的短脚本读取关键行。

**校验通过** → 跳到步骤 6。
**校验可疑** → 步骤 5。

### 5. 仅在需要时求助（A3 兜底）
用**业务语言**问 1-2 个具体问题（不提 yaml / config / header_row 这些词）：
- "这份设计书里写 SAP 字段的表叫什么？（比如 `項目マッピング` / `Mapping` / 别的）"
- "字段列表一般从第几行开始？"
- "哪一列是 SAP 的表名、哪一列是 SAP 的字段名？"

根据回答**直接修改** `projects/<project>/config.yaml` 相应字段（AI 代编辑，不让用户动文件），然后重跑步骤 4 验证。

### 6. 批量抽取建库
```bash
python3 .claude/skills/if-ingest/scripts/build_index.py --project <project>
```
命令支持 .xlsx；如发现 sources/ 里有 .xls，先提示用户或批量用 soffice 转。

### 7. 向用户汇报（业务语言）
读 `knowledge/extract_report.md`，用几句话告诉用户：
- 扫描了 N 个文件，成功抽取 M 条字段映射
- 覆盖的 SAP 表有多少种（举 3-5 个常见的）
- 对向系统有哪些
- 若有文件抽不到内容，列出文件名并简短说原因
- **不提**"config.yaml / header_row / regex" 这些技术细节

### 8. 结束语
提示用户：知识库已可用。下次有空白设计书直接说"map xxx.xls"或"映射这份设计书"触发 `if-map`。

## 关键注意事项

- 全流程**不主动给用户看 config.yaml**；即使 AI 自己修改它也不宣布文件名（可说"已调整参数"）。
- .xls 文件：`build_index.py` 只读 .xlsx。若 sources/ 里有 .xls，需要先用 `soffice --headless --convert-to xlsx` 批量转换（询问用户是否自动转；不主动删除原 .xls）。
- 若 `detect_schema.py` 在 AI 校验前就已报错（比如找不到字段块），直接进入步骤 5 用对话兜底。
- 不要覆盖用户已有的 `projects/<project>/` 除非明确说"从零新建"。
