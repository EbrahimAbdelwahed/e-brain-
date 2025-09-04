from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests


DEFAULT_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")


class LLMError(RuntimeError):
    pass


def generate_chat(
    *,
    model: str,
    messages: List[Dict[str, str]],
    system: Optional[str] = None,
    temperature: float = 0.2,
    top_p: float = 0.9,
    seed: Optional[int] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    """Call OpenRouter Chat Completions and return the assistant text.

    Args:
        model: Model name (e.g., "moonshotai/kimi-k2").
        messages: List of {role, content} pairs (no system; passed separately).
        system: Optional system prompt text.
        temperature: Sampling temperature (default 0.2 for determinism).
        top_p: Nucleus sampling (default 0.9).
        seed: Optional integer; if supported by model/provider, enables deterministic sampling.
        base_url: Override base URL (defaults to OPENROUTER_BASE_URL or OpenRouter default).
        api_key: Override API key (defaults to OPENROUTER_API_KEY env).

    Returns:
        Assistant message content as string.

    Raises:
        LLMError on HTTP or API errors.
    """
    # Offline stub for tests/dev: if LLM_OFFLINE=1, return a minimal deterministic text.
    if os.getenv("LLM_OFFLINE", "0") == "1":
        # Keep structure with Bottom line and a preprint guardrail sample.
        return (
            "Lead: Receipts-led summary.\n"
            "- What changed: example.\n"
            "- Guardrail: preprint; may change post-review.\n"
            "- Bottom line: use caution and read sources.\n"
        )

    api_key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise LLMError("Missing OPENROUTER_API_KEY; cannot call LLM.")

    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/chat/completions"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else []) + messages,
        "temperature": float(temperature),
        "top_p": float(top_p),
    }
    if seed is not None:
        payload["seed"] = int(seed)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"OpenRouter request failed: {e}") from e

    if resp.status_code >= 400:
        # Try to surface API error message
        try:
            err = resp.json()
        except Exception:  # noqa: BLE001
            err = {"error": resp.text}
        raise LLMError(f"OpenRouter error {resp.status_code}: {err}")

    try:
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise KeyError("choices")
        content = choices[0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("assistant content not str")
        return content
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"OpenRouter response parse error: {e}; body={resp.text[:500]}") from e

