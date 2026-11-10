# -*- coding: utf-8 -*-
"""
购买力顶底模型 · 公开站生成器
拉取上证月线 + 官方M2 → 计算购买力通道 → 生成 index.html（自包含）+ data.json

用法：python build_site.py
"""
import json
import urllib.request
from datetime import datetime
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
HERE = Path(__file__).resolve().parent

# ---------------- GDP 年度值（万亿元） ----------------
GDP_Y = {
    1999: 8.967, 2000: 9.921, 2001: 10.966, 2002: 12.033, 2003: 13.742,
    2004: 16.184, 2005: 18.732, 2006: 21.943, 2007: 27.023, 2008: 31.952,
    2009: 34.909, 2010: 41.212, 2011: 48.794, 2012: 53.861, 2013: 59.296,
    2014: 64.356, 2015: 68.886, 2016: 74.640, 2017: 83.204, 2018: 91.928,
    2019: 98.652, 2020: 101.357, 2021: 114.924, 2022: 120.472, 2023: 129.427,
    2024: 134.807, 2025: 140.188,
}
GDP_EST = {2026: 147.0}

# ---------------- M2 年末官方值（万亿元，央行《金融统计数据报告》） ----------------
# 东财宏观接口只提供 2008-01 以后的月度值，2000-2007 年用年末官方值几何插值补全
M2_EOP = {
    1999: 11.76, 2000: 13.46, 2001: 15.83, 2002: 18.32, 2003: 21.92,
    2004: 25.01, 2005: 29.88, 2006: 34.56, 2007: 40.34, 2008: 47.52,
    2009: 60.62, 2010: 72.58, 2011: 85.16, 2012: 97.42, 2013: 110.65,
    2014: 122.84, 2015: 139.23, 2016: 155.01, 2017: 167.68, 2018: 182.67,
    2019: 198.65, 2020: 218.68, 2021: 238.29, 2022: 266.43, 2023: 292.27,
    2024: 313.50, 2025: 338.10, 2026: 364.11,
}
# 2008 年以前可得的零散官方月度值（央行公告），优先于插值
M2_OFF_EARLY = {
    "2005-06": 27.59, "2007-10": 39.42,
}

# ---------------- 模型锚点 ----------------
# 顶线锚点：三轮流动性牛市顶（月份, 指数）
TOP_ANCHORS = [("2007-10", 6124.04), ("2015-06", 5178.19), ("2026-05", 4170.0)]
# 底线锚点：五轮历史大底（月份, 指数）
BOT_ANCHORS = [("2008-10", 1664.93), ("2013-06", 1849.65), ("2016-01", 2638.30),
               ("2019-01", 2440.91), ("2024-09", 2689.70)]


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_sse_months(start="1999-01-01"):
    """腾讯上证月线：{YYYY-MM: (high, low, close)}"""
    end = datetime.now().strftime("%Y-%m-%d")
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param=sh000001,month,{start},{end},400,qfq")
    j = http_json(url)
    data = j["data"]["sh000001"]
    arr = data.get("qfqmonth") or data.get("month")
    out = {}
    for row in arr:
        d = row[0]
        c, h, l = float(row[2]), float(row[3]), float(row[4])
        out[d[:7]] = (h, l, c)
    return out


def fetch_m2_official():
    """东财宏观接口（央行口径）：{YYYY-MM: M2余额(万亿元)}"""
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "reportName=RPT_ECONOMY_CURRENCY_SUPPLY&columns=ALL"
           "&pageSize=240&sortColumns=REPORT_DATE&sortTypes=-1")
    j = http_json(url)
    out = {}
    for it in j["result"]["data"]:
        m = it["REPORT_DATE"][:7]
        v = it.get("BASIC_CURRENCY")
        if v is not None:
            out[m] = round(v / 10000.0, 2)
    return out


def gdp_at(y, m):
    gy = GDP_Y.get(y) or GDP_EST.get(y)
    prev = GDP_Y.get(y - 1) or GDP_EST.get(y - 1)
    if gy is None:
        last = max(list(GDP_Y) + list(GDP_EST))
        base = GDP_Y.get(last) or GDP_EST.get(last)
        n = y - last
        gy = base * 1.05 ** n
        prev = base * 1.05 ** (n - 1)
    return prev + (gy - prev) * m / 12.0


def geo(v0, v1, k, n):
    return v0 * (v1 / v0) ** (k / n)


def ols(pts):
    n = len(pts)
    sx = sum(q[0] for q in pts)
    sy = sum(q[1] for q in pts)
    sxx = sum(q[0] ** 2 for q in pts)
    sxy = sum(a * b for a, b in pts)
    k = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    return k, (sy - k * sx) / n


