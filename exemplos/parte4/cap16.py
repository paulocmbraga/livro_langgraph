"""Comparação controlada de fluxo único e delegação, sem inferência real."""
from dataclasses import dataclass, field
import json
from typing import Annotated, Literal, TypedDict
import operator
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import START, END, StateGraph
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict
from exemplos.parte4.cap13 import estimar

CASOS = (
    {"id": "vpn", "pedido": "Como configurar VPN?", "alvos": ["conhecimento"],
     "esperado": "Instale Aurora Connect."},
    {"id": "status", "pedido": "Consulte A-17.", "alvos": ["operacoes"],
     "esperado": "A-17 está aberto na revisão 3."},
    {"id": "mista", "pedido": "Explique VPN e consulte A-17.",
     "alvos": ["conhecimento", "operacoes"],
     "esperado": "Instale Aurora Connect. | A-17 está aberto na revisão 3."},
    {"id": "ambigua", "pedido": "Resolva isso.", "alvos": [],
     "esperado": "Esclareça o recurso e a intenção."},
    {"id": "ausente", "pedido": "Como configurar impressora?",
     "alvos": ["conhecimento"], "esperado": "Evidência insuficiente."},
    {"id": "negacao", "pedido": "Não altere A-17; apenas explique a VPN.",
     "alvos": ["conhecimento"], "esperado": "Instale Aurora Connect."},
)


class SemOrcamento(RuntimeError):
    pass


# trecho:orcamento
@dataclass
class Orcamento:
    max_chamadas: int = 4
    max_estimativa: int = 1400
    registros: list = field(default_factory=list)

    def __post_init__(self):
        if any(type(n) is not int or n < 0 for n in
               (self.max_chamadas, self.max_estimativa)):
            raise ValueError("orcamento_invalido")

    def chamada(self, papel, entrada, gerar):
        mensagens = [HumanMessage(content=json.dumps(
            entrada, ensure_ascii=False, sort_keys=True))]
        entrada_estimada = estimar(mensagens)
        reserva_saida = 120
        consumido = sum(r["total_estimado"] for r in self.registros)
        necessario = consumido + entrada_estimada + reserva_saida
        if (len(self.registros) >= self.max_chamadas
                or necessario > self.max_estimativa):
            raise SemOrcamento("limite_global")
        saida = gerar()
        saida_estimada = estimar([AIMessage(content=json.dumps(
            saida, ensure_ascii=False, sort_keys=True))])
        self.registros.append({
            "papel": papel, "entrada_estimada": entrada_estimada,
            "saida_estimada": saida_estimada,
            "total_estimado": entrada_estimada + saida_estimada,
            "uso_real": None})
        if saida_estimada > reserva_saida:
            raise ValueError("roteiro_excede_reserva")
        return saida
# fim:orcamento


