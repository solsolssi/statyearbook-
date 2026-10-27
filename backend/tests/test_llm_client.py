from __future__ import annotations

import io
import json
import os
import unittest
from unittest import mock

from app.core.llm_client import (
    ResponsesTransport,
    parse_responses_json,
    resolve_llm_client_settings,
)


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class OllamaProviderTest(unittest.TestCase):
    def test_ollama_settings_need_no_api_key(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"LLM_PROVIDER": "ollama", "LLM_REVIEW_ENABLED": "1", "OLLAMA_MODEL": "qwen3-coder:30b"},
        ):
            settings = resolve_llm_client_settings(openai_model="gpt-5-mini", bizrouter_model="openai/gpt-5-mini")
        self.assertEqual(settings.provider, "ollama")
        self.assertTrue(settings.enabled and settings.api_key)
        self.assertEqual(settings.model, "qwen3-coder:30b")
        self.assertEqual(settings.base_url, "http://127.0.0.1:11434")

    def test_responses_body_is_sent_to_ollama_chat_and_parsed_back(self) -> None:
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "ollama", "LLM_REVIEW_ENABLED": "1"}):
            settings = resolve_llm_client_settings(openai_model="gpt-5-mini", bizrouter_model="openai/gpt-5-mini")
        sent: dict[str, object] = {}

        def opener(api_request, timeout):
            sent["url"] = api_request.full_url
            sent["body"] = json.loads(api_request.data.decode("utf-8"))
            reply = {
                "message": {"role": "assistant", "content": '{"items": [{"id": 1}]}'},
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 5,
            }
            return _FakeResponse(json.dumps(reply).encode("utf-8"))

        schema = {"type": "object", "properties": {"items": {"type": "array"}}}
        response = ResponsesTransport(settings, opener=opener).create(
            {
                "model": settings.model,
                "reasoning": {"effort": "low"},
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": "규칙"}]},
                    {"role": "user", "content": [{"type": "input_text", "text": "표"}]},
                ],
                "text": {"format": {"type": "json_schema", "name": "x", "strict": True, "schema": schema}},
                "max_output_tokens": 2000,
            }
        )

        self.assertEqual(sent["url"], "http://127.0.0.1:11434/api/chat")
        body = sent["body"]
        self.assertEqual(body["messages"], [
            {"role": "system", "content": "규칙"},
            {"role": "user", "content": "표"},
        ])
        self.assertEqual(body["format"], schema)
        self.assertFalse(body["stream"])
        self.assertEqual(body["options"]["num_predict"], 2000)
        self.assertGreaterEqual(body["options"]["num_ctx"], 2048)
        self.assertEqual(parse_responses_json(response), {"items": [{"id": 1}]})
        self.assertEqual(response["usage"]["total_tokens"], 17)


if __name__ == "__main__":
    unittest.main()
