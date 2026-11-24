# -*- coding: utf-8 -*-
"""
购买力顶底模型站点 · 本机每日更新（Windows 计划任务调用）

设计要点（针对「睡眠/关机导致错过触发」的场景）：
  1. 计划任务在 16:30—23:30 之间每 30 分钟重复触发一次，任一次成功即算完成。
  2. 距上次成功更新不足 MIN_GAP_MIN 分钟 → 秒退（幂等，避免重复刷 GitHub）。
  3. 未到今日最早更新时间（16:30）→ 秒退（避免早上或无意义触发）。
  4. 只有「确认线上已是今天的数据」才写成功标记；否则下次触发会继续补跑。

流程：
  1. 运行 build_site.py 重新生成 data.json / index.html
  2. 读取远程 data.json，若线上已是今天更新的、且实质内容一致 → 记成功并退出
  3. 有实质变化则通过 GitHub contents API 上传（绕开 git push 网络不稳）
  4. 上传成功后重新 fetch 校验线上时间戳，确认成功才写标记

日志写入同目录 update_local.log
"""
import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = "highlookup/pp-power-site"
BRANCH = "main"
FILES = ["data.json", "index.html"]
LOG = os.path.join(ROOT, "update_local.log")
STATE = os.path.join(ROOT, "update_state.json")

EARLIEST_HOUR = 16      # 收盘后时间点：此刻之后的成功更新才算「当日收盘已采集」
EARLIEST_MIN = 30

# ---- 本机降级为「纯兜底」----
# 主更新由云端负责（cron-job.org 16:30/18:30/20:30 + GitHub cron 多时段）。
# 本机只在 FALLBACK_HOUR 之后才出手，此时云端三次触发已全部跑完、
# 若仍未上线则说明云端链路确实挂了，由本机补上。
# 好处：正常情况本机只是「查一下就退」（几秒），不会与云端抢跑产生重复提交/409。
FALLBACK_HOUR = 21
FALLBACK_MIN = 0


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(d):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"  写状态文件失败: {e}")


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


def remote_index_generated():
    """取远程 index.html 内嵌的 generated 时间戳（失败返回 None）

    为什么要单独校验：data.json 上传成功、index.html 上传失败时，若只看
    data.json 会误判为「已完成」，导致页面长期停留在旧版本（11-24 事故）。
    """
    rc, out, err = gh(["api", f"repos/{REPO}/contents/index.html?ref={BRANCH}",
                       "--jq", ".content"])
    if rc != 0 or not out.strip():
        return None
    try:
        raw = base64.b64decode(out.strip()).decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r'"generated"\s*:\s*"([^"]*)"', raw)
    return m.group(1) if m else None


def substantive(data):
    """剔除时间戳后的实质内容，用于判断是否真有变化"""
    if not isinstance(data, dict):
        return data
    d = dict(data)
    d.pop("generated", None)
    return d


def target_date():
    """本次更新应覆盖的交易日（用于判断是否已采到最新收盘）。

    规则：
      - 16:30 之后 → 目标就是今天（今天已收盘）
      - 16:30 之前 → 目标是昨天（今天的收盘还没出来，不应把今天当已采集）
    这样即使电脑在 16:30 睡着、次日早上才唤醒补跑，也仍会补采昨天收盘的数据。
    """
    now = datetime.now()
    if (now.hour, now.minute) >= (EARLIEST_HOUR, EARLIEST_MIN):
        return now.strftime("%Y-%m-%d")
    return (now - timedelta(days=1)).strftime("%Y-%m-%d")


def online_ok():
    """线上是否已经是目标交易日的最新数据（页面与数据自洽）。

    这是降级为纯兜底后的唯一判断依据：不依赖本地 update_state.json，
    因为云端更新成功时根本不会写本地状态文件。只要线上对了就说明
    「某条链路（云端或本机）已经成功」，本机无需再做任何事。
    """
    remote = remote_data()
    if remote is None or not remote_is_target(remote):
        return False
    r_gen = remote_index_generated()
    return bool(r_gen) and r_gen == remote.get("generated")


def remote_is_target(remote):
    """远程数据是否是目标交易日的数据（按 generated 日期前缀判断）"""
    if not remote:
        return False
    g = remote.get("generated") or ""
    return g.startswith(target_date())


