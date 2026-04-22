# 接口字段映射知识库

这个知识库把 `历史设计书/` 下的 SAP 接口设计书 (インタフェース項目定義書)
中 `項目マッピング(受信)` / `項目マッピング(返信)` 两张工作表，抽成结构化数据，
支持"新字段 → SAP 字段"的反查。

## 目录

```
knowledge/
  field_mappings.jsonl  # 主数据：每行 = 一条字段映射记录
  ifs.db                # SQLite 索引库（由 JSONL 构建）
  README.md             # 本文件
scripts/
  extract_mapping.py    # 从 .xlsx 抽取字段映射
  build_index.py        # JSONL → SQLite
  match_field.py        # 字段匹配查询
```

## 数据模型

每条映射记录 (`field_mappings.jsonl` 中一行) 的核心字段：

| 字段 | 说明 |
|---|---|
| `ifid` / `if_name` | IF 编号与名称（如 `IFZ9000003` / `無償受注連携`） |
| `direction` | `inbound` = 外部→SAP（受信表）；`outbound` = SAP→外部（返信表） |
| `external_no` / `external_name` / `external_tech_name` / `external_length` / `external_attr` | 外部系统侧字段 |
| `sap_struct` / `sap_tech_name` | SAP 表名 + 字段名（如 `VBAK.KUNNR`） |
| `sap_name` / `sap_length` / `sap_attr` | SAP 字段日文名/长度/类型 |
| `conversion_spec` | 変換仕様（从外部到 SAP 的转换规则） |
| `io` | I / O / I/O |
| `current_spec` | 現行編集仕様（参考信息） |
| `has_sap_mapping` | 是否有明确 SAP 字段映射（布尔值） |
| `source_file` | 来源 Excel 文件名 |

**SAP 侧识别**：不依赖表头文字（模板残留有误导），而是看"構造"列是否像
SAP 表名（大写字母+数字+下划线，如 `VBAK`、`ADRC`、`PRCD_ELEMENTS`）。

## 常用命令

### 1. 重建知识库（从原始 Excel）

```bash
# 抽取所有设计书 → JSONL
python3 scripts/extract_mapping.py 历史设计书/*.xlsx -o knowledge/field_mappings.jsonl

# 导入 SQLite 索引
python3 scripts/build_index.py
```

### 2. 增量新增一份设计书

```bash
# 追加方式抽取（--append 不会清空已有数据）
python3 scripts/extract_mapping.py 历史设计书/新的设计书.xlsx \
    -o knowledge/field_mappings.jsonl --append

# 重建索引
python3 scripts/build_index.py
```

### 3. 查询：给一个新字段，找对应 SAP 字段

```bash
# 按项目名称（日文字段名）
python3 scripts/match_field.py --name 得意先コード

# 按技术名称 / SAP 字段反查
python3 scripts/match_field.py --tech KUNNR

# 加长度约束、限定在某个 IFID
python3 scripts/match_field.py --name 品番 --length 10 --ifid IFZ9000003

# 只看受信方向
python3 scripts/match_field.py --name 納所 --direction inbound
```

输出会给出 Top-N 候选，包含：
- 匹配得分与命中原因 (`ext_name=exact` / `sap_tech⊇q` 等)
- 来源 IFID / IF 名称
- SAP 侧的 `表.字段`、日文名、长度、类型
- 変換仕様、現行仕様
- 同一字段在其他 IF 中也出现过的 IFID 列表

## Pilot 范围

当前只导入了 pilot：`IFZ9000003 無償受注連携`，共 80 条记录（受信 40 / 返信 40），
其中 26 条有明确 SAP 字段映射。用到的 SAP 表：
`VBAK`, `VBAP`, `VBEP`, `VBKD`, `VBPA`, `ADRC`, `MAKT`, `MBEW`, `PRCD_ELEMENTS`。

## 批量入全量 44 份设计书

```bash
python3 scripts/extract_mapping.py 历史设计书/*.xlsx -o knowledge/field_mappings.jsonl
python3 scripts/build_index.py
```

批处理时请关注 stderr 输出的 `[error]` 行（模板/版本差异可能导致个别文件解析异常）。
