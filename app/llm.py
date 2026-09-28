"""Thin Groq chat wrapper with model fallback, rate-limit backoff and JSON extraction."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from .config import get_settings

log = logging.getLogger(__name__)

_client = None


MAX_RATE_LIMIT_WAIT = 20.0  # seconds; longer waits (e.g. daily quota) switch to the fallback model


class LLMUnavailable(RuntimeError):
    """Raised when no model could produce a usable answer."""


class ModelRateLimited(RuntimeError):
    """One model is rate limited for longer than we are willing to wait."""


def _get_client():
    global _client
    settings = get_settings()
    if not settings.groq_api_key:
        raise LLMUnavailable("GROQ_API_KEY is not set")
    if _client is None:
        from groq import AsyncGroq

        _client = AsyncGroq(api_key=settings.groq_api_key, max_retries=0, timeout=60)
    return _client


def models() -> list[str]:
    """Primary model first, then the fallbacks (GROQ_FALLBACK_MODEL may be comma-separated)."""
    s = get_settings()
    fallbacks = [m.strip() for m in s.groq_fallback_model.split(",")]
    return [m for m in [s.groq_model, *fallbacks] if m]


def _extra_body(model: str) -> dict[str, Any]:
    if model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": "low"}
    if model.startswith("qwen/"):
        return {"reasoning_format": "hidden"}
    return {}


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply (handles <think> and ``` fences)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model reply")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("model reply JSON is not an object")
    return obj


async def chat(
    messages: list[dict[str, str]],
    model: str,
    json_mode: bool = False,
    temperature: float = 0.1,
    max_tokens: int = 700,
) -> str:
    """Single chat completion.

    Short rate limits (per-minute) are waited out and retried; long ones (per-day
    quota) raise ModelRateLimited at once so the caller can switch models.
    """
    from groq import BadRequestError, RateLimitError

    client = _get_client()
    kwargs: dict[str, Any] = dict(model=model, messages=messages, temperature=temperature,
                                  max_tokens=max_tokens, extra_body=_extra_body(model))
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    for attempt in range(4):
        try:
            resp = await client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except RateLimitError as e:
            wait = _retry_after(e) or 2 ** (attempt + 1)
            if wait > MAX_RATE_LIMIT_WAIT:
                raise ModelRateLimited(f"{model} rate limited for {wait:.0f}s") from e
            log.warning("Groq rate limited on %s, waiting %.1fs", model, wait)
            await asyncio.sleep(wait)
        except BadRequestError as e:
            # Some models reject json mode or a reasoning option: retry once plain.
            if "response_format" in kwargs or kwargs.get("extra_body"):
                log.warning("Groq bad request on %s (%s); retrying without extras", model, e)
                kwargs.pop("response_format", None)
                kwargs["extra_body"] = {}
                continue
            raise
    raise ModelRateLimited(f"{model} kept rate limiting")


def _retry_after(e: Exception) -> float | None:
    try:
        return float(e.response.headers.get("retry-after"))  # type: ignore[attr-defined]
    except Exception:
        return None


async def complete_json(
    messages: list[dict[str, str]], validate, attempts_per_model: int = 2
) -> tuple[dict[str, Any], str]:
    """Ask for JSON, validate it, retry then fall back to the next model.

    ``validate`` takes the parsed dict and returns a cleaned dict or raises ValueError.
    Returns (cleaned, model_used). Raises LLMUnavailable if everything fails.
    """
    errors = []
    for model in models():
        convo = list(messages)
        for _ in range(attempts_per_model):
            try:
                raw = await chat(convo, model, json_mode=True)
                return validate(extract_json(raw)), model
            except LLMUnavailable:
                raise
            except (ValueError, json.JSONDecodeError) as e:
                errors.append(f"{model}: {e}")
                convo = messages + [{"role": "user", "content":
                                     f"Your last reply was invalid ({e}). Reply with ONLY the JSON object."}]
            except Exception as e:  # network / API errors: move on to the next model
                errors.append(f"{model}: {type(e).__name__}: {e}")
                break
    raise LLMUnavailable("; ".join(errors) or "no models configured")


async def complete_text(messages: list[dict[str, str]], max_tokens: int = 900) -> str:
    """Plain text completion with model fallback."""
    last: Exception | None = None
    for model in models():
        try:
            text = await chat(messages, model, max_tokens=max_tokens, temperature=0.2)
            return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        except LLMUnavailable:
            raise
        except Exception as e:
            last = e
    raise LLMUnavailable(str(last))
