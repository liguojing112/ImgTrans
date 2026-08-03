"""一键启动：自动启动翻译服务 → 打开客户端；客户端退出后自动停止服务。

用法：
    python scripts/launch_desktop.py            # 默认 127.0.0.1:8000
    python scripts/launch_desktop.py --port 9000

端口已有本应用服务在运行时直接复用（不重复启动、也不随客户端退出而停止）；
端口被其他程序占用时报错退出。
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import os
import socket
import subprocess
import sys
import time
import urllib.request

from server.main import _is_imgtrans_process, listener_info

_READY_TIMEOUT_S = 30


def _port_in_use(host: str, port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0
    finally:
        probe.close()


def _wait_until_ready(url: str, timeout: float = _READY_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _terminate(proc: subprocess.Popen) -> None:
    """终止子进程：先温和终止，超时再强杀。"""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception:
            pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ImgTrans 一键启动（服务 + 客户端）")
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="翻译服务端口（默认 8000）",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="翻译服务监听地址（默认 127.0.0.1）",
    )
    arguments = parser.parse_args(argv)
    host, port = arguments.host, arguments.port
    base_url = f"http://{host}:{port}"

    server_proc: subprocess.Popen | None = None
    reuse_existing = False
    if _port_in_use(host, port):
        pid, command = listener_info(host, port)
        if pid is not None and _is_imgtrans_process(command):
            print(f"检测到已有翻译服务在运行（PID {pid}），将直接复用。")
            reuse_existing = True
        else:
            print(
                f"启动失败：{host}:{port} 已被其他程序占用"
                + (f"（PID {pid}）" if pid is not None else "")
                + "，请先停止占用程序或使用 --port 换端口。"
            )
            return 2
    else:
        print(f"正在启动翻译服务（{base_url}）…")
        server_proc = subprocess.Popen(
            [sys.executable, "-m", "server"],
            stdout=None,
            stderr=None,
        )

    if not _wait_until_ready(f"{base_url}/health/live"):
        print("翻译服务启动超时，正在回滚…")
        if server_proc is not None:
            _terminate(server_proc)
        return 1

    print("翻译服务已就绪。")
    if reuse_existing:
        print("注意：复用的服务由外部管理，客户端关闭时不会停止它。")
    else:
        print("客户端关闭后将自动停止翻译服务。")

    # 启动客户端：不改变用户的翻译模式（保持默认 mock，与手动启动行为一致）。
    # 仅当用户已显式配置服务端模式但未设地址时，补上本地服务地址。
    env = os.environ.copy()
    if env.get("IMGTRANS_TRANSLATION_MODE", "").strip().lower() == "server":
        env.setdefault("IMGTRANS_API_BASE_URL", base_url)
        print("客户端已配置服务端翻译模式，将连接本地翻译服务。")
    else:
        print(
            "客户端使用默认翻译模式（不依赖服务）。如需本地服务翻译，"
            "请设置 IMGTRANS_TRANSLATION_MODE=server 并完成设备激活。"
        )
    print("正在启动客户端…")
    client_proc = subprocess.Popen(
        [sys.executable, "-m", "src", "--editor"],
        env=env,
    )
    client_code = client_proc.wait()

    if server_proc is not None:
        _terminate(server_proc)
        print("翻译服务已停止。")
    print(f"客户端已退出（代码 {client_code}）。")
    return client_code


if __name__ == "__main__":
    raise SystemExit(main())
