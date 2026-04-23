# 设计文档 — IF Mapping

## 目标

让接口设计书里"外部字段 → SAP 字段"的映射工作由 AI 辅助完成，核心要求：

1. **通用** — 不绑定特定 SAP 项目；换客户、换模板不改代码
2. **零配置体验** — 用户不看、不编 yaml；AI 和 skill 在后台完成格式探测与匹配
3. **可扩展** — 新业务域通过业务词典而非代码修改来补充
4. **可审阅** — 回填产物是标准 Excel + 下拉，业务方直接在办公软件里审阅

## 架构

```
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  参考文档目录      │      │   知识库          │      │  空白设计书        │
│  历史接口设计书    │ ───► │  (SQLite+JSONL)  │ ◄─── │  (只填连携元侧)   │
└──────────────────┘      │  2150 条映射      │      └──────────────────┘
        ▲                  │  72 SAP 构造      │                │
        │                  │  19 对向系统      │                ▼
   if-ingest skill          └──────────────────┘           if-map skill
   (摄取建库)                         ▲                    (查库+推测+回填)
                                      │                          │
                                      │                          ▼
                         ┌────────────┴──────┐      ┌──────────────────┐
                         │  项目配置 yaml     │      │  候选 xlsx        │
                         │  自动探测生成      │      │  下拉+信心+说明   │
                         └───────────────────┘      └──────────────────┘
```

两个 skill 职责分离、互不依赖（除了 if-map 要求 if-ingest 已建好 ifs.db）。

## 数据模型

### 知识库字段映射（`field_mappings.jsonl` / `ifs.db`）

每条记录代表一行"外部字段 ↔ SAP 字段"映射，归一化成固定语义（不是"源/目标"这种相对概念）：

```jsonc
{
  "source_file": "091_IFZ9000003_無償受注連携.xlsx",
  "sheet": "項目マッピング(受信)",
  "row_idx": 7,
  "ifid": "IFZ9000003",
  "if_name": "無償受注連携",
  "counterpart_system": "K-Warranty",          // 外部系统名
  "direction": "external_to_sap",              // external_to_sap | sap_to_external
  "sap_side": "right",                          // 诊断：SAP 字段块在 Excel 哪一侧

  // 外部系统侧
  "ext_no": "S070", "ext_name": "得意先コード",
  "ext_struct": null, "ext_tech": null,
  "ext_len": "6", "ext_attr": "文字(半角のみ)",

  // SAP 侧
  "sap_no": "S070", "sap_name": "受注先",
  "sap_struct": "VBAK", "sap_tech": "KUNNR",
  "sap_len": "10", "sap_attr": "CHAR",

  // 变换 + 业务补充
  "conv_spec": "受信時データをそのまま設定",
  "sap_code_system": "得意先",
  "remark": "..."
}
```

**为什么归一化 ext/sap 而非源/目标**：历史设计书模板有三种变体（双表受信/返信、单表、多子表），且不同接口方向下同一侧可能是源也可能是目标。把"字段块相对位置"抹平成"外部/SAP"语义，能让后续查询和匹配不再关心数据流向。

### SQLite 索引维度

- `ifid` — 按接口查
- `ext_name` / `ext_tech` — 按外部字段名/技术名查（精确匹配主要入口）
- `sap_tech` / `sap_struct` — 按 SAP 字段 / 表查（用于结构字典）
- `counterpart_system` — 按对向系统聚合
- `direction` — 按方向过滤

## 三类核心组件

### 1. 抽取器 `extract_mapping.py`（if-ingest）

单文件抽取：读一份 Excel → 吐 JSON 记录列表。

核心挑战：历史设计书模板不统一。实际观察到 **3 种模板变体 + 语义翻转**：

| 模板 | 右侧"连携先"列 | A5 含义 | 右侧标签 | 方向 |
|---|---|---|---|---|
| 双表（受信/返信）| K-P | K-Warranty | 部品SAP | 外部→SAP |
| 单表 23 列 | K-P | **部品SAP** | K-FRONTIER | **SAP→外部** |
| 单表 22 列 | **J-O** | 部品SAP | KWINC2/海外販社 | SAP→外部 |
| 单表 21 列 | **I-N** | SBOM | 部品SAP | 外部→SAP |

