"""Servidor LLM simulado (API compatible con OpenAI) para pruebas, sin red."""

import json

import httpx2

from apps.llm.client import LLMConfig, OpenAICompatibleProvider


def chat_response(content: str) -> dict:
    return {
        "id": "chatcmpl-prueba",
        "object": "chat.completion",
        "created": 0,
        "model": "modelo-prueba",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class FakeLLMServer:
    """Responde a /models y /chat/completions; registra las peticiones recibidas."""

    def __init__(self, models=("modelo-prueba",), chat_content="OK", models_status=200):
        self.models = list(models)
        self.chat_content = chat_content
        self.models_status = models_status
        self.requests: list[httpx2.Request] = []
        self.error: Exception | None = None
        self.status: int | None = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.status is not None:
            return httpx2.Response(self.status, json={"error": {"message": "fallo simulado"}})
        if request.url.path.endswith("/models"):
            if self.models_status != 200:
                return httpx2.Response(self.models_status, json={"error": {"message": "no"}})
            data = [
                {"id": m, "object": "model", "created": 0, "owned_by": "x"} for m in self.models
            ]
            return httpx2.Response(200, json={"object": "list", "data": data})
        if request.url.path.endswith("/chat/completions"):
            content = self.chat_content
            if callable(content):  # respuesta según el texto enviado
                body = json.loads(request.content)
                content = content(body["messages"][-1]["content"])
            return httpx2.Response(200, json=chat_response(content))
        return httpx2.Response(404, json={"error": {"message": "ruta desconocida"}})

    def provider(self, **config) -> OpenAICompatibleProvider:
        defaults = {"base_url": "http://localhost:11434/v1", "model": "modelo-prueba"}
        defaults.update(config)
        client = httpx2.Client(transport=httpx2.MockTransport(self.handler))
        return OpenAICompatibleProvider(LLMConfig(**defaults), http_client=client, max_retries=0)

    def last_json(self) -> dict:
        return json.loads(self.requests[-1].content)


def contract_ai_answer(user_text: str) -> str:
    """Modelo simulado: devuelve las entidades del contrato de ejemplo que vea en el texto."""
    candidates = [
        ("NOMBRE", "Juan Pérez"),
        ("NOMBRE", "María López"),
        ("NOMBRE", "Juan Carlos Pérez Gómez"),
        ("EMPRESA", "Soluciones Andinas S.A.S."),
        ("NOMBRE", "Bogotá"),  # falso positivo: el usuario lo desmarca
    ]
    found = [{"tipo": t, "valor": v} for t, v in candidates if v in user_text]
    return json.dumps({"entidades": found}, ensure_ascii=False)
