"""Resource-limited PDF text extraction in a disposable child process.

This is process isolation with POSIX rlimits and a wall-clock kill switch. It is
not a separate UID/container/seccomp sandbox; production deployments need that
additional OS boundary before processing hostile public uploads.
"""
from __future__ import annotations

import multiprocessing
import os
from typing import Any


class PDFParseError(Exception):
    def __init__(self, code: str, message: str, status: int):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _bounded_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


def _apply_resource_limits(memory_mb: int, cpu_seconds: int) -> None:
    try:
        import resource
    except ImportError as exc:
        raise RuntimeError("POSIX resource limits are unavailable") from exc

    if not hasattr(resource, "RLIMIT_AS"):
        raise RuntimeError("address-space limits are unavailable")
    memory_bytes = memory_mb * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    except (OSError, ValueError) as exc:
        raise RuntimeError("could not apply PDF worker resource limits") from exc


def _worker_main(
    content: bytes,
    max_pages: int,
    max_chars: int,
    memory_mb: int,
    cpu_seconds: int,
    connection: Any,
) -> None:
    """Child-process entry point. Never return parser internals or tracebacks."""
    try:
        _apply_resource_limits(memory_mb, cpu_seconds)
    except RuntimeError:
        try:
            connection.send(("error", "PDF_RESOURCE_LIMIT_UNAVAILABLE"))
        finally:
            connection.close()
        return

    try:
        from io import BytesIO
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            connection.send(("error", "PDF_ENCRYPTED"))
            return
        page_count = len(reader.pages)
        if page_count > max_pages:
            connection.send(("error", "PDF_TOO_MANY_PAGES"))
            return

        pages: list[tuple[int, str]] = []
        total_chars = 0
        for index, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            total_chars += len(text)
            if total_chars > max_chars:
                connection.send(("error", "PDF_TEXT_LIMIT"))
                return
            pages.append((index + 1, text))
        connection.send(("ok", pages))
    except BaseException:
        # Parser internals may contain document-controlled strings; do not
        # forward tracebacks or parser messages to the API caller.
        try:
            connection.send(("error", "PDF_PARSE_FAILED"))
        except Exception:
            pass
    finally:
        connection.close()


def _stop_process(process: Any) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)


def _wait_for_result(process: Any, receiver: Any, timeout: float) -> tuple[str, Any]:
    if not receiver.poll(timeout):
        _stop_process(process)
        raise PDFParseError(
            "PDF_PARSE_TIMEOUT",
            "PDF 解析超过允许的执行时间，文件过于复杂或无法安全处理",
            422,
        )
    try:
        return receiver.recv()
    except EOFError:
        raise PDFParseError(
            "PDF_WORKER_FAILED", "PDF 隔离解析进程异常退出", 422
        ) from None


def _raise_worker_error(code: str) -> None:
    if code in {"PDF_ENCRYPTED", "PDF_TOO_MANY_PAGES", "PDF_PARSE_FAILED"}:
        raise PDFParseError(
            "UNSUPPORTED_MEDIA_TYPE",
            "PDF 受密码保护、页数超限或文件无法安全解析",
            415,
        )
    if code == "PDF_TEXT_LIMIT":
        raise PDFParseError("PAYLOAD_TOO_LARGE", "PDF 提取文字超过项目允许的上限", 413)
    if code == "PDF_RESOURCE_LIMIT_UNAVAILABLE":
        raise PDFParseError(
            "PDF_WORKER_UNAVAILABLE",
            "当前系统无法为 PDF 解析进程设置资源限制",
            503,
        )
    raise PDFParseError("PDF_WORKER_FAILED", "PDF 隔离解析进程异常退出", 422)


def parse_pdf_isolated(
    content: bytes,
    *,
    max_pages: int = 100,
    max_chars: int = 80_000,
    timeout_seconds: float | None = None,
) -> list[tuple[int, str]]:
    """Extract PDF pages in a spawned child with CPU, memory and wall-time caps."""
    if not isinstance(content, bytes):
        raise PDFParseError("UNSUPPORTED_MEDIA_TYPE", "PDF 内容格式无效", 415)
    timeout = (
        float(timeout_seconds)
        if timeout_seconds is not None
        else float(_bounded_env("TRACEMAP_PDF_TIMEOUT_SECONDS", 15, 1, 60))
    )
    memory_mb = _bounded_env("TRACEMAP_PDF_MEMORY_MB", 1024, 256, 4096)
    cpu_seconds = _bounded_env("TRACEMAP_PDF_CPU_SECONDS", 10, 1, 60)
    if timeout <= 0:
        raise ValueError("timeout_seconds must be positive")

    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker_main,
        args=(content, max_pages, max_chars, memory_mb, cpu_seconds, sender),
        daemon=True,
    )
    started = False
    try:
        process.start()
        started = True
        sender.close()
        status, payload = _wait_for_result(process, receiver, timeout)
        process.join(timeout=1)
        if process.is_alive():
            _stop_process(process)
        if status != "ok":
            _raise_worker_error(str(payload))
        if not isinstance(payload, list):
            raise PDFParseError("PDF_WORKER_FAILED", "PDF 解析结果格式无效", 422)
        return payload
    except PDFParseError:
        raise
    except Exception:
        if started and process.is_alive():
            _stop_process(process)
        raise PDFParseError(
            "PDF_WORKER_FAILED", "无法启动 PDF 隔离解析进程", 503
        ) from None
    finally:
        receiver.close()
        sender.close()
        if started and process.is_alive():
            _stop_process(process)
