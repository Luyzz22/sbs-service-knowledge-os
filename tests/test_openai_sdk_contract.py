"""Exercise the installed Azure SDK through its real HTTP serialization boundary."""

import json
import unittest
from functools import partial
from unittest.mock import patch

import httpx
from openai import AzureOpenAI

from hydraulikdoc.azure_ai import AzureCredentialHeaders, AzureOpenAIModels, AzureServiceError
from hydraulikdoc.config import AppSettings


class AzureSDKContractTests(unittest.TestCase):
    def model(self, handler):
        settings = AppSettings.from_environment(
            {
                "APP_ENV": "test",
                "AZURE_USE_MANAGED_IDENTITY": "false",
                "AZURE_OPENAI_ENDPOINT": "https://synthetic.openai.azure.com",
                "AZURE_OPENAI_KEY": "synthetic-test-key",
                "AZURE_OPENAI_CHAT_DEPLOYMENT": "test-chat",
                "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "test-embedding",
                "AZURE_EMBEDDING_DIMENSIONS": "1536",
            }
        )
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch("openai.AzureOpenAI", wraps=partial(AzureOpenAI, http_client=client)):
            model = AzureOpenAIModels(settings, AzureCredentialHeaders(settings))
        self.addCleanup(model._client.close)
        return model

    def test_chat_serializes_request_and_parses_real_sdk_response(self):
        def handler(request):
            self.assertEqual(request.url.path, "/openai/deployments/test-chat/chat/completions")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "test-chat")
            self.assertEqual(body["max_tokens"], 1400)
            self.assertIn("synthetic evidence", body["messages"][1]["content"])
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": " Answer "}}]})

        self.assertEqual(self.model(handler).answer("Question", "synthetic evidence", "de"), "Answer")

    def test_embeddings_preserve_input_and_restore_response_order(self):
        def handler(request):
            self.assertEqual(request.url.path, "/openai/deployments/test-embedding/embeddings")
            body = json.loads(request.content)
            self.assertEqual(body["input"], ["first", "second"])
            self.assertEqual(body["dimensions"], 1536)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.0] * 1536},
                        {"index": 0, "embedding": [1.0] * 1536},
                    ]
                },
            )

        self.assertEqual(self.model(handler).embeddings(["first", "second"]), ((1.0,) * 1536, (0.0,) * 1536))

    def test_empty_model_answer_is_rejected(self):
        model = self.model(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}))
        with self.assertRaises(AzureServiceError):
            model.answer("Question", "synthetic evidence", "de")