def upload(path, tries=3):
    full = os.path.join(ROOT, path)
    with open(full, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    last = ""
    for i in range(1, tries + 1):
        # 每次都重取 sha，避免上一次失败/并发导致 sha 过期
        payload = {"message": f"每日数据更新 {datetime.now():%Y-%m-%d}",
                   "content": content, "branch": BRANCH}
        rc, out, err = gh(["api", f"repos/{REPO}/contents/{path}?ref={BRANCH}", "--jq", ".sha"])
        if rc == 0 and out.strip():
            payload["sha"] = out.strip()
        rc, out, err = gh(["api", "-X", "PUT", f"repos/{REPO}/contents/{path}",
                           "--input", "-"], inp=json.dumps(payload))
        if rc == 0:
            log(f"  已上传 {path}")
            return True
        last = (err or out or "").strip()[:200] or f"exit={rc}"
        log(f"  上传失败 {path}（第 {i}/{tries} 次）: {last}")
        if i < tries:
            time.sleep(3 * i)
    log(f"  {path} 最终上传失败: {last}")
    return False


def align():
    """本地对齐远程：丢弃已上传的构建改动后快进"""
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
    force = "--force" in sys.argv
    now = datetime.now()

    if not force:
        # 兜底时段门槛：云端 16:30/18:30/20:30 三次触发跑完之前本机不出手，
        # 避免与云端抢跑。只有 21:00 之后云端仍未上线，才由本机补。
        if (now.hour, now.minute) < (FALLBACK_HOUR, FALLBACK_MIN):
            log(f"{now:%H:%M} 未到兜底时段（{FALLBACK_HOUR}:{FALLBACK_MIN:02d}），"
                f"云端负责更新，本机跳过")
            return 0
        # 线上已就绪（云端已成功）→ 本机无需动作
        if online_ok():
            log(f"线上已是目标交易日 {target_date()} 的数据，云端已成功，本机无需补跑")
            return 0
        log(f"线上仍不是目标交易日 {target_date()} 的数据 → 云端可能失败，本机接手兜底")

    log(f"=== 开始每日更新（目标交易日 {target_date()}）===")
    if not build():
        log("构建失败，终止")
        return 1

    try:
        with open(os.path.join(ROOT, "data.json"), encoding="utf-8") as f:
            local = json.load(f)
    except Exception as e:
        log(f"读取本地 data.json 失败: {e}")
        return 1

    remote = remote_data()
    r_gen = remote_index_generated()
    # 页面是否与远程数据自洽：只比数据与页面彼此是否一致，
    # 不比本地构楚值。本地与云端完全可能相差一分钟，比本地会误判为「未同步」而反复上传。
    r_data_gen = (remote or {}).get("generated")
    page_ok = bool(r_gen) and r_gen == r_data_gen

    if (remote is not None and substantive(local) == substantive(remote)
            and remote_is_target(remote) and page_ok):
        log(f"线上已是目标交易日 {target_date()} 的最新数据（数据与页面自洽）")
        save_state({"last_success": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "done_for": target_date(),
                    "note": "already-fresh"})
        align()
        return 0

    if (remote is not None and substantive(local) == substantive(remote)
            and remote_is_target(remote) and not page_ok):
        # 数据已正确、仅页面掉队：只补页面，避免无意义的 data.json 空提交
        log(f"数据已就绪但页面掉队（data={r_data_gen}，page={r_gen}）→ 仅补传 index.html")
        if not upload("index.html"):
            log("页面补传失败（下次触发会重试）")
            return 1
        v_gen = remote_index_generated()
        if remote_is_target(remote_data()) and v_gen == r_data_gen:
            log("已确认页面与数据一致")
            save_state({"last_success": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "done_for": target_date(),
                        "note": "page-only"})
        else:
            log(f"警告：页面补传后仍未自洽（page={v_gen}），保持未完成以便重试")
        align()
        log("=== 完成 ===")
        return 0

    log("有实质变化，开始上传 data.json / index.html")
    ok = True
    for p in FILES:
        if not upload(p):
            ok = False
    if not ok:
        log("部分文件上传失败（下次触发会重试）")
        return 1

    # 上传后重新校验：远程数据是目标交易日，且页面与数据自洽
    verify = remote_data()
    v_gen = remote_index_generated()
    v_data_gen = (verify or {}).get("generated")
    if remote_is_target(verify) and v_gen and v_gen == v_data_gen:
        log(f"已确认线上为目标交易日 {target_date()} 的数据（数据={v_data_gen}，页面={v_gen}）")
        save_state({"last_success": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "done_for": target_date(),
                    "note": "uploaded"})
    else:
        log(f"警告：上传后校验未通过（data={verify.get('generated') if verify else None}，"
            f"index={v_gen}），保持未完成状态以便下次重试")

    align()
    log("=== 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())