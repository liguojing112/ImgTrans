from __future__ import annotations

import argparse
from collections.abc import Sequence
import getpass
import platform
import socket
import subprocess

from server.app import create_app
from server.config import ServerSettings, ServerSettingsError
from server.admin.security import AdminSecurityError, hash_admin_password


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ImgTrans backend service")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="validate configuration, database and routes without serving",
    )
    parser.add_argument(
        "--hash-admin-password",
        action="store_true",
        help="prompt for an administrator password and print its scrypt hash",
    )
    return parser


def listener_info(host: str, port: int) -> tuple[int | None, str | None]:
    """探测 (host, port) 是否已被监听；返回 (占用进程 PID, 进程命令行摘要)。

    端口空闲时返回 (None, None)。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.5)
        probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        if probe.connect_ex((probe_host, port)) != 0:
            return None, None
    finally:
        probe.close()
    return _find_listener(host, port)


def _run_text(args: list[str]) -> str:
    """运行命令并读取文本输出（Windows 按系统代码页解码，避免中文乱码崩溃）。"""
    kwargs: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "errors": "replace",
        "check": False,
    }
    if platform.system() == "Windows":
        kwargs["encoding"] = "mbcs"
    completed = subprocess.run(args, **kwargs)
    return completed.stdout or ""


def _find_listener(host: str, port: int) -> tuple[int | None, str | None]:
    """按平台查找监听端口的进程 PID 与命令行。"""
    pid: int | None = None
    if platform.system() == "Windows":
        output = _run_text(["netstat", "-ano"])
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING":
                address = parts[1]
                if address.rsplit(":", 1)[-1] == str(port):
                    try:
                        pid = int(parts[4])
                    except ValueError:
                        pid = None
                    break
        if pid is None:
            return None, None
        command = _run_text(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\" | "
                "Select-Object -ExpandProperty CommandLine",
            ]
        ).strip()
        return pid, command or None
    output = _run_text(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"])
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            try:
                pid = int(parts[1])
            except ValueError:
                pid = None
            break
    command = None
    if pid is not None:
        command = _run_text(
            ["ps", "-p", str(pid), "-o", "command="]
        ).strip()
    return pid, command or None


def _is_imgtrans_process(command: str | None) -> bool:
    if not command:
        return False
    lowered = command.casefold()
    return (
        "imgtrans" in lowered
        or "server.main" in lowered
        or " -m server" in lowered
        or "server.exe" in lowered
        or ("server" in lowered and "uvicorn" in lowered)
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.hash_admin_password:
        try:
            password = getpass.getpass("Administrator password: ")
            confirmation = getpass.getpass("Confirm password: ")
            if password != confirmation:
                print("passwords_do_not_match")
                return 2
            print(hash_admin_password(password))
            return 0
        except AdminSecurityError as error:
            print(f"password_error: {error}")
            return 2
    try:
        settings = ServerSettings.from_env()
    except ServerSettingsError as error:
        print(f"configuration_error: {error}")
        return 2
    if arguments.smoke_test:
        app = create_app(settings)
        try:
            if not app.state.database.probe():
                print("database_unavailable")
                return 1
            route_paths = set(app.openapi().get("paths", {}))
            required = {
                "/health/live",
                "/health/ready",
                "/v1/service-info",
                "/v1/client-config",
                "/v1/translations",
                "/v1/activations/validate",
                "/admin/login",
            }
            if not required.issubset(route_paths):
                print("route_contract_incomplete")
                return 1
            print("imgtrans-server ready api=v1")
            return 0
        finally:
            app.state.database.close()

    pid, command = listener_info(settings.host, settings.port)
    if pid is not None:
        print(f"启动失败：{settings.host}:{settings.port} 已被占用。")
        print(f"占用进程：PID {pid}（{command or '未知程序'}）")
        if _is_imgtrans_process(command):
            print(
                "检测到旧的 ImgTrans 服务仍在运行——服务与客户端相互独立，"
                "关闭客户端不会停止服务。"
            )
            print(
                "如需重启服务，请先结束旧进程（Windows）："
                f"taskkill /F /PID {pid}"
            )
        else:
            print(
                "该端口被其他程序占用；可设置 IMGTRANS_SERVER_PORT 换端口启动，"
                "或先停止占用程序。"
            )
        return 3

    import uvicorn

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
    return 0