def build_rows(sse, m2off):
    """生成 2000-01 至今的月度行

    未公布月份的 M2 处理：
      1) 前后均有官方值 -> 几何插值
      2) 只有历史官方值   -> 按最近12个月同比增速几何外推（避免 X 冻结导致顶线漂移）
    """
    rows = []
    months = sorted([d for d in sse if d >= "2000-01"])
    last_off = max(m2off)

    def eop_interp(d):
        """用年末官方 M2 做几何插值（2008 年以前的补全方式）"""
        y, m = int(d[:4]), int(d[5:7])
        v0 = M2_EOP.get(y - 1)
        v1 = M2_EOP.get(y)
        if v0 and v1:
            return round(geo(v0, v1, m, 12), 2), "年末插值"
        if v1 and m == 12:
            return round(v1, 2), "年末插值"
        return None, None

    # 最近12个月同比增速（用于外推）
    def yoy_growth():
        ly, lm = int(last_off[:4]), int(last_off[5:7])
        prev_key = f"{ly-1}-{lm:02d}"
        if prev_key in m2off and m2off[prev_key] > 0:
            return m2off[last_off] / m2off[prev_key]
        return 1.08

    grow = yoy_growth()

    for d in months:
        h, l, c = sse[d]
        if d in m2off:
            m2v, tag = m2off[d], "官方"
        elif d in M2_OFF_EARLY:
            m2v, tag = M2_OFF_EARLY[d], "官方"
        else:
            prev_off = max([k for k in m2off if k < d], default=None)
            nxt_off = min([k for k in m2off if k > d], default=None)
            if prev_off and nxt_off:
                p0 = datetime.strptime(prev_off + "-01", "%Y-%m-%d")
                p1 = datetime.strptime(nxt_off + "-01", "%Y-%m-%d")
                cur = datetime.strptime(d + "-01", "%Y-%m-%d")
                w = (cur - p0).days / max((p1 - p0).days, 1)
                m2v = geo(m2off[prev_off], m2off[nxt_off], w * 12, 12)
                tag = "插值"
            elif prev_off:
                # 距最新官方值几个月，按同比增速折算
                ly, lm = int(last_off[:4]), int(last_off[5:7])
                dy = int(d[:4]) - ly
                dm = int(d[5:7]) - lm
                steps = dy * 12 + dm
                m2v = m2off[prev_off] * (grow ** (steps / 12.0))
                tag = "外推"
            else:
                # 早于接口覆盖范围：用年末官方值插值
                m2v, tag = eop_interp(d)
                if m2v is None:
                    continue
        y, m = int(d[:4]), int(d[5:7])
        gdpv = gdp_at(y, m)
        x = m2v / gdpv * 10000
        rows.append({"m": d, "h": round(h, 2), "l": round(l, 2), "c": round(c, 2),
                     "m2": round(m2v, 2), "gdp": round(gdpv, 4),
                     "x": round(x, 2), "t": tag})
    return rows


def main():
    print("[1/4] 拉取上证月线 ...")
    sse = fetch_sse_months()
    print(f"      {len(sse)} 个月，最新 {max(sse)}")
    print("[2/4] 拉取官方 M2 ...")
    m2off = fetch_m2_official()
    print(f"      {len(m2off)} 个月官方值，最新 {max(m2off)} = {m2off[max(m2off)]} 万亿")

    print("[3/4] 计算模型 ...")
    rows = build_rows(sse, m2off)
    xmap = {r["m"]: r["x"] for r in rows}

    top_pts = [(xmap[m], p) for m, p in TOP_ANCHORS if m in xmap]
    bot_pts = [(xmap[m], p) for m, p in BOT_ANCHORS if m in xmap]
    Kt, Bt = ols(top_pts)
    Kb, Bb = ols(bot_pts)

    for r in rows:
        top = Kt * r["x"] + Bt
        bot = Kb * r["x"] + Bb
        r["top"] = round(top, 1)
        r["bot"] = round(bot, 1)
        r["pos"] = round((r["c"] - bot) / (top - bot), 4) if top > bot else None
        r["posH"] = round((r["h"] - bot) / (top - bot), 4) if top > bot else None
        r["posL"] = round((r["l"] - bot) / (top - bot), 4) if top > bot else None

    last = rows[-1]
    pos = last["pos"]
    if pos >= 0.9:
        zone = "贴顶 · 顶部区"
    elif pos >= 0.7:
        zone = "上部区"
    elif pos >= 0.3:
        zone = "中部区"
    elif pos >= 0.15:
        zone = "下部区"
    else:
        zone = "贴底 · 底部区"

    prev = rows[-2] if len(rows) > 1 else None
    trend = ""
    if prev and prev["pos"] is not None:
        dp = pos - prev["pos"]
        if dp > 0.05:
            trend = "较上月上行"
        elif dp < -0.05:
            trend = "较上月下行"
        else:
            trend = "较上月基本持平"

    incomplete = (last["m"] == datetime.now().strftime("%Y-%m"))

    data = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "incomplete": incomplete,
        "params": {"Kt": round(Kt, 6), "Bt": round(Bt, 4),
                   "Kb": round(Kb, 6), "Bb": round(Bb, 4)},
        "state": {"month": last["m"], "close": last["c"], "high": last["h"],
                  "low": last["l"], "x": last["x"], "top": last["top"],
                  "bot": last["bot"], "pos": pos, "zone": zone, "trend": trend,
                  "tag": last["t"] + ("· 未完月" if incomplete else "")},
        "anchors": {"top": TOP_ANCHORS, "bot": BOT_ANCHORS},
        "rows": rows,
        "gdpNote": "GDP 2026 为估算值（147.0 万亿），国家统计局初步核算值公布后更新",
    }

    (HERE / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print("[4/4] 生成本月结论 ...")
    print(f"      {last['m']} 收盘 {last['c']:.0f} | 顶线 {last['top']:.0f} | "
          f"底线 {last['bot']:.0f} | 位置 {pos*100:.0f}%（{zone}）")

    html = (HERE / "template.html").read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False,
                                                       separators=(",", ":")))
    (HERE / "index.html").write_text(html, encoding="utf-8")
    print(f"      已生成 index.html ({len(html)/1024:.1f} KB)")


if __name__ == "__main__":
    main()