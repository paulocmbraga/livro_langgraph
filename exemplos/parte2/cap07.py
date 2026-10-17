"""Ciclo limitado por trabalho, repetição, novidade e prazo cooperativo."""
from dataclasses import dataclass
import json
from time import monotonic
from typing import Annotated, Callable, TypedDict
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from exemplos.parte2.cap06 import BANCO, Escopo, despachar
from exemplos.parte2.modelos import Modelo, Roteiro, FalhaModelo


# trecho:estado
class RespostaFinal(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    chamado_id: str
    status: str = Field(min_length=1)


class Estado(TypedDict):
    mensagens: Annotated[list[AnyMessage], add_messages]
    alvo: str
    inicio: float
    modelos: int
    ferramentas: int
    assinaturas: list[str]
    evidencias: list[dict]
    sem_novidade: int
    motivo: str
    resolvida: bool


@dataclass(frozen=True)
class Limites:
    modelos: int = 4
    ferramentas: int = 3
    sem_novidade: int = 2
    segundos: float = 10.0

    def __post_init__(self):
        for n in (self.modelos, self.ferramentas, self.sem_novidade):
            if type(n) is not int or not 1 <= n <= 100:
                raise ValueError("limite_invalido")
        if not 0 < self.segundos <= 3600:
            raise ValueError("prazo_invalido")


@dataclass(frozen=True)
class Contexto:
    modelo: Modelo
    escopo: Escopo
    limites: Limites
    relogio: Callable[[], float] = monotonic
# fim:estado


# trecho:modelo
def modelar(estado: Estado, runtime: Runtime[Contexto]):
    ctx = runtime.context
    if ctx.relogio() - estado["inicio"] >= ctx.limites.segundos:
        return {"motivo": "prazo"}
    if estado["modelos"] >= ctx.limites.modelos:
        return {"motivo": "orcamento_modelo"}
    contador = estado["modelos"] + 1
    try:
        resposta = ctx.modelo.invoke(estado["mensagens"])
    except FalhaModelo:
        return {"modelos": contador, "motivo": "falha_modelo"}
    atualizacao = {"mensagens": [resposta], "modelos": contador}
    if ctx.relogio() - estado["inicio"] >= ctx.limites.segundos:
        return {**atualizacao, "motivo": "prazo"}
    if resposta.response_metadata.get("fim") == "length":
        return {**atualizacao, "motivo": "truncada"}
    if resposta.invalid_tool_calls or len(resposta.tool_calls) > 1:
        return {**atualizacao, "motivo": "protocolo_invalido"}
    if resposta.tool_calls:
        return atualizacao
    try:
        final = RespostaFinal.model_validate_json(resposta.content)
    except (ValidationError, TypeError):
        return {**atualizacao, "motivo": "inconclusiva"}
    confere = final.chamado_id == estado["alvo"] and any(
        e["id"] == final.chamado_id and e["status"] == final.status
        for e in estado["evidencias"])
    return {**atualizacao, "resolvida": confere,
            "motivo": "concluida" if confere else "sem_sustentacao"}
# fim:modelo


# trecho:ferramenta
def consultar_no(estado: Estado, runtime: Runtime[Contexto]):
    ctx = runtime.context
    chamada = estado["mensagens"][-1].tool_calls[0]
    identidade = chamada.get("id")
    if not isinstance(identidade, str) or not identidade.strip():
        return {"motivo": "protocolo_invalido"}
    assinatura = json.dumps(
        [chamada["name"], chamada["args"]], sort_keys=True)
    motivo = ""
    if ctx.relogio() - estado["inicio"] >= ctx.limites.segundos:
        motivo = "prazo"
    elif estado["ferramentas"] >= ctx.limites.ferramentas:
        motivo = "orcamento_ferramenta"
    elif assinatura in estado["assinaturas"]:
        motivo = "repeticao"
    if motivo:
        aviso = ToolMessage(content=json.dumps({"erro": motivo}),
                            tool_call_id=identidade, status="error")
        return {"motivo": motivo, "mensagens": [aviso]}
    mensagem, registro = despachar(chamada, ctx.escopo)
    evidencias = list(estado["evidencias"])
    dado = registro["resultado"].get("dados")
    novidade = dado is not None and dado not in evidencias
    if novidade:
        evidencias.append(dado)
    sem_novidade = 0 if novidade else estado["sem_novidade"] + 1
    motivo = ("sem_progresso" if sem_novidade >= ctx.limites.sem_novidade
              else "")
    if ctx.relogio() - estado["inicio"] >= ctx.limites.segundos:
        motivo = "prazo"
    return {
        "mensagens": [mensagem],
        "ferramentas": estado["ferramentas"] + 1,
        "assinaturas": estado["assinaturas"] + [assinatura],
        "evidencias": evidencias, "sem_novidade": sem_novidade,
        "motivo": motivo,
    }
# fim:ferramenta


# trecho:grafo
def criar_grafo():
    grafo = StateGraph(Estado, context_schema=Contexto)
    grafo.add_node("modelo", modelar)
    grafo.add_node("consulta", consultar_no)
    grafo.add_edge(START, "modelo")
    grafo.add_conditional_edges(
        "modelo", lambda e: "fim" if e["motivo"] else "consulta",
        {"fim": END, "consulta": "consulta"})
    grafo.add_conditional_edges(
        "consulta", lambda e: "fim" if e["motivo"] else "modelo",
        {"fim": END, "modelo": "modelo"})
    return grafo.compile()


def executar(modelo, limites=Limites(), relogio=monotonic, alvo="A-17"):
    estado = {
        "mensagens": [HumanMessage(
            content=f"Consulte o status do chamado {alvo}.")],
        "alvo": alvo, "inicio": relogio(), "modelos": 0,
        "ferramentas": 0, "assinaturas": [], "evidencias": [],
        "sem_novidade": 0, "motivo": "", "resolvida": False,
    }
    contexto = Contexto(
        modelo, Escopo("aurora", frozenset({"chamados:ler"})),
        limites, relogio)
    return criar_grafo().invoke(
        estado, {"recursion_limit": 2 * limites.modelos + 5},
        context=contexto)
# fim:grafo


def pedir(id="A-17", chamada="c1"):
    return AIMessage(content="", tool_calls=[{
        "name": "consultar_chamado", "args": {"chamado_id": id},
        "id": chamada, "type": "tool_call",
    }])


def resumir(resultado):
    return {k: resultado[k] for k in
            ("motivo", "resolvida", "modelos", "ferramentas")}


if __name__ == "__main__":
    modelo = Roteiro([pedir(), AIMessage(
        content='{"chamado_id":"A-17","status":"aberto"}')])
    print(json.dumps(resumir(executar(modelo)), ensure_ascii=False, indent=2))
