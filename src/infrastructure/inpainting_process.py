from __future__ import annotations

import multiprocessing
from multiprocessing.connection import Connection
from pathlib import Path
from time import perf_counter

from src.domain.inpainting import InpaintingError, InpaintingRequest, InpaintingResult
from src.infrastructure.lama_onnx_adapter import LAMA_MODEL_SHA256, LamaOnnxAdapter


class ProcessLamaAdapter:
    adapter_id = "lama-process"

    def __init__(
        self,
        model_path: Path,
        expected_sha256: str = LAMA_MODEL_SHA256,
        timeout_seconds: float = 120,
    ) -> None:
        self._model_path = model_path
        self._expected_sha256 = expected_sha256
        self._timeout_seconds = timeout_seconds
        self._process: multiprocessing.Process | None = None
        self._connection: Connection | None = None

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        self._ensure_process()
        assert self._connection is not None
        assert self._process is not None
        started = perf_counter()
        try:
            self._connection.send(request)
        except (BrokenPipeError, EOFError, OSError) as error:
            self.close()
            raise InpaintingError("lama_worker_failed", "LaMa 工作进程无法接收任务") from error
        if not self._connection.poll(self._timeout_seconds):
            self.close()
            raise InpaintingError("lama_timeout", "LaMa 修复超时，已终止工作进程")
        try:
            kind, payload = self._connection.recv()
        except (EOFError, OSError) as error:
            self.close()
            raise InpaintingError("lama_worker_failed", "LaMa 工作进程意外退出") from error
        if kind == "error":
            code, message = payload
            raise InpaintingError(code, message)
        if not isinstance(payload, InpaintingResult):
            raise InpaintingError("lama_worker_invalid", "LaMa 工作进程返回了无效结果")
        return InpaintingResult(
            payload.document,
            payload.backend_id,
            (perf_counter() - started) * 1000,
            payload.warning,
        )

    def close(self) -> None:
        connection, process = self._connection, self._process
        self._connection = None
        self._process = None
        if connection is not None:
            try:
                connection.send(None)
            except (BrokenPipeError, EOFError, OSError):
                pass
            connection.close()
        if process is not None:
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)

    def cancel(self) -> None:
        connection, process = self._connection, self._process
        self._connection = None
        self._process = None
        if connection is not None:
            connection.close()
        if process is not None and process.is_alive():
            process.terminate()

    def _ensure_process(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self.close()
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(
            target=_worker_main,
            args=(child, self._model_path, self._expected_sha256),
            name="imgtrans-lama",
            daemon=True,
        )
        process.start()
        child.close()
        self._connection = parent
        self._process = process


def _worker_main(connection: Connection, model_path: Path, expected_sha256: str) -> None:
    adapter = LamaOnnxAdapter(model_path, expected_sha256)
    try:
        while True:
            request = connection.recv()
            if request is None:
                break
            try:
                connection.send(("result", adapter.inpaint(request)))
            except InpaintingError as error:
                connection.send(("error", (error.code, str(error))))
            except Exception as error:
                connection.send(("error", ("lama_worker_failed", str(error))))
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()
