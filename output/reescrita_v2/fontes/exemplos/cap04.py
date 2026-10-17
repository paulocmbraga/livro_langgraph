"""Capítulo 4: um fan-out fixo e uma junção explícita."""
# trecho:basico
import operator
from typing import Annotated, TypedDict
from langgraph.graph import END, START, StateGraph


class Documento(TypedDict):
    documento: str
    revisao: int
    texto: str


FONTES = {
    "manual": {"documento": "D-10", "revisao": 2,
               "texto": "Verificar a disponibilidade antes de redefinir o acesso."},
    "status": {"documento": "D-20", "revisao": 1,
               "texto": "Servico em manutencao programada."},
}


class Pesquisa(TypedDict, total=False):
    documentos: Annotated[list[Documento], operator.add]
    resumo: str


def buscar_manual(estado: Pesquisa) -> dict:
    return {"documentos": [dict(FONTES["manual"])]}


def buscar_status(estado: Pesquisa) -> dict:
    return {"documentos": [dict(FONTES["status"])]}


def sintetizar(estado: Pesquisa) -> dict:
    nomes = sorted(item["documento"] for item in estado["documentos"])
    return {"resumo": "Documentos consultados: " + ", ".join(nomes)}


def criar_grafo():
    construtor = StateGraph(Pesquisa)
    construtor.add_node("manual", buscar_manual)
    construtor.add_node("status", buscar_status)
    construtor.add_node("sintetizar", sintetizar)
    construtor.add_edge(START, "manual")
    construtor.add_edge(START, "status")
    construtor.add_edge(["manual", "status"], "sintetizar")
    construtor.add_edge("sintetizar", END)
    return construtor.compile()


if __name__ == "__main__":
    print(criar_grafo().invoke({"documentos": []})["resumo"])
# fim:basico
