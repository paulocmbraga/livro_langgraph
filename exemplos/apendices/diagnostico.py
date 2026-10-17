"""Falhas deliberadas e reparos pequenos, sem alterar a aplicação Aurora."""
import json
import operator
from typing import Annotated, TypedDict
from langgraph.errors import GraphRecursionError, InvalidUpdateError
from langgraph.graph import StateGraph, START, END


class Simples(TypedDict):
    valores: list[str]


class Agregado(TypedDict):
    valores: Annotated[list[str], operator.add]


# trecho:concorrencia
def paralelo(com_reducer):
    g = StateGraph(Agregado if com_reducer else Simples)
    g.add_node("a", lambda s: {"valores": ["a"]})
    g.add_node("b", lambda s: {"valores": ["b"]})
    g.add_edge(START, "a")
    g.add_edge(START, "b")
    g.add_edge("a", END)
    g.add_edge("b", END)
    return g.compile().invoke({"valores": []})
# fim:concorrencia


class Contador(TypedDict):
    passos: int


# trecho:termino
def ciclo(com_termino):
    g = StateGraph(Contador)
    g.add_node("avancar", lambda s: {"passos": s["passos"] + 1})
    g.add_edge(START, "avancar")
    g.add_conditional_edges(
        "avancar",
        lambda s: END if com_termino and s["passos"] >= 3 else "avancar",
    )
    return g.compile().invoke({"passos": 0}, {"recursion_limit": 6})
# fim:termino


def demonstrar():
    saida = {}
    for nome, executar, erro in (
        ("sem_reducer", lambda: paralelo(False), InvalidUpdateError),
        ("sem_termino", lambda: ciclo(False), GraphRecursionError),
    ):
        try:
            executar()
        except erro as exc:
            saida[nome] = type(exc).__name__
        else:
            raise AssertionError("Falha esperada não ocorreu: " + nome)
    saida["com_reducer"] = sorted(paralelo(True)["valores"])
    saida["com_termino"] = ciclo(True)["passos"]
    return saida


if __name__ == "__main__":
    print(json.dumps(demonstrar(), ensure_ascii=False, indent=2))
