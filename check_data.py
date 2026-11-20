# -*- coding: utf-8 -*-
"""比较构建产物与线上已提交版本的实质内容（剔除 generated 时间戳）。

用法：
    python check_data.py <线上版本json路径> <本地json路径>

退出码 0 表示无需更新，1 表示有实质变化。
"""
import json
import sys


def sub(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    if isinstance(d, dict):
        d.pop("generated", None)
    return d


def main():
    if len(sys.argv) < 3:
        print("用法: python check_data.py <remote.json> <local.json>")
        return 1
    a = sub(sys.argv[1])
    b = sub(sys.argv[2])
    if a is None or b is None:
        print("读取失败，按有变化处理")
        return 1
    changed = a != b
    print("实质内容有变化" if changed else "实质内容一致")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())