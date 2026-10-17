"""Capítulo 1: duas implementações de uma especificação de triagem."""
# trecho:programa
from typing import TypedDict
from langgraph.graph import END, START, StateGraph

FILAS = {
    "falha": "suporte",
    "orientacao": "conhecimento",
    "mudanca": "planejamento",
}


def prioridade(usuarios: int) -> str:
    if usuarios >= 50:
        return "P1"
    if usuarios > 0:
        return "P2"
    return "P3"


def por_funcao(chamado: dict) -> dict:
    return {
        "id": chamado["id"],
        "prioridade": prioridade(chamado["usuarios"]),
        "fila": FILAS[chamado["tipo"]],
    }


class Estado(TypedDict, total=False):
    id: str
    tipo: str
    usuarios: int
    prioridade: str
    resultado: dict


def avaliar(estado: Estado) -> dict:
    return {"prioridade": prioridade(estado["usuarios"])}


def encaminhar(estado: Estado) -> dict:
    return {"resultado": {
        "id": estado["id"],
        "prioridade": estado["prioridade"],
        "fila": FILAS[estado["tipo"]],
    }}


def criar_grafo():
    construtor = StateGraph(Estado)
    construtor.add_node("avaliar", avaliar)
    construtor.add_node("encaminhar", encaminhar)
    construtor.add_edge(START, "avaliar")
    construtor.add_edge("avaliar", "encaminhar")
    construtor.add_edge("encaminhar", END)
    return construtor.compile()


if __name__ == "__main__":
    entrada = {"id": "A-17", "tipo": "falha", "usuarios": 80}
    grafo = criar_grafo()
    print(por_funcao(entrada))
    print(grafo.invoke(entrada)["resultado"])
# fim:programa
