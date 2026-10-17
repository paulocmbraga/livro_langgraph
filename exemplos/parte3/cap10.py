"""Revisão vinculada, intenção e confirmação de efeito local."""
from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, TypedDict
from pydantic import BaseModel, ConfigDict, Field
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from .cap09 import configuracao
from .destino import Destino, Diario, digest, RespostaPerdida, QuedaSimulada


# trecho:contratos
class Proposta(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    operacao: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,99}$")
    organizacao: Literal["aurora"]
    chamado_id: Literal["A-17"]
    novo_status: Literal["em_analise", "aberto"]


class Decisao(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    aceitar: bool
    operacao: str
    digest: str


class Estado(TypedDict, total=False):
    proposta: dict
    aprovacao: dict | None
    situacao: str
    recibo: dict | None


@dataclass
class Contexto:
    destino: Destino
    diario: Diario
    revisor: str = "ana"
    pode_aprovar: bool = True
    falha: str = ""
    consulta_disponivel: bool = True
# fim:contratos


def proposta_padrao(operacao="op-001"):
    return {"operacao": operacao, "organizacao": "aurora",
            "chamado_id": "A-17", "novo_status": "em_analise"}


# trecho:revisao
def revisar(estado: Estado, runtime: Runtime[Contexto]):
    ctx = runtime.context
    proposta = Proposta.model_validate(estado["proposta"]).model_dump()
    ctx.destino.evento("revisao")
    resposta = interrupt({"proposta": proposta, "digest": digest(proposta)})
    decisao = Decisao.model_validate(resposta)
    if (not ctx.pode_aprovar or not ctx.revisor.strip()
            or decisao.operacao != proposta["operacao"]
            or decisao.digest != digest(proposta)):
        return {"aprovacao": None, "situacao": "recusada"}
    if not decisao.aceitar:
        return {"aprovacao": None, "situacao": "rejeitada"}
    return {"aprovacao": {"revisor": ctx.revisor, "digest": decisao.digest,
                          "operacao": decisao.operacao},
            "situacao": "aprovada"}
# fim:revisao


# trecho:conciliacao
def conciliar(ctx, proposta):
    chave = proposta["operacao"]
    registro = ctx.diario.registrar(proposta)
    if registro["situacao"] == "confirmed":
        return {"situacao": "confirmed",
                "recibo": json.loads(registro["recibo"])}
    try:
        resultado = ctx.destino.consultar(
            chave, digest(proposta), disponivel=ctx.consulta_disponivel)
    except RespostaPerdida:
        resultado = {"situacao": "unknown"}
    if resultado["situacao"] == "confirmed":
        ctx.diario.marcar(chave, "confirmed", resultado["recibo"])
        return resultado
    ctx.diario.marcar(chave, "unknown")
    return {"situacao": "unknown", "recibo": None}
# fim:conciliacao


# trecho:efeito
def executar_efeito(estado: Estado, runtime: Runtime[Contexto]):
    ctx = runtime.context
    proposta = Proposta.model_validate(estado["proposta"]).model_dump()
    aprovacao = estado.get("aprovacao") or {}
    if (not ctx.pode_aprovar or aprovacao.get("digest") != digest(proposta)
            or aprovacao.get("operacao") != proposta["operacao"]):
        return {"situacao": "recusada", "recibo": None}
    intencao = ctx.diario.registrar(proposta)
    if intencao["situacao"] == "confirmed":
        return {"situacao": "confirmed",
                "recibo": json.loads(intencao["recibo"])}
    if intencao["situacao"] in {"sent", "unknown"}:
        return conciliar(ctx, proposta)
    ctx.diario.marcar(proposta["operacao"], "sent")
    try:
        recibo = ctx.destino.aplicar(
            proposta, falha=ctx.falha if ctx.falha != "queda" else "")
    except RespostaPerdida:
        ctx.diario.marcar(proposta["operacao"], "unknown")
        return {"situacao": "unknown", "recibo": None}
    if ctx.falha == "queda":
        raise QuedaSimulada("destino_confirmou_antes_do_checkpoint")
    if ctx.falha == "encerrar_processo":
        # Usado somente pelo subprocesso descartável do laboratório L10.
        import os
        os._exit(23)
    ctx.diario.marcar(proposta["operacao"], "confirmed", recibo)
    return {"situacao": "confirmed", "recibo": recibo}
# fim:efeito


# trecho:grafo
def criar_grafo(checkpointer):
    grafo = StateGraph(Estado, context_schema=Contexto)
    grafo.add_node("revisar", revisar)
    grafo.add_node("executar", executar_efeito)
    grafo.add_edge(START, "revisar")
    grafo.add_conditional_edges(
        "revisar",
        lambda e: "executar" if e["situacao"] == "aprovada" else "fim",
        {"executar": "executar", "fim": END})
    grafo.add_edge("executar", END)
    return grafo.compile(checkpointer=checkpointer)


def aprovar(proposta, aceitar=True):
    return Command(resume={"aceitar": aceitar,
                           "operacao": proposta["operacao"],
                           "digest": digest(proposta)})
# fim:grafo


def executar():
    with TemporaryDirectory() as pasta:
        ctx = Contexto(Destino(pasta), Diario(pasta))
        with SqliteSaver.from_conn_string(str(Path(pasta)/"grafo.sqlite")) as saver:
            grafo = criar_grafo(saver)
            config = configuracao("aurora:operacao:01")
            proposta = proposta_padrao()
            grafo.invoke({"proposta": proposta}, config,
                         context=ctx, durability="sync")
            resultado = grafo.invoke(aprovar(proposta), config,
                                     context=ctx, durability="sync")
            return {"situacao": resultado["situacao"],
                    **ctx.destino.contadores()}


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
