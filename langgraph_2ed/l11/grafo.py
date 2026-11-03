"""Worker do ensaio. O único estado que sobrevive é o salvo em disco ou no destino."""
from contextlib import contextmanager
import sqlite3
from typing import TypedDict
from urllib.error import URLError
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from .destino import digest, requisicao


class Estado(TypedDict, total=False):
    pedido: dict
    chave: str
    digest: str
    voto: dict
    fase: str
    recibo: str
    origem: str


def preparar(s):
    return {"chave": "aurora-" + s["pedido"]["intencao"],
            "digest": digest(s["pedido"]), "fase": "revisao"}


def revisar(s):
    voto = interrupt({"pedido": s["pedido"], "chave": s["chave"], "digest": s["digest"]})
    valido = (isinstance(voto, dict) and voto.get("autorizar") is True and
              voto.get("chave") == s["chave"] and voto.get("digest") == s["digest"])
    return {"voto": voto, "fase": "autorizada" if valido else "recusada"}


def finalizar(s, chave, corpo, origem):
    if (corpo.get("chave") != chave or corpo.get("digest") != s["digest"]
            or not corpo.get("recibo")):
        return {"fase": "conflito"}
    return {"fase": "confirmada", "recibo": corpo["recibo"], "origem": origem}


@contextmanager
def abrir(pasta, url, variante="estavel", janela="", retomada=False, marcado=None):
    def barreira():
        marcado.set()
        # O controlador só mata o handle do worker criado para esta trajetória.
        from threading import Event
        if not Event().wait(60):
            raise TimeoutError("controlador não atingiu a barreira")

    def despachar(s):
        chave = s["chave"]
        if retomada and variante == "mutante":
            chave += "-retry"
        try:
            status, res = requisicao(url, "/recibo/" + chave)
            if status == 200:
                return finalizar(s, chave, res, "consulta")
            if status != 404:
                return {"fase": "desconhecida"}
            if janela == "antes":
                barreira()
            reter = janela in ("commit", "timeout")
            status, res = requisicao(url, "/creditos",
                                     {"chave": chave, "pedido": s["pedido"],
                                      "reter_resposta": reter},
                                     timeout=0.5 if janela == "timeout" else 30)
            if status == 409:
                return {"fase": "conflito"}
            if status not in (200, 201):
                return {"fase": "desconhecida"}
            confirmado = finalizar(s, chave, res, "resposta")
            if janela == "resposta" and confirmado["fase"] == "confirmada":
                barreira()
            return confirmado
        except (TimeoutError, URLError, ConnectionError):
            return {"fase": "desconhecida"}

    def triagem(s):
        escolha = interrupt({"fase": s["fase"], "chave": s["chave"],
                             "acao": "reconciliar ou manter pendente"})
        return {"fase": "consultar" if escolha == "reconciliar" else "pendente_manual"}

    g = StateGraph(Estado)
    for f in (preparar, revisar, despachar, triagem):
        g.add_node(f.__name__, f)
    g.add_edge(START, "preparar")
    g.add_edge("preparar", "revisar")
    g.add_conditional_edges("revisar", lambda s: "despachar" if s["fase"] == "autorizada" else END)
    g.add_conditional_edges("despachar", lambda s: "triagem" if s["fase"] == "desconhecida" else END)
    g.add_conditional_edges("triagem", lambda s: "despachar" if s["fase"] == "consultar" else END)
    con = sqlite3.connect(pasta / "grafo.sqlite", check_same_thread=False)
    try:
        yield g.compile(checkpointer=SqliteSaver(con))
    finally:
        con.close()


def config(ident):
    return {"configurable": {"thread_id": ident}}


def executar(pasta, url, ident, variante, janela, retomada, voto, marcado):
    with abrir(pasta, url, variante, janela, retomada, marcado) as g:
        entrada = Command(resume=voto) if voto is not None else None
        g.invoke(entrada, config(ident), durability="sync")