**抽取策略**：
1. **字段块位置不硬编码** — 扫第 6 行，找连续 6 列命中 `№/項目名称/構造/技術名称/文字数/属性` 语义，自动定位两个字段块
2. **SAP 侧用 label 判定** — 第 5 行含 `部品SAP` / `ＳＡＰ` 的那一侧是 SAP，另一侧是外部
3. **方向推断** — 工作表后缀 `(受信)/(返信)` > 文件名标记 `※受信/※送信` > fallback 到 SAP 所在侧

配置从 `projects/<name>/config.yaml` 注入，所以换项目（不同模板、不同表头词汇、不同 SAP label）不改代码。

### 2. 构建器 `build_index.py`（if-ingest）

批量抽取 → JSONL + SQLite + 统计报告。

```bash
python3 build_index.py --project kaps2
```

扫 `sources/` 下每份 xlsx，调 extract_mapping，合并写入 `knowledge/`。SQLite 有 6 个索引，查询毫秒级。

### 3. 回填器 `fill_book.py`（if-map）

**三层命中（historically grounded）**：

| 层 | 信号 | 权重 |
|---|---|---|
| L1 | `ext_tech` 精确命中知识库 | 1.0 |
| L2 | `ext_name` 精确命中 | 0.7 |
| L3 | `ext_name` 归一化命中（NFKC+去空白/符号）| 0.5 |

命中后按 `(sap_struct, sap_tech)` 聚合，按加权频次排 Top-3。

**三层推测（无直接命中时）**：

| 层 | 信号 | 权重 | 说明 |
|---|---|---|---|
| S1 | 名称子串匹配（提取关键词+去后缀词根）| 0.15（freq 封顶 3）| 避免偶发 1 次主导 |
| S3 | 业务语义词典命中（regex）| 0.6（rank factor 1.0/0.7/0.5）| 人工维护，跨项目共用 |
| S2 | 本书上下文聚集加分 | +0.35 | 只对已产出候选加分，不独立产生候选（避免 VBAP.MATNR 刷到所有字段）|

推测类候选显示 `[推测]` 前缀，信心度最高 `★（推测）`，与历史直接映射严格区分。

**复合字段拆分**：备注里含 `得意先6桁+納所3桁` 这种模式时，自动拆两个子字段分别推荐，产物里显示 `得意先→BESG.KUNNR + 納所→LIKP.KUNNR`。

**上下文聚集策略**：Pass 1 先扫全部字段的直接命中，统计本书 Top-N 的 SAP 结构。Pass 2 对每个候选，若其结构在本书聚集 ≥3 次，加 0.15 分。这利用了"同一 IF 内字段倾向属于同一 SAP 段/表"的先验，显著提升消歧质量。

### 4. 探测器 `detect_schema.py`（两个 skill 各一份）

**if-ingest 版** — 从一份参考文档样本探测：
- 映射表工作表（名字含 `マッピング/Mapping/映射`）
- 表头行（第几行出现 ≥4 个字段语义词）
- 两个字段块的列位置（左右对称）
- SAP 侧（label 行含 `部品SAP` 的一侧）

→ 产出 `projects/<name>/config.yaml` 草稿。

**if-map 版** — 从一份空白设计书样本探测：
- 主工作表
- 表头行
- 单边字段块（外部字段侧）
- 可选 remark 列

→ 产出 `<stem>.schema.yaml` 草稿。

两份脚本共享探测核心逻辑（表头扫描、字段块识别），但裁剪后各自只做自己范围内的事，不共用代码。

### 5. 业务词典

两层合并：

```
scripts/business_dict.default.yaml      ← 跨项目 SAP 通用词典（20+ 条 regex）
projects/<name>/business_dict.yaml      ← 项目特有补充（可选）
```

每条 pattern：

```yaml
- regex: "(?:^|[^A-Za-z])数$|数量|個数|件数|ケース"
  suggest:
    - { struct: LIPS, tech: LFIMG,  name: "出荷数量" }
    - { struct: VBAP, tech: KWMENG, name: "受注数量" }
  hint: "数量字段：出荷→LIPS.LFIMG；受注→VBAP.KWMENG"
```

或跳过类（接口内部字段）：

```yaml
- regex: "^予備$|^FIL\\d|保留|PADDING"
  skip_reason: "填充/保留字段"
```

项目词典在前，默认词典在后；同 regex 项目优先。

