"""
Model-agnostic agent base for SQLiq.

Uses the openai SDK with a configurable base_url.
This covers: Ollama (local or Colab+ngrok), OpenAI, and any
OpenAI-compatible endpoint. Switch backends via .env — no code changes.

Emits the full agentstatelib trace event set:
PromptAssembled → ModelCalled → ModelReturned → (ValidationFailed + RetryAttempted)*.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from openai import AsyncOpenAI

from agentstatelib import (
    ModelCalled,
    ModelReturned,
    PromptAssembled,
    RetryAttempted,
    StateStore,
    ValidationFailed,
)


def _build_client() -> AsyncOpenAI:
    """Build an AsyncOpenAI client from env vars. Works for Ollama and OpenAI."""
    base_url = os.getenv("SQLIQ_API_BASE")       # None → uses api.openai.com
    api_key = os.getenv("SQLIQ_API_KEY", "ollama")
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


_MODEL = os.getenv("SQLIQ_MODEL", "qwen2.5-coder:7b")
_MAX_RETRIES = int(os.getenv("SQLIQ_MAX_RETRIES", "3"))


async def call_model_with_events(
    *,
    store: StateStore,
    workflow_id: str,
    agent_id: str,
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    user_message: str,
    max_retries: int = _MAX_RETRIES,
) -> dict[str, Any]:
    """
    Call the model with a retry-with-correction loop.

    Emits PromptAssembled, ModelCalled, ModelReturned, ValidationFailed,
    and RetryAttempted events into the store on every attempt.

    Returns parsed JSON dict on success.
    Raises RuntimeError after max_retries exhausted.
    """
    last_error: str | None = None

    for attempt in range(max_retries):
        correction = (
            f"\n\nYour previous response failed JSON parsing: {last_error}."
            " Return ONLY valid JSON. No markdown. No explanation. No code fences."
            if last_error
            else ""
        )
        final_user = user_message + correction

        await store.append(
            PromptAssembled(
                workflow_id=workflow_id,
                agent_id=agent_id,
                prompt_text=final_user,
                system_prompt_length=len(system_prompt),
                context_length=len(final_user),
                is_correction_attempt=last_error is not None,
                attempt_number=attempt,
            )
        )

        call_id = str(uuid.uuid4())
        await store.append(
            ModelCalled(
                workflow_id=workflow_id,
                agent_id=agent_id,
                model=model,
                provider="openai_compatible",
                attempt_number=attempt,
                call_id=call_id,
            )
        )

        t0 = time.perf_counter()
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": final_user},
            ],
            temperature=0.1,
        )
        latency = time.perf_counter() - t0
        raw: str = response.choices[0].message.content or ""
        usage = response.usage

        await store.append(
            ModelReturned(
                workflow_id=workflow_id,
                agent_id=agent_id,
                call_id=call_id,
                raw_response=raw,
                latency_seconds=latency,
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                estimated_cost_usd=None,
            )
        )

        cleaned = (
            raw.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            last_error = str(exc)
            will_retry = attempt < max_retries - 1
            await store.append(
                ValidationFailed(
                    workflow_id=workflow_id,
                    agent_id=agent_id,
                    attempt_number=attempt,
                    error_type="json_decode_error",
                    error_message=str(exc),
                    raw_output=raw,
                    will_retry=will_retry,
                )
            )
            if will_retry:
                await store.append(
                    RetryAttempted(
                        workflow_id=workflow_id,
                        agent_id=agent_id,
                        attempt_number=attempt + 1,
                        previous_error=str(exc),
                    )
                )

    raise RuntimeError(
        f"[{agent_id}] max retries ({max_retries}) exhausted. Last error: {last_error}"
    )