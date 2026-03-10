"""OpenAI SDK wrapper with retry and JSON mode."""

import asyncio
import logging

import openai

logger = logging.getLogger(__name__)


async def call_llm(
    system_prompt: str,
    user_message: str,
    *,
    purpose: str,
    request_id: str,
    temperature: float = 0.1,
    model: str = "gpt-5.2",
    api_key: str,
    json_mode: bool = True,
) -> str:
    """Call OpenAI with optional JSON mode, retries on rate limit/timeout.

    Returns raw string content from the LLM response.
    Raises openai.AuthenticationError on auth errors (caller should handle).
    Raises RuntimeError if all retries exhausted.
    """
    client = openai.AsyncOpenAI(api_key=api_key)

    delays = [1, 2, 4]

    for attempt in range(1, 4):
        try:
            logger.info(
                "llm.request | req=%s purpose=%s model=%s attempt=%d",
                request_id,
                purpose,
                model,
                attempt,
            )

            kwargs = dict(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
            )
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = await client.chat.completions.create(**kwargs)

            content = response.choices[0].message.content or ""
            usage = response.usage

            logger.info(
                "llm.response | req=%s purpose=%s response_time=ok total_tokens=%s",
                request_id,
                purpose,
                usage.total_tokens if usage else "?",
            )

            return content

        except openai.AuthenticationError:
            logger.error(
                "llm.auth_error | req=%s purpose=%s", request_id, purpose
            )
            raise

        except (openai.RateLimitError, openai.APITimeoutError) as exc:
            delay = delays[attempt - 1] if attempt <= len(delays) else delays[-1]
            logger.warning(
                "llm.retry | req=%s purpose=%s attempt=%d error=%s delay=%ds",
                request_id,
                purpose,
                attempt,
                type(exc).__name__,
                delay,
            )
            if attempt < 3:
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "llm.exhausted | req=%s purpose=%s after=%d attempts",
                    request_id,
                    purpose,
                    attempt,
                )
                raise RuntimeError(
                    f"LLM call failed after {attempt} retries: {exc}"
                ) from exc

        except openai.APIError as exc:
            delay = delays[attempt - 1] if attempt <= len(delays) else delays[-1]
            logger.warning(
                "llm.retry | req=%s purpose=%s attempt=%d error=%s",
                request_id,
                purpose,
                attempt,
                str(exc)[:100],
            )
            if attempt < 3:
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(
                    f"LLM call failed after {attempt} retries: {exc}"
                ) from exc

    raise RuntimeError("LLM call failed: unexpected code path")


async def call_llm_vision(
    system_prompt: str,
    image_bytes: bytes,
    caption: str | None = None,
    *,
    purpose: str,
    request_id: str,
    temperature: float = 0.1,
    model: str = "gpt-5.2",
    api_key: str,
    json_mode: bool = True,
) -> str:
    """Call OpenAI with an image (vision). Same retry logic as call_llm.

    Sends the image as a base64 data URL in a content block.
    Returns raw string content from the LLM response.
    Raises openai.AuthenticationError on auth errors (caller should handle).
    Raises RuntimeError if all retries exhausted.
    """
    import base64

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64}"

    user_content: list[dict] = [
        {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
    ]
    if caption:
        user_content.append({"type": "text", "text": f"Caption del usuario: {caption}"})

    client = openai.AsyncOpenAI(api_key=api_key)
    delays = [1, 2, 4]

    for attempt in range(1, 4):
        try:
            logger.info(
                "llm.vision_request | req=%s purpose=%s model=%s attempt=%d",
                request_id,
                purpose,
                model,
                attempt,
            )

            kwargs = dict(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
            )
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = await client.chat.completions.create(**kwargs)

            content = response.choices[0].message.content or ""
            usage = response.usage

            logger.info(
                "llm.vision_response | req=%s purpose=%s total_tokens=%s",
                request_id,
                purpose,
                usage.total_tokens if usage else "?",
            )

            return content

        except openai.AuthenticationError:
            logger.error(
                "llm.auth_error | req=%s purpose=%s", request_id, purpose
            )
            raise

        except (openai.RateLimitError, openai.APITimeoutError) as exc:
            delay = delays[attempt - 1] if attempt <= len(delays) else delays[-1]
            logger.warning(
                "llm.retry | req=%s purpose=%s attempt=%d error=%s delay=%ds",
                request_id,
                purpose,
                attempt,
                type(exc).__name__,
                delay,
            )
            if attempt < 3:
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "llm.exhausted | req=%s purpose=%s after=%d attempts",
                    request_id,
                    purpose,
                    attempt,
                )
                raise RuntimeError(
                    f"LLM call failed after {attempt} retries: {exc}"
                ) from exc

        except openai.APIError as exc:
            delay = delays[attempt - 1] if attempt <= len(delays) else delays[-1]
            logger.warning(
                "llm.retry | req=%s purpose=%s attempt=%d error=%s",
                request_id,
                purpose,
                attempt,
                str(exc)[:100],
            )
            if attempt < 3:
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(
                    f"LLM call failed after {attempt} retries: {exc}"
                ) from exc

    raise RuntimeError("LLM call failed: unexpected code path")