## SKILL 设计要点

两个 skill 都遵循**对用户零 yaml 认知**的原则：

1. 自动探测 yaml 配置，不落盘展示给用户
2. AI 用 Read 工具读样本 Excel 做语义校验，确认探测是否合理
3. 只在校验可疑时用业务语言问 1-2 个简单问题（"表头在第几行？""哪一列是字段代码？"），永不让用户编 yaml
4. 汇报用业务语言（"N 个字段 / 高信心 X / 推测 Y / 跳过 W"），不提 `header_row`/`regex`/`config.yaml` 这些技术细节

详见 [.claude/skills/if-ingest/SKILL.md](./.claude/skills/if-ingest/SKILL.md) 和 [.claude/skills/if-map/SKILL.md](./.claude/skills/if-map/SKILL.md)。

## 关键设计决策

| 决策 | 替代方案 | 选择原因 |
|---|---|---|
| SQLite + JSONL 双存储 | 仅 JSONL / 仅 SQLite | JSONL 便于 git diff 和肉眼审阅；SQLite 做多维查询 |
| YAML 配置驱动 | 硬编码 / 纯自动探测 | YAML 兼顾灵活性和可调试；自动探测负责生成草稿，用户不需编辑 |
| Skill 自包含 `scripts/` 子目录 | 全局共享 scripts/ | 符合 Anthropic Agent Skills 约定；单个 skill 可整体复制到其他项目 |
| ext_*/sap_* 归一化 | 保留 src_*/target_* 相对语义 | 模板方向经常翻转，归一化让查询不关心方向 |
| 默认词典 + 项目词典合并 | 仅项目词典 / 仅默认词典 | 通用 SAP 语义（数量/重量/日期）跨项目一致；项目特殊规则可覆盖 |
| 推测类候选独立前缀 `[推测]` | 混在历史候选里 | 让用户一眼区分"历史验证过"和"AI 推测"，避免过度信任 |
| L2 上下文仅加分不独立召回 | L2 独立产生候选 | 历史版本曾因 L2 独立召回，让高频主键 VBAP.MATNR 刷到所有推测字段 |
| 产物 Excel 不改原文件 | 就地修改 | 原 .xls 不破坏；.xlsx 产物可二次编辑 |
| 下拉菜单列字符串 | 多列分别下拉 | 用户操作简单；`"VBAK.KUNNR（受注先）"` 一条字符串自解释 |

## 信心度分级算法

**直接命中**（origin=history）：
```
score = weighted_freq / total_weighted + (0.15 if ctx_struct_match else 0)
```
分档：
- score ≥ 0.85 + raw_freq > 1 → ★★★
- score ≥ 0.85 + raw_freq ≤ 1 → ★★（历史仅1次，需复核）
- score ≥ 0.6 → ★★
- score ≥ 0.3 → ★
- else → 需确认

**推测**（origin=speculate）：封顶 `★（推测）`，不论分数多高。这是重要保护：避免用户把 AI 推断当成历史验证过的结论。

## 已知限制

1. **.xls 转换依赖 libreoffice** — 没有 libreoffice 时 .xls 文件无法读取。解决：预先批量转 .xlsx。
2. **字段语义词汇表需本地化** — 对非日语项目（如中文/英文 spec）需要扩展 `field_semantics` 的同义词集合。
3. **小样本映射会过拟合** — 历史仅出现 1 次的映射，信心度上限 ★★（自动带"需复核"标记）。
4. **跨 SAP 模块推广** — 当前知识库聚焦 SD/LE（销售/交货），FICO/MM 等模块映射较少，推测质量会更弱，需要持续补充业务词典。
5. **复合字段识别只识别备注里的 "X桁+Y桁" 模式** — 其他复合模式（如"前3位XXX、后5位YYY"）未自动识别，需人工标注。

## 演进路径

- 字典外置化：把 `field_semantics` 也外置为 yaml（当前 hardcoded 在 `detect_schema.py`）
- 知识库 Embedding：为 ext_name/sap_name 生成向量，支持语义近邻查询（超越子串匹配）
- 多项目联合：跨项目共享"SAP 通用语义"层，每个项目保留自己的"外部系统特化"层
- 反馈闭环：用户在候选 Excel 里勾选的结果可回流到知识库，增量学习
