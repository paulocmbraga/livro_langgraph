"""Descrição livre -> proposta tipada; nenhuma ação é executada."""
from dataclasses import dataclass
import json
from typing import Annotated, Literal, TypedDict
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from exemplos.parte2.modelos import Modelo, Roteiro, FalhaModelo


# trecho:contratos
class Pedido(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: str = Field(pattern=r"^A-\d+$")
    descricao: str = Field(min_length=1, max_length=2000)


class Proposta(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    tipo: Literal["falha", "orientacao", "mudanca"]
    usuarios: int = Field(ge=0, le=10000)
    justificativa: str = Field(min_length=1, max_length=240)


class Estado(TypedDict, total=False):
    pedido: dict
    mensagens: Annotated[list[AnyMessage], add_messages]
    resposta: AIMessage
    proposta: dict | None
    motivo: str
    registro: dict


@dataclass(frozen=True)
class Contexto:
    modelo: Modelo
# fim:contratos


# trecho:nos
def inferir(estado: Estado, runtime: Runtime[Contexto]):
    try:
        resposta = runtime.context.modelo.invoke(
            estado["mensagens"], Proposta.model_json_schema())
    except FalhaModelo as erro:
        return {"motivo": str(erro), "proposta": None}
    return {
        "resposta": resposta, "mensagens": [resposta],
        "registro": {"conteudo": resposta.content,
                     "configuracao": resposta.response_metadata,
                     "uso": resposta.usage_metadata},
    }


def validar(estado: Estado):
    if estado.get("motivo"):
        return {}
    resposta = estado["resposta"]
    if resposta.response_metadata.get("fim") == "length":
        return {"motivo": "truncada", "proposta": None}
    if (not isinstance(resposta.content, str) or resposta.tool_calls
            or resposta.invalid_tool_calls):
        return {"motivo": "formato_inesperado", "proposta": None}
    try:
        proposta = Proposta.model_validate_json(resposta.content)
    except ValidationError:
        return {"motivo": "estrutura_invalida", "proposta": None}
    if not proposta.justificativa.strip():
        return {"motivo": "justificativa_vazia", "proposta": None}
    return {"motivo": "proposta_valida", "proposta": proposta.model_dump()}
# fim:nos


# trecho:grafo
def criar_grafo():
    grafo = StateGraph(Estado, context_schema=Contexto)
    grafo.add_node("inferir", inferir)
    grafo.add_node("validar", validar)
    grafo.add_edge(START, "inferir")
    grafo.add_edge("inferir", "validar")
    grafo.add_edge("validar", END)
    return grafo.compile()


def executar(pedido, modelo):
    entrada = Pedido.model_validate(pedido)
    if not entrada.descricao.strip():
        raise ValueError("descricao_vazia")
    instrucoes = (
        "Classifique o chamado da Aurora. Falha: serviço deixou de "
        "funcionar; orientação: dúvida; mudança: alteração solicitada. "
        "Extraia a quantidade explicitamente informada; não invente. "
        "Se faltar quantidade, não produza proposta e peça esclarecimento. "
        "A resposta esperada, quando possível, segue este JSON Schema: "
        + json.dumps(Proposta.model_json_schema(), ensure_ascii=False)
    )
    mensagens = [SystemMessage(content=instrucoes, id="instrucao"),
                 HumanMessage(content=entrada.descricao, id=entrada.id)]
    return criar_grafo().invoke(
        {"pedido": entrada.model_dump(), "mensagens": mensagens,
         "motivo": "", "proposta": None},
        context=Contexto(modelo),
    )
# fim:grafo


if __name__ == "__main__":
    modelo = Roteiro([AIMessage(content=json.dumps({
        "tipo": "falha", "usuarios": 80,
        "justificativa": "Portal indisponível para 80 pessoas.",
    }, ensure_ascii=False))])
    resultado = executar(
        {"id": "A-17", "descricao": "O portal parou para 80 pessoas."},
        modelo,
    )
    print(json.dumps({k: resultado[k] for k in ("motivo", "proposta", "registro")},
                     ensure_ascii=False, indent=2))
