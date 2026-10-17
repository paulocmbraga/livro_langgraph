"""Capítulo 3: decisão, continuação e invariantes de conclusão."""
# trecho:estado
from dataclasses import dataclass
from typing import Literal
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command
from exemplos.cap02 import Entrada, ErroContrato, validar_entrada


@dataclass(frozen=True)
class Politica:
    permite_proposta: bool = False

    def __post_init__(self):
        if type(self.permite_proposta) is not bool:
            raise ValueError("permite_proposta deve ser booleano")


class Atendimento(Entrada, total=False):
    rota: str
    situacao: str
    resposta: str
    proposta: dict
    motivo: str


def escolher(entrada: Entrada, politica: Politica) -> str:
    if entrada["tipo"] == "falha":
        return "diagnosticar"
    if entrada["tipo"] == "orientacao":
        return "orientar"
    return "propor" if politica.permite_proposta else "recusar"
# fim:estado


# trecho:nos
def decidir(estado: Atendimento, runtime: Runtime[Politica]) -> dict:
    return {"rota": escolher(estado, runtime.context), "situacao": "em_andamento"}


def diagnosticar(estado: Atendimento) -> dict:
    return {"resposta": "Verifique o painel local de disponibilidade."}


def orientar(estado: Atendimento) -> dict:
    return {"resposta": "Consulte o procedimento de acesso da equipe."}


def finalizar(estado: Atendimento) -> dict:
    resposta = estado.get("resposta")
    if type(resposta) is not str or not resposta.strip():
        raise ErroContrato("resposta", "finalizacao")
    return {"situacao": "concluido"}


def propor(estado: Atendimento) -> dict:
    return {"situacao": "proposto", "proposta": {
        "chamado_id": estado["id"],
        "acao": "agendar_analise",
    }}


def recusar(estado: Atendimento) -> dict:
    return {"situacao": "recusado", "motivo": "Preparacao de propostas desabilitada."}
# fim:nos


# trecho:command
def decidir_com_command(estado: Atendimento, runtime: Runtime[Politica]) -> Command[
    Literal["diagnosticar", "orientar", "propor", "recusar"]
]:
    rota = escolher(estado, runtime.context)
    return Command(update={"rota": rota, "situacao": "em_andamento"}, goto=rota)
# fim:command


# trecho:topologia
def montar_grafo(estilo: str = "condicional"):
    if estilo not in {"condicional", "command"}:
        raise ValueError("estilo desconhecido")
    construtor = StateGraph(Atendimento, context_schema=Politica)
    no_decisao = decidir if estilo == "condicional" else decidir_com_command
    construtor.add_node("decidir", no_decisao)
    for nome, no in (("diagnosticar", diagnosticar), ("orientar", orientar),
                     ("propor", propor), ("recusar", recusar), ("finalizar", finalizar)):
        construtor.add_node(nome, no)
    construtor.add_edge(START, "decidir")
    if estilo == "condicional":
        construtor.add_conditional_edges("decidir", lambda e: e["rota"], {
            "diagnosticar": "diagnosticar", "orientar": "orientar",
            "propor": "propor", "recusar": "recusar",
        })
    construtor.add_edge("diagnosticar", "finalizar")
    construtor.add_edge("orientar", "finalizar")
    for nome in ("finalizar", "propor", "recusar"):
        construtor.add_edge(nome, END)
    return construtor
# fim:topologia


# trecho:contrato_final
def validar_fim(estado: dict, entrada: Entrada, politica: Politica) -> dict:
    rota = escolher(entrada, politica)
    if estado.get("id") != entrada["id"] or estado.get("rota") != rota:
        raise ErroContrato("vinculo", "final")
    situacao = estado.get("situacao")
    conteudos = {k for k in ("resposta", "proposta", "motivo") if k in estado}
    if rota in {"diagnosticar", "orientar"}:
        if (situacao != "concluido" or conteudos != {"resposta"}
                or type(estado["resposta"]) is not str or not estado["resposta"].strip()):
            raise ErroContrato("resposta", "final")
        detalhe = {"resposta": estado["resposta"]}
    elif rota == "propor":
        esperado = {"chamado_id": entrada["id"], "acao": "agendar_analise"}
        if situacao != "proposto" or conteudos != {"proposta"} or estado["proposta"] != esperado:
            raise ErroContrato("proposta", "final")
        detalhe = {"proposta": dict(estado["proposta"])}
    else:
        if (situacao != "recusado" or conteudos != {"motivo"}
                or type(estado["motivo"]) is not str or not estado["motivo"].strip()):
            raise ErroContrato("motivo", "final")
        detalhe = {"motivo": estado["motivo"]}
    return {"id": entrada["id"], "situacao": situacao, **detalhe}


def atender(valor: object, politica: Politica, grafo=None) -> dict:
    entrada = validar_entrada(valor)
    grafo = montar_grafo().compile() if grafo is None else grafo
    estado = grafo.invoke(entrada, context=politica)
    return validar_fim(estado, entrada, politica)
# fim:contrato_final


if __name__ == "__main__":
    chamado = {"id": "A-19", "tipo": "mudanca", "usuarios": 0,
               "descricao": "Solicitar nova janela de manutencao"}
    grafo = montar_grafo().compile()
    print(atender(chamado, Politica(False), grafo))
    print(atender(chamado, Politica(True), grafo))
