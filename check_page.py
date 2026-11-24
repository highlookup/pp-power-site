# -*- coding: utf-8 -*-
"""检查页面与数据是否自洽（index.html 内嵌时间戳 == data.json 的 generated）。

为什么需要：data.json 上传成功、index.html 上传失败时，若只比较 data.json，
会被判定「无变化」而跳过提交，导致页面长期停留在旧版本（2026-11-24 事故）。

用法：
    python check_page.py <index.html路径> <data.json路径>

退出码 0 表示自洽，1 表示不一致（需要重新提交）。
"""
import json
import re
import sys


def page_generated(path):
    """从 index.html 中提取内嵌的 DATA.generated"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return None
    m = re.search(r'"generated"\s*:\s*"([^"]*)"', text)
    return m.group(1) if m else None


def data_generated(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("generated")
    except Exception:
        return None


def main():
    if len(sys.argv) < 3:
        print("用法: python check_page.py <index.html> <data.json>")
        return 1
    pg, dt = page_generated(sys.argv[1]), data_generated(sys.argv[2])
    if pg is not None and pg == dt:
        print(f"页面与数据自洽（{dt}）")
        return 0
    print(f"页面与数据不一致：page={pg} data={dt} → 需要重新提交")
    return 1


if __name__ == "__main__":
    sys.exit(main())