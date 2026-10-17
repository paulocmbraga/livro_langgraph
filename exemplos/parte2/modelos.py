"""Fronteira de inferência: roteiro local e adaptador Ollama explícito."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol
import httpx
from langchain_core.messages import AIMessage, BaseMessage


class FalhaModelo(RuntimeError):
    pass


class Modelo(Protocol):
    def invoke(self, mensagens: list[BaseMessage], esquema=None) -> AIMessage:
        ...


@dataclass
class Roteiro:
    respostas: list[AIMessage]
    chamadas: int = 0

    def invoke(self, mensagens, esquema=None):
        if self.chamadas >= len(self.respostas):
            raise FalhaModelo("roteiro_esgotado")
        resposta = deepcopy(self.respostas[self.chamadas])
        self.chamadas += 1
        resposta.response_metadata.setdefault("origem", "roteiro")
        resposta.response_metadata.setdefault("modelo", "roteiro-v1")
        return resposta


# trecho:ollama
@dataclass
class OllamaLocal:
    modelo: str
    timeout: float = 60.0
    transporte: object = None

    def invoke(self, mensagens, esquema=None):
        papeis = {"system": "system", "human": "user", "ai": "assistant"}
        if any(m.type not in papeis or not isinstance(m.content, str)
               for m in mensagens):
            raise FalhaModelo("mensagem_nao_suportada")
        corpo = {
            "model": self.modelo,
            "messages": [{"role": papeis[m.type], "content": m.content}
                         for m in mensagens],
            "stream": False,
            "options": {"temperature": 0, "num_predict": 512},
        }
        if esquema is not None:
            corpo["format"] = esquema
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False,
                              transport=self.transporte) as cliente:
                resposta = cliente.post(
                    "http://127.0.0.1:11434/api/chat", json=corpo)
                resposta.raise_for_status()
                dados = resposta.json()
        except (httpx.HTTPError, ValueError) as erro:
            raise FalhaModelo("transporte_ou_json") from erro
        if not isinstance(dados, dict) or dados.get("done") is not True:
            raise FalhaModelo("resposta_incompleta")
        mensagem = dados.get("message", {})
        if not isinstance(mensagem, dict) or mensagem.get("role") != "assistant":
            raise FalhaModelo("papel_invalido")
        texto = mensagem.get("content")
        if not isinstance(texto, str):
            raise FalhaModelo("conteudo_invalido")
        uso = None
        entrada, saida = dados.get("prompt_eval_count"), dados.get("eval_count")
        if all(type(n) is int and n >= 0 for n in (entrada, saida)):
            uso = {"input_tokens": entrada, "output_tokens": saida,
                   "total_tokens": entrada + saida}
        return AIMessage(
            content=texto, usage_metadata=uso,
            response_metadata={
                "origem": "ollama_local",
                "modelo": dados.get("model"),
                "fim": dados.get("done_reason"),
                "duracao_ns": dados.get("total_duration"),
                "temperatura": 0, "limite_saida": 512,
            },
        )
# fim:ollama
