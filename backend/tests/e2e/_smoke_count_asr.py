"""冒烟校验 count_asr_connections 的 lsof 参数：不依赖任何第三方包。

跑法：python3 tests/e2e/_smoke_count_asr.py

做法：直接在「修后版」的 lsof 调用上跑——开一个 localhost TCP，本进程
连上去保持 ESTABLISHED，调一遍本文件的 _call_lsof()（即 conftest 中的
count_asr_connections 干的事），应能数到这条连接；关掉再调应回到 0。
两条都通过则 `-a`（AND 交集）+ `parts[1]`（PID 列）+ `-iTCP@ADDR`
（地址过滤）三件套都站得住。失败则说明修复仍需复核。

故意不走 `import conftest`：那条路径会拉 pytest/httpx 全家桶，CI 上
装不全就会栽在 import，反而看不到 lsof 本身的修复效果。
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import threading
import time


def _call_lsof(pid: int, asr_addr: str) -> int:
    """复刻 conftest.count_asr_connections 的修后版本。仅这里用，不导出。"""
    out = subprocess.run(
        ["lsof", "-nP", "-a",
         "-p", str(pid),
         "-iTCP@" + asr_addr,
         "-sTCP:ESTABLISHED"],
        capture_output=True, text=True, check=False,
    )
    n = 0
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == str(pid):
            n += 1
    return n


def _open_one_established() -> tuple[socket.socket, socket.socket, socket.socket]:
    """开一个 localhost TCP 监听；本进程连上去；返回 (server, accepted, client)。"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    port = server.getsockname()[1]
    accepted_holder: list[socket.socket] = []

    def _accept_one():
        c, _ = server.accept()
        accepted_holder.append(c)
        try:
            c.settimeout(2.0)
            c.recv(4096)
        except OSError:
            pass

    threading.Thread(target=_accept_one, daemon=True).start()

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    time.sleep(0.2)
    deadline = time.monotonic() + 1.0
    while not accepted_holder and time.monotonic() < deadline:
        time.sleep(0.02)
    assert accepted_holder, "accept 子线程未就绪"
    return server, accepted_holder[0], client


def main() -> int:
    if shutil.which("lsof") is None:
        print("[smoke] SKIP: no lsof on this host")
        return 0

    pid = __import__("os").getpid()
    port_here = _open_one_established()
    server, accepted, client = port_here
    port = server.getsockname()[1]
    asr = f"127.0.0.1:{port}"

    baseline = _call_lsof(pid, "127.0.0.1:1")  # 不存在的端口先采基线
    open1 = _call_lsof(pid, asr)
    print(f"[smoke] pid={pid} baseline={baseline} opened={open1} (期望 baseline=0, opened≥1)")

    client.close()
    try:
        accepted.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    accepted.close()
    server.close()
    time.sleep(0.4)
    after_close = _call_lsof(pid, asr)
    print(f"[smoke] closed -> count={after_close} (期望回到 {baseline})")

    ok = baseline == 0 and open1 >= 1 and after_close == 0
    print(f"[smoke] {'PASS' if ok else 'FAIL'} —— -a / 列号 / 地址过滤 三件套联动验证")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
