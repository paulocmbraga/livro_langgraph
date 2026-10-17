"""Especialista aninhado: projeção de estado e supervisão."""
from dataclasses import dataclass
import hashlib
import json
from typing import TypedDict
from langgraph.graph import START, END, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt, Command
from pydantic import BaseModel, ConfigDict, Field


class Consulta(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    pergunta: str = Field(min_length=1, max_length=200)
    organizacao: str = Field(min_length=1)


class Saida(TypedDict):
    resposta: str
    fonte: str | None
    situacao: str


class Interno(Saida, total=False):
    pergunta: str
    organizacao: str
    bruto: dict


@dataclass(frozen=True)
class Contexto:
    organizacao: str
    contadores: dict


def buscar(pergunta, organizacao):
    if organizacao == "aurora" and "vpn" in pergunta.casefold():
        return {"texto": "Instale Aurora Connect.", "fonte": "VPN-r2",
                "revisao": 2, "nota_interna": "triagem-sintetica"}
    return {}


def identidade_documento(bruto):
    return hashlib.sha256(json.dumps(
        bruto, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# trecho:especialista
def criar_especialista(pausar=True):
    def recuperar(s, runtime: Runtime[Contexto]):
        runtime.context.contadores["buscas"] += 1
        q = Consulta.model_validate({
            "pergunta": s["pergunta"], "organizacao": s["organizacao"]})
        if q.organizacao != runtime.context.organizacao:
            raise ValueError("escopo_divergente")
        return {"bruto": buscar(q.pergunta, q.organizacao)}
    def revisar(s, runtime: Runtime[Contexto]):
        runtime.context.contadores["revisoes"] += 1
        bruto = s["bruto"]
        if not bruto:
            return {"resposta": "", "fonte": None, "situacao": "insuficiente"}
        resumo = identidade_documento(bruto)
        if pausar:
            decisao = interrupt({"fonte": bruto["fonte"], "digest": resumo})
        else:
            decisao = {"aceitar": True, "digest": resumo}
        aceita = (isinstance(decisao, dict)
                  and decisao.get("aceitar") is True
                  and decisao.get("digest") == resumo)
        return {"resposta": bruto["texto"] if aceita else "",
                "fonte": bruto["fonte"] if aceita else None,
                "situacao": "resposta" if aceita else "recusada"}
    g = StateGraph(Interno, context_schema=Contexto, output_schema=Saida)
    g.add_node("recuperar", recuperar)
    g.add_node("revisar", revisar)
    g.add_edge(START, "recuperar")
    g.add_edge("recuperar", "revisar")
    g.add_edge("revisar", END)
    return g.compile()
# fim:especialista


# trecho:pai
class Pai(TypedDict, total=False):
    pergunta: str
    segredo_sintetico: str
    resultado: Saida
    publicado: dict


def criar_pai(saver, pausar=True):
    filho = criar_especialista(pausar)
    def consultar(s, runtime: Runtime[Contexto]):
        ctx = runtime.context
        ctx.contadores["entradas_pai"] += 1
        entrada = {"pergunta": s["pergunta"],
                   "organizacao": ctx.organizacao}
        saida = filho.invoke(entrada, context=ctx)
        return {"resultado": {k: saida[k] for k in Saida.__annotations__}}
    def publicar(s):
        return {"publicado": dict(s["resultado"])}
    g = StateGraph(Pai, context_schema=Contexto)
    g.add_node("consultar", consultar)
    g.add_node("publicar", publicar)
    g.add_edge(START, "consultar")
    g.add_edge("consultar", "publicar")
    g.add_edge("publicar", END)
    return g.compile(checkpointer=saver)
# fim:pai


# trecho:eventos
def eventos_publicos(eventos):
    permitidos = {"resposta", "fonte", "situacao"}
    for ns, atualizacao in eventos:
        if ns or "publicar" not in atualizacao:
            continue
        publico = atualizacao["publicar"]["publicado"]
        yield {k: publico[k] for k in permitidos}
# fim:eventos


def criar_contador(saver, persistente=False):
    class S(TypedDict, total=False):
        n: int
    filho = StateGraph(S)
    filho.add_node("somar", lambda s: {"n": s.get("n", 0) + 1})
    filho.add_edge(START, "somar")
    filho.add_edge("somar", END)
    sub = filho.compile(checkpointer=True if persistente else None)
    class P(TypedDict, total=False):
        resultado: int
    pai = StateGraph(P)
    pai.add_node("filho", lambda s: {"resultado": sub.invoke({})["n"]})
    pai.add_edge(START, "filho")
    pai.add_edge("filho", END)
    return pai.compile(checkpointer=saver)


def executar():
    from langgraph.checkpoint.memory import InMemorySaver
    contadores = {"entradas_pai": 0, "buscas": 0, "revisoes": 0}
    ctx = Contexto("aurora", contadores)
    g = criar_pai(InMemorySaver())
    cfg = {"configurable": {"thread_id": "consulta-15"}}
    pausa = g.invoke({"pergunta": "Como configurar VPN?",
                      "segredo_sintetico": "apenas-no-pai"}, cfg, context=ctx)
    pedido = pausa["__interrupt__"][0].value
    final = g.invoke(Command(resume={"aceitar": True,
                                     "digest": pedido["digest"]}),
                     cfg, context=ctx)
    return {"publicado": final["publicado"], "contadores": contadores}


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
