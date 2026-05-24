"""LLM client wrapper.

Uses Gemini API through google-genai.
Set GEMINI_API_KEY in the environment.
"""

import os
from google import genai


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")


def get_llm_client():
    """Create Gemini client."""
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in environment")

    return genai.Client(api_key=api_key)


def call_llm(client, prompt: str) -> str:
    """Call Gemini and return plain text."""
    response = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=prompt,
    )

    return response.text or ""