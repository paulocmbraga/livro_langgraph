"""Instrumentação opcional: ordem dos produtores e momento de consumo."""
import operator
import threading
import time
from typing import Annotated, TypedDict
from langgraph.graph import END, START, StateGraph
from exemplos.cap04 import Documento, FONTES
from exemplos.cap04_distribuicao import unir_documentos


def comparar_atrasos(atrasos: dict[str, float], agregar: bool = True) -> dict:
    class Acumulado(TypedDict):
        documentos: Annotated[list[Documento], operator.add]

    class Simples(TypedDict):
        documentos: list[Documento]

    registro, trava, barreira = [], threading.Lock(), threading.Barrier(2)

    def registrar(nome, evento):
        with trava:
            registro.append({"fonte": nome, "evento": evento})

    def produtor(nome):
        def consultar(estado):
            registrar(nome, "inicio")
            barreira.wait(timeout=5)
            time.sleep(atrasos[nome])
            registrar(nome, "fim")
            return {"documentos": [dict(FONTES[nome])]}
        return consultar

    construtor = StateGraph(Acumulado if agregar else Simples)
    for nome in FONTES:
        construtor.add_node(nome, produtor(nome))
        construtor.add_edge(START, nome)
        construtor.add_edge(nome, END)
    from langgraph.errors import InvalidUpdateError
    try:
        saida = construtor.compile().invoke({"documentos": []}, {"max_concurrency": 2})
        return {"documentos": saida["documentos"], "eventos": registro}
    except InvalidUpdateError:
        if agregar:
            raise
        return {"erro": "InvalidUpdateError", "eventos": registro}


def comparar_juncao(esperar_todos: bool) -> dict:
    class Estado(TypedDict):
        documentos: Annotated[list[Documento], unir_documentos]
        leituras: Annotated[list[int], operator.add]

    def manual(estado):
        return {"documentos": [dict(FONTES["manual"])]}

    def preparar_status(estado):
        return {}

    def status(estado):
        return {"documentos": [dict(FONTES["status"])]}

    def consumir(estado):
        return {"leituras": [len(estado["documentos"])]}

    construtor = StateGraph(Estado)
    for nome, no in (("manual", manual), ("preparar_status", preparar_status),
                     ("status", status), ("consumir", consumir)):
        construtor.add_node(nome, no)
    construtor.add_edge(START, "manual")
    construtor.add_edge(START, "preparar_status")
    construtor.add_edge("preparar_status", "status")
    # trecho:juncao
    if esperar_todos:
        construtor.add_edge(["manual", "status"], "consumir")
    else:
        construtor.add_edge("manual", "consumir")
        construtor.add_edge("status", "consumir")
    # fim:juncao
    construtor.add_edge("consumir", END)
    return construtor.compile().invoke({"documentos": [], "leituras": []})
