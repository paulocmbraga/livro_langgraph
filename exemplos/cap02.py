"""Capítulo 2: validação explícita e contexto por invocação."""
# trecho:tipos
from dataclasses import dataclass
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from exemplos.cap01 import FILAS


class Entrada(TypedDict):
    id: str
    tipo: str
    usuarios: int
    descricao: str


class Saida(TypedDict):
    id: str
    prioridade: str
    fila: str


class Trabalho(Entrada, total=False):
    prioridade: str
    fila: str
    diagnostico: str


@dataclass(frozen=True)
class Contexto:
    limite_p1: int = 50

    def __post_init__(self):
        if type(self.limite_p1) is not int or self.limite_p1 < 1:
            raise ValueError("limite_p1 deve ser inteiro positivo")


class ErroContrato(ValueError):
    def __init__(self, campo: str, fronteira: str = "entrada"):
        self.campo = campo
        self.fronteira = fronteira
        super().__init__(f"{fronteira}:{campo}")
# fim:tipos


# trecho:validacao
def validar_entrada(valor: object) -> Entrada:
    if type(valor) is not dict:
        raise ErroContrato("objeto")
    if set(valor) != {"id", "tipo", "usuarios", "descricao"}:
        raise ErroContrato("campos")
    for campo in ("id", "tipo", "descricao"):
        if type(valor[campo]) is not str or not valor[campo].strip():
            raise ErroContrato(campo)
    if valor["id"] != valor["id"].strip():
        raise ErroContrato("id")
    if valor["tipo"] not in FILAS:
        raise ErroContrato("tipo")
    if type(valor["usuarios"]) is not int or valor["usuarios"] < 0:
        raise ErroContrato("usuarios")
    return {**valor, "descricao": valor["descricao"].strip()}


def prioridade_para(usuarios: int, contexto: Contexto) -> str:
    if usuarios >= contexto.limite_p1:
        return "P1"
    return "P2" if usuarios > 0 else "P3"


def validar_saida(valor: object, entrada: Entrada, contexto: Contexto) -> Saida:
    if type(valor) is not dict or set(valor) != {"id", "prioridade", "fila"}:
        raise ErroContrato("campos", "saida")
    esperado = {
        "id": entrada["id"],
        "prioridade": prioridade_para(entrada["usuarios"], contexto),
        "fila": FILAS[entrada["tipo"]],
    }
    for campo, conteudo in esperado.items():
        if valor[campo] != conteudo:
            raise ErroContrato(campo, "saida")
    return dict(valor)
# fim:validacao


# trecho:execucao
def calcular(estado: Trabalho, runtime: Runtime[Contexto]) -> dict:
    return {
        "prioridade": prioridade_para(estado["usuarios"], runtime.context),
        "fila": FILAS[estado["tipo"]],
        "diagnostico": f"limite={runtime.context.limite_p1}",
    }


def criar_grafo(no=calcular):
    construtor = StateGraph(
        Trabalho, input_schema=Entrada, output_schema=Saida,
        context_schema=Contexto,
    )
    construtor.add_node("calcular", no)
    construtor.add_edge(START, "calcular")
    construtor.add_edge("calcular", END)
    return construtor.compile()


def executar(valor: object, contexto: Contexto, grafo=None) -> Saida:
    entrada = validar_entrada(valor)
    grafo = criar_grafo() if grafo is None else grafo
    saida = grafo.invoke(entrada, context=contexto)
    return validar_saida(saida, entrada, contexto)


if __name__ == "__main__":
    chamado = {"id": "A-17", "tipo": "falha", "usuarios": 80,
               "descricao": "  Portal indisponivel  "}
    grafo = criar_grafo()
    print(executar(chamado, Contexto(50), grafo))
    print(executar(chamado, Contexto(100), grafo))
# fim:execucao
