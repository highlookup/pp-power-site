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
import subprocess
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = "highlookup/pp-power-site"
BRANCH = "main"
FILES = ["data.json", "index.html"]
LOG = os.path.join(ROOT, "update_local.log")
STATE = os.path.join(ROOT, "update_state.json")

EARLIEST_HOUR = 16      # 收盘后时间点：此刻之后的成功更新才算「当日收盘已采集」
EARLIEST_MIN = 30


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


def already_done():
    """判断目标交易日是否已经成功更新过（依据本地状态标记）"""
    st = load_state()
    done_day = st.get("done_for") or ""
    return bool(done_day) and done_day >= target_date()


def remote_is_target(remote):
    """远程数据是否是目标交易日的数据（按 generated 日期前缀判断）"""
    if not remote:
        return False
    g = remote.get("generated") or ""
    return g.startswith(target_date())


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

    if not force:
        if already_done():
            log(f"目标交易日 {target_date()} 已完成更新，跳过")
            return 0

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
    if remote is not None and substantive(local) == substantive(remote) and remote_is_target(remote):
        log(f"线上已是目标交易日 {target_date()} 的最新数据，无需推送")
        save_state({"last_success": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "done_for": target_date(),
                    "note": "already-fresh"})
        align()
        return 0

    log("有实质变化，开始上传 data.json / index.html")
    ok = True
    for p in FILES:
        if not upload(p):
            ok = False
    if not ok:
        log("部分文件上传失败（下次触发会重试）")
        return 1

    # 上传后重新校验：只有确认线上是目标交易日的数据才记成功
    verify = remote_data()
    if remote_is_target(verify):
        log(f"已确认线上为目标交易日 {target_date()} 的数据")
        save_state({"last_success": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "done_for": target_date(),
                    "note": "uploaded"})
    else:
        log("警告：上传后线上时间戳仍不符目标交易日，保持未完成状态以便下次重试")

    align()
    log("=== 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())