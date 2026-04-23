# IF Mapping — SAP 接口字段映射助手

从历史 SAP 接口设计书中提炼字段映射知识，为新的空白接口设计书自动推荐 SAP 字段候选，产出带下拉菜单的可审阅 Excel。

## 做什么

接口设计书（IF 定义书 / spec）里，外部系统字段填好了，SAP 侧往往是一大片空白。这个项目：

1. 读一批历史设计书（已完成映射的 Excel），把每条 `外部字段 → SAP 字段` 抽出来建成知识库。
2. 给一份空白设计书时，为每个外部字段从知识库推荐 **Top-3 SAP 表和字段**，直接以下拉菜单回填到 Excel，附信心度和业务化说明。

## 目录结构

```
IF_mapping/
├── projects/
│   └── kaps2/                          # 一个项目一个目录
│       ├── config.yaml                 # 项目配置（自动探测生成，对用户透明）
│       ├── business_dict.yaml          # 项目特有业务词典（可选）
│       ├── sources/                    # 参考文档（历史接口设计书 xlsx）
│       ├── knowledge/                  # 知识库产物
│       │   ├── field_mappings.jsonl   # 字段映射主库
│       │   ├── ifs.db                 # SQLite 索引
│       │   └── extract_report.md      # 抽取统计
│       └── fill_out/                   # 空白设计书 + 产物
│           ├── RS020_xxx.xls          # 输入
│           ├── RS020_xxx.schema.yaml  # 输入格式（自动探测）
│           └── RS020_xxx_候选.xlsx    # 产物（带下拉、信心、说明）
└── .claude/skills/
    ├── if-ingest/                      # 摄取参考文档建知识库
    │   ├── SKILL.md
    │   └── scripts/
    │       ├── detect_schema.py       # 参考文档格式自动探测
    │       ├── extract_mapping.py     # 单文件字段映射抽取
    │       └── build_index.py         # 批量建 jsonl + sqlite
    └── if-map/                         # 空白设计书回填
        ├── SKILL.md
        └── scripts/
            ├── detect_schema.py       # 空白设计书格式自动探测
            ├── fill_book.py           # 查库+推测+复合字段，产出候选 xlsx
            └── business_dict.default.yaml  # 跨项目默认业务词典
```

## 快速开始

### 安装依赖

```bash
pip install --user openpyxl pyyaml
# .xls 文件需要 libreoffice 做转换
# Ubuntu: sudo apt-get install libreoffice
```

### 使用方式一：通过 Claude Code skill（推荐）

安装本项目后，在 Claude Code 里用自然语言触发：

```
# 摄取历史设计书建知识库
"摄取 projects/kaps2/sources/ 这个目录的参考文档，项目叫 kaps2"
→ 触发 if-ingest skill

# 映射新的空白设计书
"把这份 RS020_国内出荷連絡データ(MQ).xls 映射到 SAP"
→ 触发 if-map skill
```

Skill 会自动探测文档格式、建库、回填，用业务语言报告结果，遇到不确定的地方才用简单问题问你（不让你碰 yaml）。

### 使用方式二：直接命令行

```bash
# 1. 摄取参考文档建知识库
python3 .claude/skills/if-ingest/scripts/detect_schema.py \
    <代表性样本.xlsx> --project kaps2 --out projects/kaps2/config.yaml
python3 .claude/skills/if-ingest/scripts/build_index.py --project kaps2

# 2. 回填空白设计书
python3 .claude/skills/if-map/scripts/detect_schema.py \
    projects/kaps2/fill_out/新接口.xls \
    --out projects/kaps2/fill_out/新接口.schema.yaml
python3 .claude/skills/if-map/scripts/fill_book.py \
    --project kaps2 projects/kaps2/fill_out/新接口.xls
```

产物：`projects/kaps2/fill_out/新接口_候选.xlsx`，在 Excel 里打开看 **推奨 SAP 字段 / 信心 / 備考** 三列。

## 产物 Excel 的信心度

| 标签 | 含义 | 建议 |
|---|---|---|
| ★★★ | 历史一致映射（≥85% 频次）| 直接采纳 |
| ★★ | 历史主导候选 + 备选 | 复核后采纳 |
| ★★（历史仅1次，需复核）| 高频次但样本少 | 人工确认 |
| ★ | 并列候选 / 弱主导 | 结合业务判断 |
| 需确认 | 多候选频次相近 | 根据业务语义选 |
| ★（推测）| 无历史映射，推测而来 | 必须复核 |
| 复合字段 | 已自动拆成多个子字段 | 确认每个子字段 |
| — | 无候选或填充字段 | 接口内部字段无需映射 |

## 当前知识库规模（KAPS2 项目）

- 44 份历史设计书 → 2150 条字段映射
- 覆盖 72 种 SAP 构造（VBAK/VBAP/LIKP/LIPS/VBRK/VBRP/MARA/MAKT/ADRC/VTTK/RBKP …）
- 19 个对向系统（K-Warranty / SPI / KWINC2 / A-PIKO / DOS / MDOS / 全農 / 海外販社 …）
- 主要业务域：销售、出荷、发票、物料、交货

## 扩展到新项目

```bash
mkdir -p projects/<新项目名>/{knowledge,fill_out}
ln -s /path/to/reference_docs projects/<新项目名>/sources
python3 .claude/skills/if-ingest/scripts/detect_schema.py \
    projects/<新项目名>/sources/<样本>.xlsx \
    --project <新项目名> \
    --out projects/<新项目名>/config.yaml
python3 .claude/skills/if-ingest/scripts/build_index.py --project <新项目名>
```

自动探测 + 跨项目默认业务词典（`scripts/business_dict.default.yaml`）通常够用。若某业务域有特殊映射规则，在 `projects/<新项目名>/business_dict.yaml` 加条目即可（覆盖默认）。

## 详细设计

见 [DESIGN.md](./DESIGN.md)。

## 许可

内部项目。
