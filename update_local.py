# -*- coding: utf-8 -*-
"""
购买力顶底模型站点 · 本机每日更新（Windows 计划任务 16:30 调用）

流程：
  1. 运行 build_site.py 重新生成 data.json / index.html
  2. 与远程比对，无变化则直接退出
  3. 有变化则通过 GitHub contents API 上传（绕开 git push 网络不稳）
  4. 上传成功后把本地工作区对齐到远程，避免长期落后

日志写入同目录 update_local.log
"""
import base64
import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = "highlookup/pp-power-site"
BRANCH = "main"
FILES = ["data.json", "index.html"]
LOG = os.path.join(ROOT, "update_local.log")


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def gh(args, inp=None):
    r = subprocess.run(["gh"] + args, capture_output=True, text=True,
                       input=inp, cwd=ROOT)
    return r.returncode, r.stdout, r.stderr


def git(*args):
    r = subprocess.run(["git"] + list(args), capture_output=True, text=True, cwd=ROOT)
    return r.returncode, r.stdout, r.stderr


def build():
    r = subprocess.run([sys.executable, "build_site.py"], capture_output=True,
                       text=True, cwd=ROOT, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    for line in out.splitlines():
        if any(k in line for k in ("最新", "位置", "已生成", "Traceback", "Error", "错误")):
            log("  " + line.strip())
    return r.returncode == 0


def remote_data():
    """取远程 data.json 并解析（失败返回 None）"""
    rc, out, err = gh(["api", f"repos/{REPO}/contents/data.json?ref={BRANCH}", "--jq", ".content"])
    if rc != 0 or not out.strip():
        return None
    try:
        raw = base64.b64decode(out.strip()).decode("utf-8")
        return json.loads(raw)
    except Exception:
        return None


def substantive(data):
    """剔除时间戳后的实质内容，用于判断是否真有变化"""
    if not isinstance(data, dict):
        return data
    d = dict(data)
    d.pop("generated", None)
    return d


def changed_files():
    """返回相对远程有实质变化的文件列表；仅时间戳变化视为无变化"""
    rc, _, err = git("fetch", "origin", BRANCH)
    if rc != 0:
        log(f"  fetch 失败（继续按全量处理）: {err.strip()[:120]}")
        return FILES

    local_path = os.path.join(ROOT, "data.json")
    try:
        with open(local_path, encoding="utf-8") as f:
            local = json.load(f)
    except Exception:
        return FILES

    remote = remote_data()
    if remote is None:
        log("  读取远程 data.json 失败，按有变化处理")
        return FILES

    if substantive(local) == substantive(remote):
        return []
    return FILES


def upload(path):
    full = os.path.join(ROOT, path)
    with open(full, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    payload = {"message": f"每日数据更新 {datetime.now():%Y-%m-%d}", "content": content, "branch": BRANCH}
    rc, out, err = gh(["api", f"repos/{REPO}/contents/{path}?ref={BRANCH}", "--jq", ".sha"])
    if rc == 0 and out.strip():
        payload["sha"] = out.strip()
    rc, out, err = gh(["api", "-X", "PUT", f"repos/{REPO}/contents/{path}", "--input", "-"],
                      inp=json.dumps(payload))
    if rc != 0:
        log(f"  上传失败 {path}: {err.strip()[:200]}")
        return False
    log(f"  已上传 {path}")
    return True


def align():
    """本地对齐远程：丢弃已上传的构建改动后快进（先重新 fetch，确保拿到刚上传的提交）"""
    git("checkout", "--", *FILES)
    rc, _, err = git("fetch", "origin", BRANCH)
    if rc != 0:
        log(f"  对齐前 fetch 失败: {err.strip()[:120]}")
        return
    rc, out, err = git("merge", "--ff-only", f"origin/{BRANCH}")
    if rc != 0:
        log(f"  本地对齐失败（不影响线上）: {(err or out).strip()[:150]}")
    else:
        log("  本地已对齐远程")


def main():
    log("=== 开始每日更新 ===")
    if not build():
        log("构建失败，终止")
        return 1

    todo = changed_files()
    if not todo:
        log("数据无实质变化，无需推送")
        align()
        return 0

    log(f"有变化文件: {', '.join(todo)}")
    if not all(upload(p) for p in todo):
        log("部分文件上传失败")
        return 1

    align()
    log("=== 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())