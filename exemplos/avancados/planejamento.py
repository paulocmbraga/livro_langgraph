"""Busca finita, observação, replanejamento e término explícito em LangGraph."""
from collections import deque
from dataclasses import dataclass, field
import operator
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END

ARESTAS = {
    "novo": [("diagnosticar", "diagnosticado")],
    "diagnosticado": [("corrigir", "corrigido"), ("contornar", "contornado")],
    "corrigido": [("testar", "testado")],
    "contornado": [("testar", "testado")],
    "testado": [],
}


# trecho:busca
def buscar(inicio, bloqueadas=(), limite=20):
    if type(limite) is not int or limite < 0:
        raise ValueError("limite_invalido")
    fila, vistos, expandidos = deque([(inicio, [])]), {inicio}, 0
    while fila:
        estado, caminho = fila.popleft()
        if estado == "testado":
            return {"motivo": "plano", "acoes": caminho, "expansoes": expandidos}
        if expandidos >= limite:
            return {"motivo": "busca_limitada", "acoes": [], "expansoes": expandidos}
        expandidos += 1
        for acao, destino in ARESTAS.get(estado, []):
            if acao not in bloqueadas and destino not in vistos:
                vistos.add(destino)
                fila.append((destino, caminho+[acao]))
    return {"motivo": "sem_caminho", "acoes": [], "expansoes": expandidos}
# fim:busca


@dataclass
class Ambiente:
    estado: str = "novo"
    revisao: int = 1
    indisponiveis: frozenset = frozenset()
    perder_retorno: bool = False
    efeitos: list = field(default_factory=list)

    def observar(self):
        return {"estado": self.estado, "revisao": self.revisao}

    def executar(self, acao, revisao):
        if revisao != self.revisao:
            return {"situacao": "obsoleto"}
        admissiveis = dict(ARESTAS.get(self.estado, []))
        if acao not in admissiveis:
            return {"situacao": "recusada"}
        if acao in self.indisponiveis:
            return {"situacao": "indisponivel"}
        self.estado, self.revisao = admissiveis[acao], self.revisao+1
        self.efeitos.append(acao)
        return {"situacao": "desconhecida" if self.perder_retorno else "confirmada"}


class Estado(TypedDict, total=False):
    observacao: dict
    plano: dict
    bloqueadas: list[str]
    tentativas: int
    planos: int
    motivo: str
    historico: Annotated[list[dict], operator.add]


# trecho:controlador
def criar_grafo(ambiente, max_chamadas=6, max_planos=6, planejador=buscar):
    for valor in (max_chamadas, max_planos):
        if type(valor) is not int or valor < 0:
            raise ValueError("orcamento_invalido")

    def observar(s):
        obs = ambiente.observar()
        motivo = "concluida" if obs["estado"] == "testado" else "planejar"
        return {"observacao": obs, "motivo": motivo}

    def planejar(s):
        if s["tentativas"] >= max_chamadas or s["planos"] >= max_planos:
            return {"motivo": "orcamento"}
        p = planejador(s["observacao"]["estado"], s["bloqueadas"])
        return {"plano": p, "planos": s["planos"]+1,
                "motivo": "executar" if p["motivo"] == "plano" else p["motivo"],
                "historico": [{"plano": p, "base": s["observacao"]}]}

    def executar(s):
        acoes = s["plano"].get("acoes", [])
        acao = acoes[0] if acoes else None
        # O planejador propõe; a fronteira mantém as precondições.
        retorno = ambiente.executar(acao, s["observacao"]["revisao"])
        situacao = retorno["situacao"]
        bloqueadas = s["bloqueadas"] + ([acao] if situacao == "indisponivel" else [])
        motivo = "observar" if situacao in ("confirmada", "indisponivel", "obsoleto") else situacao
        return {"tentativas": s["tentativas"]+1, "bloqueadas": bloqueadas,
                "motivo": motivo, "historico": [{"acao": acao, **retorno}]}

    g = StateGraph(Estado)
    for nome, no in (("observar", observar), ("planejar", planejar), ("executar", executar)):
        g.add_node(nome, no)
    g.add_edge(START, "observar")
    g.add_conditional_edges("observar", lambda s: "planejar" if s["motivo"] == "planejar" else END)
    g.add_conditional_edges("planejar", lambda s: "executar" if s["motivo"] == "executar" else END)
    g.add_conditional_edges("executar", lambda s: "observar" if s["motivo"] == "observar" else END)
    return g.compile()
# fim:controlador


def executar(ambiente=None, **opcoes):
    ambiente = ambiente or Ambiente()
    return criar_grafo(ambiente, **opcoes).invoke(
        {"bloqueadas": [], "tentativas": 0, "planos": 0, "historico": []},
        {"recursion_limit": 60})


def demonstrar():
    normal = executar()
    alternativo = executar(Ambiente(indisponiveis=frozenset({"corrigir"})))
    incerto = executar(Ambiente(perder_retorno=True))
    return {"normal": normal, "replanejamento": alternativo,
            "retorno_perdido": incerto, "modelo_real": False}
