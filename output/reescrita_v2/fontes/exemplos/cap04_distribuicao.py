"""Complemento do capítulo 4: identidade, conflito e distribuição dinâmica."""
# trecho:reducer
from typing import Annotated, TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from exemplos.cap04 import Documento, FONTES


def unir_documentos(atual: list[Documento], novos: list[Documento]) -> list[Documento]:
    indice = {}
    for item in [*atual, *novos]:
        if type(item) is not dict or set(item) != {"documento", "revisao", "texto"}:
            raise ValueError("formato de documento invalido")
        if (type(item["documento"]) is not str or not item["documento"].strip()
                or type(item["texto"]) is not str or not item["texto"].strip()
                or type(item["revisao"]) is not int or item["revisao"] < 1):
            raise ValueError("conteudo de documento invalido")
        chave = (item["documento"], item["revisao"])
        if chave in indice and indice[chave] != item:
            raise ValueError("mesma revisao com conteudos diferentes")
        indice[chave] = dict(item)
    return [indice[chave] for chave in sorted(indice)]
# fim:reducer


# trecho:send
class Lote(TypedDict):
    fontes: list[str]
    documentos: Annotated[list[Documento], unir_documentos]


class Pacote(TypedDict):
    fonte: str


def preparar(estado: Lote) -> dict:
    fontes = estado["fontes"]
    if type(fontes) is not list or len(fontes) > 10:
        raise ValueError("lote deve ser uma lista de ate dez fontes")
    if any(type(nome) is not str or nome not in FONTES for nome in fontes):
        raise ValueError("fonte desconhecida")
    return {}


def distribuir(estado: Lote):
    if not estado["fontes"]:
        return END
    return [Send("buscar", {"fonte": nome}) for nome in estado["fontes"]]


def buscar(pacote: Pacote) -> dict:
    return {"documentos": [dict(FONTES[pacote["fonte"]])]}


def criar_grafo(no_busca=buscar):
    construtor = StateGraph(Lote)
    construtor.add_node("preparar", preparar)
    construtor.add_node("buscar", no_busca)
    construtor.add_edge(START, "preparar")
    construtor.add_conditional_edges("preparar", distribuir)
    construtor.add_edge("buscar", END)
    return construtor.compile()


if __name__ == "__main__":
    entrada = {"fontes": ["manual", "status", "manual"], "documentos": []}
    print(criar_grafo().invoke(entrada)["documentos"])
# fim:send
