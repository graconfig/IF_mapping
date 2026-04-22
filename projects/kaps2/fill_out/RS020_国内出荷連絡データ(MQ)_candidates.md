# 国内出荷連絡データ(MQ) — SAP 映射候选审阅

- 源文件: `RS020_国内出荷連絡データ(MQ).xls`
- IFID（推测）: RS020
- 字段总数: 24（跳过填充 1）
- 有候选 / 无候选: 11 / 12
- 生成: 2026-04-22 21:17

## 本书上下文聚集（各字段 Top-1 候选的 SAP 结构分布）
- `VBAP`: 3 字段
- `LIKP`: 2 字段
- `LIPS`: 2 字段
- `VBAK`: 1 字段
- `VBKD`: 1 字段
- `LIPS
LIPS`: 1 字段
- `MAKT`: 1 字段

---

## №1 | ファイルＩＤ | BFIL | Type=C Len=2 Byte=2 | 備考: 'R3'

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №2 | 出荷日 | DSYKDDD | Type=C Len=6 Byte=6 | 備考: YYMMDD

- [ ] **Top-1** 信心 0.24 — `LIKP.WADAT` (計画在庫移動日付)
  - 信号: ext_tech_exact×2, ext_name_exact×2
  - 历史 IF: IFZ9000037, IFZ9000101
- [ ] **Top-2** 信心 0.24 — `LIKP.WADAT_IST` (実在庫移動日付)
  - 信号: ext_tech_exact×2, ext_name_exact×2
  - 历史 IF: IFZ9000171, IFZ9000398
- [ ] **Top-3** 信心 0.12 — `EKET.EINDT` (明細納入期日)
  - 信号: ext_tech_exact×1, ext_name_exact×1
  - 历史 IF: IFZ9000102

---

## №3 | 出荷連絡No | BSYR | Type=C Len=8 Byte=8

- [ ] **Top-1** 信心 0.65 — `LIKP.VBELN` (出荷伝票)
  - 信号: ext_tech_exact×4, ext_name_norm(出荷連絡№)×3
  - 历史 IF: IFZ9000037, IFZ9000092, IFZ9000172, IFZ9000173
- [ ] **Top-2** 信心 0.35 — `EKKO.EBELN` (購買伝票)
  - 信号: ext_tech_exact×2, ext_name_norm(出荷連絡No.)×1, ext_name_norm(出荷連絡№)×1
  - 历史 IF: IFZ9000100, IFZ9000103

---

## №4 | 出荷連絡L# | BSYRGYO | Type=C Len=1 Byte=1

- [ ] **Top-1** 信心 1.00 — `LIPS.POSNR` (出荷明細)
  - 信号: ext_tech_exact×3
  - 历史 IF: IFZ9000037, IFZ9000172, IFZ9000173

---

## №5 | 出荷連絡枝番 | BSYKRENEDA | Type=C Len=3 Byte=3

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №6 | 受付No | BUKE | Type=C Len=8 Byte=8

- [ ] **Top-1** 信心 0.84 — `VBAK.VBELN` (販売伝票)
  - 信号: ext_name_norm(受付№)×6, ext_tech_exact×5
  - 历史 IF: IFZ9000015, IFZ9000026, IFZ9000100, IFZ9000172, IFZ9000173 …+1
- [ ] **Top-2** 信心 0.16 — `LIKP.VGBEL` (参照伝票)
  - 信号: ext_tech_exact×1, ext_name_norm(受付№)×1
  - 历史 IF: IFZ9000037

---

## №7 | 受付L# | BUKEGYO | Type=C Len=1 Byte=1

- [ ] **Top-1** 信心 1.00 — `VBAP.POSNR` (販売伝票明細)
  - 信号: ext_tech_exact×2
  - 历史 IF: IFZ9000172, IFZ9000173
  - 上下文+0.15（VBAP 在本书聚集 ×3）

---

## №8 | 便コード | BYUS | Type=C Len=2 Byte=2

- [ ] **Top-1** 信心 1.00 — `VBKD.VSART` (出荷タイプ)
  - 信号: ext_tech_exact×5
  - 历史 IF: IFZ9000100, IFZ9000102, IFZ9000172, IFZ9000173

