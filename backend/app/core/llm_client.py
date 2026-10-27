from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from typing import Any, Callable
from urllib import error, request

from app.core.env import env_value, load_local_env_file


RESPONSES_PATH = "/responses"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_BIZROUTER_BASE_URL = "https://api.bizrouter.ai/v1"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen3-coder:30b"
OLLAMA_CHAT_PATH = "/api/chat"


@dataclass(frozen=True)
class LLMClientSettings:
    enabled: bool
    provider: str
    api_key: str
    api_key_env: str
    model: str
    base_url: str
    timeout: int
    num_ctx: int = 0


def resolve_llm_client_settings(
    *,
    openai_model: str,
    bizrouter_model: str,
) -> LLMClientSettings:
    load_local_env_file()
    provider = os.getenv("LLM_PROVIDER", "auto").strip().lower()
    if provider not in {"auto", "openai", "bizrouter", "ollama"}:
        raise ValueError("LLM_PROVIDER must be auto, openai, bizrouter, or ollama")

    bizrouter_key = os.getenv("BIZROUTER_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if provider == "auto":
        provider = "bizrouter" if bizrouter_key else "openai"
    enabled = env_value("LLM_REVIEW_ENABLED", "OPENAI_LLM_REVIEW_ENABLED", default="1")

    if provider == "ollama":
        # A local Ollama server needs no key; the placeholder keeps the
        # existing "key present" gates working for the offline provider.
        return LLMClientSettings(
            enabled=enabled not in {"0", "false", "no", "off"},
            provider=provider,
            api_key="ollama",
            api_key_env="OLLAMA_MODEL",
            model=os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL,
            base_url=os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/"),
            # Local 30B models are much slower than hosted APIs.
            timeout=max(int(env_value("LLM_REVIEW_TIMEOUT", default="600")), 10),
            num_ctx=ollama_num_ctx(),
        )
    if provider == "bizrouter":
        return LLMClientSettings(
            enabled=enabled not in {"0", "false", "no", "off"},
            provider=provider,
            api_key=bizrouter_key,
            api_key_env="BIZROUTER_API_KEY",
            model=os.getenv("BIZROUTER_MODEL", bizrouter_model).strip() or bizrouter_model,
            base_url=os.getenv("BIZROUTER_BASE_URL", DEFAULT_BIZROUTER_BASE_URL).rstrip("/"),
            timeout=max(int(env_value("LLM_REVIEW_TIMEOUT", "OPENAI_LLM_REVIEW_TIMEOUT", default="90")), 10),
        )
    return LLMClientSettings(
        enabled=enabled not in {"0", "false", "no", "off"},
        provider=provider,
        api_key=openai_key,
        api_key_env="OPENAI_API_KEY",
        model=os.getenv("OPENAI_TRANSLATION_MODEL", openai_model).strip() or openai_model,
        base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).rstrip("/"),
        timeout=max(int(env_value("LLM_REVIEW_TIMEOUT", "OPENAI_LLM_REVIEW_TIMEOUT", default="90")), 10),
    )


class ResponsesTransport:
    """Provider-neutral OpenAI Responses-compatible HTTP transport."""

    def __init__(
        self,
        settings: LLMClientSettings,
        *,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self._opener = opener or request.urlopen

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.settings.provider == "ollama":
            return ollama_to_responses(self._post(OLLAMA_CHAT_PATH, responses_to_ollama(body, self.settings)))
        return self._post(RESPONSES_PATH, body)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        api_request = request.Request(
            f"{self.settings.base_url}{path}",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        max_attempts = 6
        for attempt in range(max_attempts):
            try:
                with self._opener(api_request, timeout=self.settings.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except error.HTTPError as exc:
                body_text = exc.read().decode("utf-8", errors="replace")
                if exc.code not in {408, 409, 429, 500, 502, 503, 504} or attempt == max_attempts - 1:
                    raise RuntimeError(
                        f"{self.settings.provider} Responses API error {exc.code}: {body_text[:800]}"
                    ) from exc
                retry_after = retry_after_seconds(body_text)
            except (error.URLError, TimeoutError) as exc:
                if attempt == max_attempts - 1:
                    reason = getattr(exc, "reason", str(exc))
                    raise RuntimeError(
                        f"{self.settings.provider} Responses API request failed: {reason}"
                    ) from exc
                retry_after = 0.0
            delay = retry_after or min(2**attempt, 16)
            time.sleep(delay + (attempt + 1) * 0.25)
        raise RuntimeError(f"{self.settings.provider} Responses API request failed after retries")


def ollama_num_ctx() -> int:
    return max(int(env_value("OLLAMA_NUM_CTX", default="32768")), 2048)


def responses_to_ollama(body: dict[str, Any], settings: LLMClientSettings) -> dict[str, Any]:
    """Translate a Responses API request into an Ollama /api/chat request."""

    messages: list[dict[str, str]] = []
    for message in body.get("input", []):
        content = message.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        messages.append({"role": str(message.get("role", "user")), "content": str(content)})

    chat_body: dict[str, Any] = {
        "model": body.get("model") or settings.model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
    }
    # Ollama's default context is small; batched review prompts would be cut off.
    chat_body["options"]["num_ctx"] = settings.num_ctx or ollama_num_ctx()
    if body.get("max_output_tokens"):
        chat_body["options"]["num_predict"] = int(body["max_output_tokens"])
    text_format = body.get("text", {}).get("format", {})
    if text_format.get("type") == "json_schema" and isinstance(text_format.get("schema"), dict):
        chat_body["format"] = text_format["schema"]
    elif text_format.get("type") == "json_object":
        chat_body["format"] = "json"
    return chat_body


def ollama_to_responses(response: dict[str, Any]) -> dict[str, Any]:
    """Shape an Ollama chat reply like a Responses API result for existing parsers."""

    message = response.get("message")
    text = message.get("content", "") if isinstance(message, dict) else ""
    input_tokens = int(response.get("prompt_eval_count") or 0)
    output_tokens = int(response.get("eval_count") or 0)
    return {
        "status": "incomplete" if response.get("done_reason") == "length" else "completed",
        "incomplete_details": {"reason": "max_output_tokens"} if response.get("done_reason") == "length" else None,
        "output_text": text,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def retry_after_seconds(body_text: str) -> float:
    try:
        payload = json.loads(body_text)
        value = payload.get("error", {}).get("details", {}).get("retry_after", 0)
        return max(float(value), 0.0)
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return 0.0


def parse_responses_json(response: dict[str, Any]) -> dict[str, Any]:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return parse_json_text(output_text)

    parts: list[str] = []
    for output in response.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str):
                    parts.append(text)
    if not parts:
        raise RuntimeError(
            "LLM response did not contain structured output "
            f"(status={response.get('status', 'unknown')}, "
            f"incomplete_details={response.get('incomplete_details')!r}, "
            f"usage={response.get('usage')!r})"
        )
    return parse_json_text("\n".join(parts))


def parse_json_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(stripped[start : end + 1])
    return parsed if isinstance(parsed, dict) else {"items": []}
