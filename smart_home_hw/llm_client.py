"""OpenAI LLM client for reasoning-capable models."""

import os
from openai import OpenAI
from dotenv import load_dotenv


load_dotenv()

DEFAULT_MODEL = "gpt-5-nano"


def get_llm_client() -> OpenAI:
    """
    Create and return an OpenAI client using credentials from .env.

    Returns:
        OpenAI client instance
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in environment")
    return OpenAI(api_key=api_key)


def call_llm(
    client: OpenAI,
    prompt: str | list[dict],
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Call the OpenAI Responses API for reasoning-capable models.

    Args:
        client: OpenAI client instance
        prompt: Prompt string or list of message dicts
        model: Model name (default gpt-5-nano)

    Returns:
        Response text string
    """
    if isinstance(prompt, str):
        prompt = [{"role": "user", "content": prompt}]

    response = client.responses.create(
        model=model,
        input=prompt,
    )
    return response.output_text
