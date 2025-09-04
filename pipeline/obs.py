from __future__ import annotations

import os
import time
import logging
from contextlib import AbstractContextManager
from typing import Any, Dict, Optional


_HOST = os.getenv("LANGFUSE_HOST")
_PK = os.getenv("LANGFUSE_PUBLIC_KEY")
_SK = os.getenv("LANGFUSE_SECRET_KEY")

_client: Any = None
_trace: Any = None
_trace_id: Optional[str] = None

_logger = logging.getLogger("pipeline")


def _init_client() -> None:
    global _client  # noqa: PLW0603
    if _client is not None:
        return
    if not (_HOST and _PK and _SK):
        return
    try:
        # Import guarded so tests remain offline-friendly
        from langfuse import Langfuse  # type: ignore

        _client = Langfuse(host=_HOST, public_key=_PK, secret_key=_SK)
    except Exception:  # noqa: BLE001
        # If import or client init fails, stay in no-op mode
        _client = None


def _ensure_trace() -> None:
    global _trace, _trace_id  # noqa: PLW0603
    if _trace is not None or _client is None:
        return
    try:
        # Try common SDK patterns; swallow errors to remain no-op safe
        # Prefer a single process-wide trace to nest spans under
        # Name kept stable for easier grouping in backends
        tr = None
        try:
            tr = _client.trace(name="pipeline-run")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            try:
                tr = _client.create_trace(name="pipeline-run")  # type: ignore[attr-defined]
            except Exception:
                tr = None
        _trace = tr
        # Best-effort extraction of an identifier for run_report
        if tr is not None:
            _trace_id = (
                getattr(tr, "id", None)
                or getattr(tr, "trace_id", None)
                or getattr(tr, "traceId", None)
            )
    except Exception:  # noqa: BLE001
        _trace = None
        _trace_id = None


OBS_ENABLED: bool
try:
    _init_client()
    OBS_ENABLED = bool(_client is not None)
except Exception:  # noqa: BLE001
    OBS_ENABLED = False


class _NoopSpan(AbstractContextManager):
    def __init__(self, name: str, attrs: Optional[Dict[str, Any]] = None):
        self.name = name
        self.attrs: Dict[str, Any] = dict(attrs or {})
        self._t0: float = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        # Local log only; never network
        if _logger:
            _logger.debug("obs start: %s | %s", self.name, self.attrs)
        return self

    def set(self, attrs: Dict[str, Any] | None = None) -> None:
        if attrs:
            self.attrs.update(attrs)

    def __exit__(self, exc_type, exc, exc_tb):
        dt = time.perf_counter() - self._t0
        if _logger:
            _logger.debug(
                "obs end: %s | %.4fs | %s",
                self.name,
                dt,
                {**self.attrs, "duration_sec": round(dt, 6)},
            )
        return False  # do not suppress exceptions


class _LangfuseSpan(AbstractContextManager):
    def __init__(self, name: str, attrs: Optional[Dict[str, Any]] = None):
        self.name = name
        self.attrs: Dict[str, Any] = dict(attrs or {})
        self._t0: float = 0.0
        self._span: Any = None

    def __enter__(self):
        self._t0 = time.perf_counter()
        if _logger:
            _logger.debug("obs start: %s | %s", self.name, self.attrs)
        try:
            _ensure_trace()
            tr = _trace
            sp = None
            if tr is not None:
                # Try nested span creation on the trace
                try:
                    sp = tr.span(name=self.name)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    try:
                        sp = tr.create_span(name=self.name)  # type: ignore[attr-defined]
                    except Exception:
                        sp = None
            if sp is None and _client is not None:
                # Fallback: top-level span on client
                try:
                    sp = _client.span(name=self.name)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    try:
                        sp = _client.create_span(name=self.name)  # type: ignore[attr-defined]
                    except Exception:
                        sp = None
            self._span = sp
            # Best-effort attributes on enter
            if self._span and self.attrs:
                for k, v in self.attrs.items():
                    try:
                        # Try common attribute APIs
                        if hasattr(self._span, "set_attribute"):
                            self._span.set_attribute(k, v)  # type: ignore[attr-defined]
                        elif hasattr(self._span, "update"):
                            self._span.update({k: v})  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            self._span = None
        return self

    def set(self, attrs: Dict[str, Any] | None = None) -> None:
        if not attrs:
            return
        self.attrs.update(attrs)
        if self._span is None:
            return
        for k, v in attrs.items():
            try:
                if hasattr(self._span, "set_attribute"):
                    self._span.set_attribute(k, v)  # type: ignore[attr-defined]
                elif hasattr(self._span, "update"):
                    self._span.update({k: v})  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    def __exit__(self, exc_type, exc, exc_tb):
        dt = time.perf_counter() - self._t0
        if _logger:
            _logger.debug(
                "obs end: %s | %.4fs | %s",
                self.name,
                dt,
                {**self.attrs, "duration_sec": round(dt, 6)},
            )
        try:
            if self._span is not None:
                # Attach duration if supported, then end/finish the span
                try:
                    if hasattr(self._span, "set_attribute"):
                        self._span.set_attribute("duration_sec", round(dt, 6))  # type: ignore[attr-defined]
                    elif hasattr(self._span, "update"):
                        self._span.update({"duration_sec": round(dt, 6)})  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
                try:
                    if hasattr(self._span, "end"):
                        self._span.end()  # type: ignore[attr-defined]
                    elif hasattr(self._span, "finish"):
                        self._span.finish()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
        finally:
            return False  # do not suppress exceptions


def obs_span(name: str, attrs: Optional[Dict[str, Any]] = None) -> AbstractContextManager:
    """Context manager wrapper for optional Langfuse spans.

    - If LANGFUSE env vars are set and the SDK is available, emits spans and attaches attributes.
    - Always logs to the local logger for offline-friendly traces.
    - When unset/unavailable, behaves as a safe no-op.
    """
    if OBS_ENABLED and _client is not None:
        return _LangfuseSpan(name, attrs)
    return _NoopSpan(name, attrs)


def obs_metadata() -> Dict[str, Any]:
    """Minimal metadata for run_report enrichment.

    Returns: {"enabled": bool, "trace_id": Optional[str]}
    """
    return {"enabled": bool(OBS_ENABLED), "trace_id": _trace_id}

