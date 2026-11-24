# -*- coding: utf-8 -*-
"""收盘时间窗口检查：北京时间早于 15:30 时不允许提交。

为什么需要：腾讯月线接口对「当月未完成的 K 线」，close 字段返回的是
盘中最新价而非收盘价。实测 2026-11-24 上午 10:37 运行时取到 3569.23
（盘中价），而当日真实收盘是 3548.37；若此次写入被当作最终结果，
页面会长期显示错误价格。

GitHub 免费版 schedule 存在 3~9 小时延迟（实测曾延迟至次日凌晨/上午），
因此必须在提交前加这道门槛，无论调度何时漂移都不会写入盘中价。

退出码 0 = 已过收盘窗口，允许提交；1 = 未到时间，跳过提交。
"""
import sys
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))

# 15:30 之后才允许提交：A股 15:00 收盘，留 30 分钟给数据源更新
ALLOW_FROM_MIN = 15 * 60 + 30


def main():
    now = datetime.now(BJ)
    minutes = now.hour * 60 + now.minute
    if minutes < ALLOW_FROM_MIN:
        print(f"北京时间 {now:%H:%M} 早于 15:30，当日收盘数据尚未确定，跳过提交")
        return 1
    print(f"北京时间 {now:%H:%M} 已过 15:30 收盘窗口，允许提交")
    return 0


if __name__ == "__main__":
    sys.exit(main())