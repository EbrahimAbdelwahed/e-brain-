from __future__ import annotations

from typing import Optional

import dspy

from ..config import get_settings


class WritePost(dspy.Signature):
    """Write a concise, factual X post about a neuroscience topic using given context.

    Requirements:
    - 1–2 sentences
    - Prefer clarity and accuracy; avoid hype
    - Occasional emoji is OK, but sparing
    - Keep total length <= 280 characters
    """

    query = dspy.InputField(desc="the user topic/query to address")
    context = dspy.InputField(desc="curated snippets as bullet points")
    post = dspy.OutputField(desc="final X post text")


def _configure_lm() -> None:
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY missing for DSPy")
    # Configure DSPy to use OpenAI with the configured chat model
    dspy.settings.configure(lm=dspy.OpenAI(model=s.chat_model, api_key=s.openai_api_key))


class PostGeneratorDSPy(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.writer = dspy.Predict(WritePost)

    def forward(self, query: str, context: str) -> str:
        out = self.writer(query=query, context=context)
        return (out.post or "").strip()


def generate_post(query: str, context: str) -> str:
    """Generate a post using DSPy with the configured LLM backend.

    This is a thin wrapper to keep the generator integration simple.
    """
    _configure_lm()
    mod = PostGeneratorDSPy()
    return mod.forward(query=query, context=context)

