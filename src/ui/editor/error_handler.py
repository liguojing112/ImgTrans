"""错误处理工具 — 分类、友好提示、敏感信息过滤。"""

from __future__ import annotations

_ERROR_SUGGESTIONS = {
    "connection": ("连接失败", "无法连接到后端服务", "请检查服务是否已启动，或网络连接是否正常。"),
    "unauthorized": ("认证失败", "API 认证未通过", "请检查 API Token 是否配置正确，或重新激活设备。"),
    "rate_limited": ("请求过多", "请求频率超过限制", "请稍后重试。"),
    "server_error": ("服务端错误", "后端服务返回异常", "请联系管理员，或稍后重试。"),
    "model_load": ("模型加载失败", "OCR/修复模型加载失败", "请检查模型文件是否完整，或重新下载模型。"),
    "image_format": ("图片格式不支持", "不支持该图片格式或文件无法读取", "请使用 JPG、PNG、WebP 或 BMP 格式。"),
    "image_not_found": ("图片未找到", "找不到所选图片文件", "请检查文件路径是否正确，文件是否已被删除。"),
    "export_error": ("导出失败", "导出目录不存在或磁盘空间不足", "请检查导出路径是否存在，以及磁盘空间是否充足。"),
    "file_too_large": ("文件过大", "图片文件超过大小限制", "请压缩图片后再试。"),
    "dimension_limit": ("尺寸超限", "图片宽高或像素数超过限制", "请缩小图片尺寸后再试。"),
    "unknown": ("操作失败", "发生了未知错误", "请重试，或联系技术支持。"),
}


def classify_error(error: Exception) -> tuple[str, str, str]:
    """对异常分类，返回 (标题, 消息, 用户建议)。"""
    msg = sanitize_error_msg(str(error))

    # 连接错误
    if isinstance(error, ConnectionError):
        return _ERROR_SUGGESTIONS["connection"]
    if "ConnectionRefusedError" in type(error).__name__:
        return _ERROR_SUGGESTIONS["connection"]

    # 从 error 中读取 code 属性
    error_code = getattr(error, "code", None)
    if error_code is not None:
        error_code = str(error_code)

    # HTTP 状态码判断
    if error_code == "401" or "unauthorized" in msg.lower() or "401" in msg:
        return _ERROR_SUGGESTIONS["unauthorized"]
    if error_code == "429" or "too many requests" in msg.lower() or "429" in msg:
        return _ERROR_SUGGESTIONS["rate_limited"]
    if error_code and error_code[0] == "5":
        return _ERROR_SUGGESTIONS["server_error"]

    # ImageValidationError 的 code 判断
    if error_code == "unsupported_input_format":
        return _ERROR_SUGGESTIONS["image_format"]
    if error_code == "file_not_found":
        return _ERROR_SUGGESTIONS["image_not_found"]
    if error_code == "file_too_large":
        return _ERROR_SUGGESTIONS["file_too_large"]
    if error_code in ("dimensions_too_small", "dimensions_too_large", "pixel_count_too_large"):
        return _ERROR_SUGGESTIONS["dimension_limit"]
    if error_code in ("output_directory_missing", "output_disk_full", "output_unavailable", "output_permission_denied"):
        return _ERROR_SUGGESTIONS["export_error"]

    # 模型加载失败（消息中包含 model/模型 关键字）
    if "model" in msg.lower() and any(w in msg.lower() for w in ("fail", "load", "not found", "missing")):
        return _ERROR_SUGGESTIONS["model_load"]

    # OcrError
    if "OcrError" in type(error).__name__:
        return _ERROR_SUGGESTIONS["model_load"]

    if error_code == "unsupported_output_format":
        return _ERROR_SUGGESTIONS["export_error"]

    return _ERROR_SUGGESTIONS["unknown"]


def sanitize_error_msg(msg: str) -> str:
    """过滤敏感信息：密钥、Token、绝对路径等。"""
    import re
    # 替换 sk- 开头的 API 密钥
    msg = re.sub(r'sk-[A-Za-z0-9]{20,}', 'sk-***', msg)
    # 替换 token=xxx 或 ?token=xxx
    msg = re.sub(r'(token=|api_key=|api-key=|apikey=)[A-Za-z0-9_-]{8,}', r'\1***', msg, flags=re.IGNORECASE)
    # 替换 Authorization: Bearer xxx
    msg = re.sub(r'Authorization:\s*Bearer\s+\S+', 'Authorization: Bearer ***', msg, flags=re.IGNORECASE)
    # 替换 Windows 绝对路径
    msg = re.sub(r'[A-Za-z]:\\[^\s,;)]+', '[path]', msg)
    # 替换 Unix 绝对路径
    msg = re.sub(r'(?<!\w)/(?:[^/\s]+/)+[^/\s]*', '[path]', msg)
    return msg