# trecho:contratos
class Decisao(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    destino: Literal["conhecimento", "operacoes", "concluir"]


class Entrega(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    tarefa: str
    especialista: Literal["conhecimento", "operacoes"]
    texto: str
    fonte: str | None
    situacao: Literal["resposta", "insuficiente"]


class Estado(TypedDict, total=False):
    entregas: Annotated[list[dict], operator.add]
    resposta: str
    motivo: str
    proximo: str
# fim:contratos


def produzir(caso, papel):
    if papel == "conhecimento":
        texto = ("Instale Aurora Connect." if "vpn" in caso["pedido"].casefold()
                 else "Evidência insuficiente.")
        fonte = "VPN-r2" if texto.startswith("Instale") else None
    else:
        texto, fonte = "A-17 está aberto na revisão 3.", "A-17:r3"
    return Entrega(tarefa=caso["id"], especialista=papel, texto=texto,
                   fonte=fonte, situacao="resposta" if fonte else "insuficiente").model_dump()


def juntar(caso, entregas):
    if not entregas:
        return "Esclareça o recurso e a intenção."
    return " | ".join(e["texto"] for e in entregas)


# trecho:delegacao
def criar_delegado(caso, orcamento, plano=None):
    roteiro = list(caso["alvos"] if plano is None else plano)
    # trecho:supervisor
    def supervisor(s):
        entregas = s.get("entregas", [])
        destino = (roteiro[len(entregas)]
                   if len(entregas) < len(roteiro) else "concluir")
        try:
            bruto = orcamento.chamada(
                "supervisor", {"pedido": caso["pedido"], "entregas": entregas},
                lambda: {"destino": destino})
        except SemOrcamento:
            return Command(
                update={"motivo": "orcamento", "resposta": ""}, goto=END)
        decisao = Decisao.model_validate(bruto)
        if decisao.destino == "concluir":
            return Command(update={"resposta": juntar(caso, entregas),
                                   "motivo": "concluido"}, goto=END)
        if any(e["especialista"] == decisao.destino for e in entregas):
            return Command(
                update={"resposta": "", "motivo": "sem_progresso"}, goto=END)
        return Command(goto=decisao.destino)
    # fim:supervisor
    # trecho:especialista
    def especialista(papel):
        def executar(s):
            try:
                bruto = orcamento.chamada(papel, {"tarefa": caso["id"],
                    "pedido": caso["pedido"]}, lambda: produzir(caso, papel))
            except SemOrcamento:
                return Command(
                    update={"motivo": "orcamento", "resposta": ""}, goto=END)
            entrega = Entrega.model_validate(bruto)
            if entrega.tarefa != caso["id"] or entrega.especialista != papel:
                raise ValueError("entrega_sem_correlacao")
            return Command(update={"entregas": [entrega.model_dump()]},
                           goto="supervisor")
        return executar
    # fim:especialista
    # trecho:composicao
    g = StateGraph(Estado)
    g.add_node("supervisor", supervisor)
    for papel in ("conhecimento", "operacoes"):
        g.add_node(papel, especialista(papel))
    g.add_edge(START, "supervisor")
    return g.compile()
    # fim:composicao
# fim:delegacao


def executar_caso(caso, arquitetura, max_chamadas=4):
    orc = Orcamento(max_chamadas=max_chamadas)
    if arquitetura == "unico":
        g = StateGraph(Estado)
        def resolver(s):
            try:
                r = orc.chamada("unico", {"pedido": caso["pedido"]},
                    lambda: {"entregas": [produzir(caso, a) for a in caso["alvos"]]})
            except SemOrcamento:
                return {"resposta": "", "motivo": "orcamento"}
            return {"entregas": r["entregas"],
                    "resposta": juntar(caso, r["entregas"]), "motivo": "concluido"}
        g.add_node("resolver", resolver)
        g.add_edge(START, "resolver")
        g.add_edge("resolver", END)
        grafo = g.compile()
    elif arquitetura in ("delegado", "delegado_ruim"):
        plano = ["operacoes"] if arquitetura == "delegado_ruim" and caso["id"] == "negacao" else None
        grafo = criar_delegado(caso, orc, plano)
    else:
        raise ValueError("arquitetura_desconhecida")
    r = grafo.invoke({"entregas": []}, {"recursion_limit": 20})
    entregas = r.get("entregas", [])
    return {"caso": caso["id"], "arquitetura": arquitetura,
            "resposta": r["resposta"], "motivo": r["motivo"],
            "correta": r["resposta"] == caso["esperado"],
            "delegacoes": len(entregas) if arquitetura != "unico" else 0,
            "indevidas": sum(e["especialista"] not in caso["alvos"] for e in entregas),
            "chamadas": len(orc.registros),
            "estimativa": sum(r["total_estimado"] for r in orc.registros),
            "registros": orc.registros}


# trecho:transferencia
def criar_transferencia():
    class S(TypedDict, total=False):
        motivo: str
        destino: str
    def transferir(s) -> Command:
        return Command(graph=Command.PARENT, goto="revisao",
                       update={"motivo": "exige_supervisao"})
    filho = StateGraph(S)
    filho.add_node("transferir", transferir)
    filho.add_edge(START, "transferir")
    pai = StateGraph(S)
    pai.add_node("especialista", filho.compile())
    pai.add_node("revisao", lambda s: {"destino": "revisor"})
    pai.add_edge(START, "especialista")
    pai.add_edge("revisao", END)
    return pai.compile()
# fim:transferencia


def executar():
    resultados = [executar_caso(c, a) for a in ("unico", "delegado", "delegado_ruim")
                  for c in CASOS]
    return {"max_chamadas_por_tarefa": 4, "casos_por_arquitetura": len(CASOS),
            "inferencia_real": False, "resultados": resultados}


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
