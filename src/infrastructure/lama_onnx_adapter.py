from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

import cv2
import numpy as np
import onnxruntime as ort

from src.domain.image import ImageDocument
from src.domain.inpainting import InpaintingError, InpaintingRequest, InpaintingResult


LAMA_MODEL_FILENAME = "inpainting_lama_2025jan.onnx"
LAMA_MODEL_SHA256 = "7df918ac3921d3daf0aae1d219776cf0dc4e4935f035af81841b40adcf74fdf2"


class LamaOnnxAdapter:
    adapter_id = "lama-onnxruntime"

    def __init__(
        self,
        model_path: Path,
        expected_sha256: str = LAMA_MODEL_SHA256,
        threads: int = 2,
        session_factory: Callable[[Path, int], Any] | None = None,
    ) -> None:
        self._model_path = model_path
        self._expected_sha256 = expected_sha256
        self._threads = threads
        self._session_factory = session_factory or _create_session
        self._session: Any | None = None

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        started = perf_counter()
        session = self._get_session()
        document = request.document
        channels = 4 if document.mode == "RGBA" else 3
        source = np.frombuffer(document.pixels, dtype=np.uint8).reshape(
            document.asset.height, document.asset.width, channels
        )
        mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(
            request.erase_mask.height, request.erase_mask.width
        )
        if request.protect_mask is not None:
            protected = np.frombuffer(request.protect_mask.pixels, dtype=np.uint8).reshape(
                request.protect_mask.height, request.protect_mask.width
            )
            mask = np.where(protected > 0, 0, mask).astype(np.uint8)
        if not np.any(mask):
            raise InpaintingError("empty_erase_mask", "擦除蒙版为空")
        x0, y0, x1, y1 = _mask_crop(mask, request.context_pixels)
        source_crop = source[y0:y1, x0:x1, :3]
        mask_crop = mask[y0:y1, x0:x1]
        try:
            candidate_crop = _infer(session, source_crop, mask_crop)
        except Exception as error:
            raise InpaintingError("lama_inference_failed", f"LaMa 推理失败：{error}") from error
        output_rgb = source[:, :, :3].copy()
        selected = mask_crop > 0
        target_crop = output_rgb[y0:y1, x0:x1]
        target_crop[selected] = candidate_crop[selected]
        if document.mode == "RGBA":
            output = np.dstack((output_rgb, source[:, :, 3]))
        else:
            output = output_rgb
        return InpaintingResult(
            ImageDocument(document.asset, document.mode, output.tobytes()),
            self.adapter_id,
            (perf_counter() - started) * 1000,
        )

    def _get_session(self) -> Any:
        if self._session is None:
            _verify_model(self._model_path, self._expected_sha256)
            try:
                self._session = self._session_factory(self._model_path, self._threads)
            except Exception as error:
                raise InpaintingError("lama_load_failed", f"LaMa 模型加载失败：{error}") from error
        return self._session


def _create_session(model_path: Path, threads: int) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    return ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )


def _verify_model(model_path: Path, expected_sha256: str) -> None:
    if not model_path.is_file():
        raise InpaintingError("lama_model_missing", f"LaMa 模型尚未下载：{model_path}")
    digest = hashlib.sha256()
    with model_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if expected_sha256 and digest.hexdigest().lower() != expected_sha256.lower():
        raise InpaintingError("lama_model_invalid", "LaMa 模型哈希校验失败")


def _mask_crop(mask: np.ndarray, context: int) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    return (
        max(0, int(xs.min()) - context),
        max(0, int(ys.min()) - context),
        min(mask.shape[1], int(xs.max()) + context + 1),
        min(mask.shape[0], int(ys.max()) + context + 1),
    )


def _infer(session: Any, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    target_size = (512, 512)
    image_tensor = (
        cv2.resize(image, target_size, interpolation=cv2.INTER_AREA)
        .astype(np.float32)
        .transpose(2, 0, 1)[None, ...]
        / 255.0
    )
    mask_tensor = (
        cv2.resize(mask, target_size, interpolation=cv2.INTER_NEAREST) > 0
    ).astype(np.float32)[None, None, ...]
    raw = session.run(None, {"image": image_tensor, "mask": mask_tensor})[0][0]
    candidate = np.clip(raw.transpose(1, 2, 0), 0, 255).astype(np.uint8)
    return cv2.resize(
        candidate,
        (image.shape[1], image.shape[0]),
        interpolation=cv2.INTER_CUBIC,
    )
