"""服务启动器端口占用检查测试。"""

import sys
import types

import pytest

from server.main import _is_imgtrans_process, main


def _free_port(monkeypatch) -> list:
    """端口空闲：listener_info 返回未占用，uvicorn 正常启动。"""
    runs = []
    fake_uvicorn = types.SimpleNamespace(
        run=lambda *args, **kwargs: runs.append(kwargs)
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(
        "server.main.listener_info",
        lambda host, port: (None, None),
    )
    return runs


def test_main_starts_when_port_is_free(monkeypatch) -> None:
    runs = _free_port(monkeypatch)

    assert main([]) == 0
    assert len(runs) == 1
    assert runs[0]["host"] == "127.0.0.1"
    assert runs[0]["port"] == 8000


def test_main_reports_port_occupied_by_imgtrans_server(monkeypatch, capsys) -> None:
    """端口被旧 ImgTrans 服务占用 → 友好提示并退出码 3。"""
    monkeypatch.setattr(
        "server.main.listener_info",
        lambda host, port: (12345, "python -m server"),
    )

    assert main([]) == 3

    output = capsys.readouterr().out
    assert "已被占用" in output
    assert "PID 12345" in output
    assert "服务与客户端相互独立" in output
    assert "taskkill /F /PID 12345" in output


def test_main_reports_port_occupied_by_foreign_program(monkeypatch, capsys) -> None:
    """端口被其他程序占用 → 提示换端口并退出码 3。"""
    monkeypatch.setattr(
        "server.main.listener_info",
        lambda host, port: (8888, "C:\\Windows\\some-other-app.exe"),
    )

    assert main([]) == 3

    output = capsys.readouterr().out
    assert "已被占用" in output
    assert "IMGTRANS_SERVER_PORT" in output
    assert "taskkill" not in output


def test_is_imgtrans_process_matching() -> None:
    assert _is_imgtrans_process("python -m server")
    assert _is_imgtrans_process("C:\\app\\imgtrans-server.exe")
    assert _is_imgtrans_process("python -m uvicorn server.main:app")
    assert not _is_imgtrans_process("python -m uvicorn other_app:app")
    assert not _is_imgtrans_process(None)
    assert not _is_imgtrans_process("C:\\Windows\\explorer.exe")