---

## №9 | 運送会社コード | BUNS | Type=C Len=6 Byte=6

- [ ] **Top-1** 信心 1.00 — `LIPS.AESKD` (得意先設計変更ステータス)
  - 信号: ext_tech_exact×2, ext_name_exact×2
  - 历史 IF: IFZ9000172, IFZ9000173

---

## №10 | 重量 | SGYU | Type=C Len=7 Byte=7 | 備考: 符号なし
PIC'9999999'

- [ ] **Top-1** 信心 1.00 — `LIPS
LIPS.NTGEW
BRGEW` (正味重量
総重量)
  - 信号: ext_tech_exact×2, ext_name_exact×2
  - 历史 IF: IFZ9000172, IFZ9000173

---

## №11 | 口数 | SKUC | Type=C Len=3 Byte=3 | 備考: 符号なし　PIC'999'

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №12 | 品番 | BHIN | Type=C Len=10 Byte=10

- [ ] **Top-1** 信心 0.51 — `VBAP.MATNR` (品目コード)
  - 信号: ext_name_exact×6, ext_tech_exact×2
  - 历史 IF: IFZ9000003, IFZ9000015, IFZ9000025, IFZ9000026, IFZ9000098 …+1
  - 上下文+0.15（VBAP 在本书聚集 ×3）
- [ ] **Top-2** 信心 0.30 — `VBRP.MATNR` (品目コード)
  - 信号: ext_tech_exact×3, ext_name_exact×3
  - 历史 IF: IFZ9000089, IFZ9000172, IFZ9000173
- [ ] **Top-3** 信心 0.10 — `EBAN.MATNR` (品目コード)
  - 信号: ext_tech_exact×1, ext_name_exact×1
  - 历史 IF: IFZ9000167

---

## №13 | 品名 | NHINKN | Type=C Len=20 Byte=20

- [ ] **Top-1** 信心 0.94 — `MAKT.MAKTX` (品目テキスト)
  - 信号: ext_tech_exact×11, ext_name_exact×8
  - 历史 IF: IF0135, IFZ9000015, IFZ9000016, IFZ9000025, IFZ9000026 …+10
- [ ] **Top-2** 信心 0.21 — `VBAP.ARKTX` (受注明細のテキスト (短))
  - 信号: ext_tech_exact×1
  - 历史 IF: IFZ9000098
  - 上下文+0.15（VBAP 在本书聚集 ×3）

---

## №14 | 荷札№ | BNFD | Type=C Len=10 Byte=10 | 備考: MMDD+PC＋連番4桁

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №15 | 出荷連絡数 | SRSYK | Type=C Len=5 Byte=5

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №16 | 出荷連絡不足数 | SSYKRENFSK | Type=C Len=5 Byte=5

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №17 | 入出庫形態 | CNSKKTI | Type=C Len=3 Byte=3

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №18 | 入出庫連番 | BNSKRBN | Type=C Len=8 Byte=8 | 備考: B扱いはﾌﾞﾗﾝｸ

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №19 | ケース数 | SCAS | Type=C Len=3 Byte=3 | 備考: 符号なし　PIC'999'

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №20 | 荷集めボックスNo | BNSYBOX | Type=C Len=5 Byte=5

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №21 | 集約得意先納所 | BSYUTKUNOS | Type=C Len=9 Byte=9 | 備考: 得意先6桁+納所3桁

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №22 | メーカー略号 | BMEKRYG | Type=C Len=3 Byte=3 | 備考: 2017/10/04 追加

- [ ] **Top-1** 信心 1.00 — `VBAP.MATNR` (品目コード)
  - 信号: ext_name_exact×1
  - 历史 IF: IFZ9000025
  - 上下文+0.15（VBAP 在本书聚集 ×3）

---

## №23 | 品番（20桁） | BHIN20 | Type=C Len=20 Byte=20 | 備考: 2017/10/04 追加

**无合适候选** — 可能是接口元数据 / 透传字段，推测无需映射到 SAP 表

---

## №24 | 予備 | FIL1 | Type=C Len=2 Byte=2 | 備考: 25→2
2017/10/04 変更

*（填充字段，跳过映射）*

---
