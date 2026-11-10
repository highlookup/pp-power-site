---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'b030f6fe-957d-410f-b026-9aea215fac24'
  PropagateID: 'b030f6fe-957d-410f-b026-9aea215fac24'
  ReservedCode1: '75fd734c-3dc3-435d-8545-c5fbd95c6dc0'
  ReservedCode2: '75fd734c-3dc3-435d-8545-c5fbd95c6dc0'
---

# A股购买力顶底模型 · 月度监测站

基于 M2/GDP 购买力通道的 A 股顶底位置监测。每月 12 日自动更新上证月线数据与央行官方 M2 数据，重算模型并刷新本页。

## 模型

- 购买力比：`X = M2 月末余额(万亿) ÷ GDP 年化(万亿) × 10⁴`
- 顶线：`TOP = Kt × X + Bt`，由三轮流动性牛市顶部拟合（2007-10、2015-06、2026-05）
- 底线：`BOT = Kb × X + Bb`，由五轮历史大底拟合（2008-10、2013-06、2016-01、2019-01、2024-09）
- 通道位置：`(收盘 − 底线) ÷ (顶线 − 底线)`，≥90% 贴顶预警，≤15% 贴底机会

## 文件

| 文件 | 说明 |
|---|---|
| `build_site.py` | 拉取数据 → 计算模型 → 生成 `data.json` 与 `index.html` |
| `template.html` | 页面模板（含样式与图表渲染逻辑） |
| `data.json` | 月度数据与模型参数 |
| `index.html` | 生成的自包含页面（GitHub Pages 入口） |
| `.github/workflows/update.yml` | 每月 12 日自动运行 |

## 本地运行

```bash
python build_site.py
```

无需安装第三方依赖，仅用标准库。生成后打开 `index.html` 即可。

## 数据来源

- 上证指数月线：腾讯行情
- M2 供应量：中国人民银行（经东方财富宏观库）
- GDP：国家统计局年度值，按月线性插值年化

## 维护

每年 1 月统计局公布上年 GDP 后，需在 `build_site.py` 顶部的 `GDP_Y` 字典中补充新年度数值（单位：万亿元）。

## 说明

本页为模型研究结果，不构成投资建议。模型为公开资料中相关思想的公式重构，原文未披露计算方法。

> AI生成