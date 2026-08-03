"""一键启动脚本测试。"""

import subprocess
import sys

import pytest

from scripts.launch_desktop import main


class FakeProc:
    def __init__(self, command) -> None:
        self.command = list(command)
        self.terminated = False
        self.killed = False
        self._exit_code = 0

    def poll(self):
        return self._exit_code if self.terminated or self.killed else None

    def wait(self, timeout=None):
        del timeout
        return self._exit_code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def _recorded_procs(monkeypatch, *exit_codes) -> list:
    created: list[FakeProc] = []
    codes = list(exit_codes)

    def fake_popen(command, **kwargs):
        del kwargs
        proc = FakeProc(command)
        created.append(proc)
        if codes:
            proc._exit_code = codes.pop(0)
        return proc

    monkeypatch.setattr("scripts.launch_desktop.subprocess.Popen", fake_popen)
    return created


def test_launch_starts_server_then_client_and_stops_server(
    monkeypatch,
) -> None:
    """端口空闲：先启动服务 → 就绪 → 启动客户端 → 退出后终止服务。"""
    monkeypatch.setattr(
        "scripts.launch_desktop._port_in_use", lambda host, port: False
    )
    monkeypatch.setattr(
        "scripts.launch_desktop._wait_until_ready", lambda url, timeout=30: True
    )
    created = _recorded_procs(monkeypatch, 0)

    assert main([]) == 0
    assert len(created) == 2
    server_proc, client_proc = created
    assert server_proc.command == [sys.executable, "-m", "server"]
    assert client_proc.command == [sys.executable, "-m", "src", "--editor"]
    assert server_proc.terminated  # 客户端退出后服务被停止
    assert not client_proc.terminated


def test_launch_reuses_existing_imgtrans_server(monkeypatch) -> None:
    """端口已被本应用服务占用：复用现有服务，不启动新服务、也不终止它。"""
    monkeypatch.setattr(
        "scripts.launch_desktop._port_in_use", lambda host, port: True
    )
    monkeypatch.setattr(
        "scripts.launch_desktop.listener_info",
        lambda host, port: (12345, "python -m server"),
    )
    monkeypatch.setattr(
        "scripts.launch_desktop._wait_until_ready", lambda url, timeout=30: True
    )
    created = _recorded_procs(monkeypatch, 0)

    assert main([]) == 0
    assert len(created) == 1  # 只启动了客户端
    assert created[0].command == [sys.executable, "-m", "src", "--editor"]


def test_launch_fails_when_port_held_by_foreign_program(monkeypatch) -> None:
    """端口被其他程序占用：报错退出，不启动任何进程。"""
    monkeypatch.setattr(
        "scripts.launch_desktop._port_in_use", lambda host, port: True
    )
    monkeypatch.setattr(
        "scripts.launch_desktop.listener_info",
        lambda host, port: (8888, "C:\\Windows\\other-app.exe"),
    )
    created = _recorded_procs(monkeypatch)

    assert main([]) == 2
    assert created == []


def test_launch_rolls_back_server_when_not_ready(monkeypatch, capsys) -> None:
    """服务就绪超时：终止自己启动的服务并退出非零。"""
    monkeypatch.setattr(
        "scripts.launch_desktop._port_in_use", lambda host, port: False
    )
    monkeypatch.setattr(
        "scripts.launch_desktop._wait_until_ready", lambda url, timeout=30: False
    )
    created = _recorded_procs(monkeypatch)

    assert main([]) == 1
    assert len(created) == 1
    assert created[0].terminated
    assert "启动超时" in capsys.readouterr().out


def test_launch_does_not_change_translation_mode(monkeypatch, capsys) -> None:
    """一键启动不注入 server 模式：客户端保持默认翻译行为（与手动启动一致）。"""
    captured_env = {}

    def fake_popen(command, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return FakeProc(command)

    monkeypatch.setattr(
        "scripts.launch_desktop._port_in_use", lambda host, port: False
    )
    monkeypatch.setattr(
        "scripts.launch_desktop._wait_until_ready", lambda url, timeout=30: True
    )
    monkeypatch.setattr("scripts.launch_desktop.subprocess.Popen", fake_popen)

    monkeypatch.delenv("IMGTRANS_TRANSLATION_MODE", raising=False)
    monkeypatch.delenv("IMGTRANS_API_BASE_URL", raising=False)

    main([])
    assert "IMGTRANS_TRANSLATION_MODE" not in captured_env
    assert "IMGTRANS_API_BASE_URL" not in captured_env
    assert "默认翻译模式" in capsys.readouterr().out


def test_launch_injects_base_url_only_for_server_mode(monkeypatch, capsys) -> None:
    """用户已配置服务端模式但未设地址时，补上本地服务地址；模式本身不被改写。"""
    captured_env = {}

    def fake_popen(command, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return FakeProc(command)

    monkeypatch.setattr(
        "scripts.launch_desktop._port_in_use", lambda host, port: False
    )
    monkeypatch.setattr(
        "scripts.launch_desktop._wait_until_ready", lambda url, timeout=30: True
    )
    monkeypatch.setattr("scripts.launch_desktop.subprocess.Popen", fake_popen)
    monkeypatch.setenv("IMGTRANS_TRANSLATION_MODE", "server")

    main([])
    assert captured_env["IMGTRANS_TRANSLATION_MODE"] == "server"
    assert captured_env["IMGTRANS_API_BASE_URL"] == "http://127.0.0.1:8000"
    assert "本地翻译服务" in capsys.readouterr().out

    # 用户已配置远程地址则保留
    monkeypatch.setenv("IMGTRANS_API_BASE_URL", "https://remote.example.com")
    main([])
    assert captured_env["IMGTRANS_API_BASE_URL"] == "https://remote.example.com"
