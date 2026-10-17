"""Dossiê, proveniência, gerações e revisão de conflitos; armazenamento local."""
from dataclasses import dataclass, field
import hashlib
import json
import operator
from typing import Annotated, Literal, TypedDict
from pydantic import BaseModel, ConfigDict, Field
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Send


def digest(objeto):
    return hashlib.sha256(json.dumps(objeto, sort_keys=True,
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


# trecho:envelope
class Entrega(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    run: str
    tarefa: str
    mensagem: str
    tentativa: int = Field(ge=1)
    snapshot: int = Field(ge=1)
    fonte: str
    revisao: int = Field(ge=1)
    prioridade: Literal["alta", "normal"]


@dataclass
class Coordenador:
    run: str = "R1"
    snapshot: int = 1
    tentativas: dict = field(default_factory=lambda: {"impacto": 1, "operacao": 1})
    catalogo: dict = field(default_factory=lambda: {"D1": (1, "origem-1"), "D2": (1, "origem-2")})
    aceitas: dict = field(default_factory=dict)
    mensagens: dict = field(default_factory=dict)
    fechado: bool = False
    integridade: bool = True

    def receber(self, objeto):
        e = Entrega.model_validate(objeto)
        if self.fechado:
            return "encerrado"
        if (e.run != self.run or e.snapshot != self.snapshot or
                self.tentativas.get(e.tarefa) != e.tentativa):
            return "obsoleta_ou_alheia"
        if self.catalogo.get(e.fonte, (None,))[0] != e.revisao:
            return "fonte_invalida"
        h = digest(e.model_dump())
        if e.mensagem in self.mensagens:
            if self.mensagens[e.mensagem] == h:
                return "duplicada"
            self.integridade = False
            return "conflito_integridade"
        if e.tarefa in self.aceitas:
            self.integridade = False
            return "conflito_integridade"
        self.mensagens[e.mensagem] = h
        self.aceitas[e.tarefa] = e.model_dump()
        return "aceita"

    def reatribuir(self, tarefa):
        if self.fechado or tarefa not in self.tentativas:
            raise ValueError("reatribuicao_invalida")
        self.tentativas[tarefa] += 1
        self.aceitas.pop(tarefa, None)

    def concluir(self):
        if self.fechado:
            raise ValueError("dossie_encerrado")
        completo = set(self.aceitas) == set(self.tentativas)
        raizes = {self.catalogo[e["fonte"]][1] for e in self.aceitas.values()}
        valores = {e["prioridade"] for e in self.aceitas.values()}
        if not self.integridade:
            status = "conflito_integridade"
        elif not completo:
            status = "incompleto"
        elif len(raizes) < 2:
            status = "evidencia_dependente"
        else:
            status = "divergencia" if len(valores) > 1 else "proposta"
        self.fechado = True
        dossie = {"run": self.run, "snapshot": self.snapshot,
                  "tentativas": self.tentativas.copy(), "entregas": self.aceitas.copy(),
                  "status": status}
        return {**dossie, "digest": digest(dossie)}
# fim:envelope


def entrega(tarefa="impacto", prioridade="alta", **alteracoes):
    d = {"run": "R1", "tarefa": tarefa, "mensagem": "M-"+tarefa,
         "tentativa": 1, "snapshot": 1, "fonte": "D1" if tarefa == "impacto" else "D2",
         "revisao": 1, "prioridade": prioridade}
    return {**d, **alteracoes}


class EstadoEquipe(TypedDict, total=False):
    tarefas: list[dict]
    entregas: Annotated[list[dict], operator.add]
    dossie: dict
    resultado: str


# trecho:equipe
def criar_equipe():
    def distribuir(s):
        return [Send("especialista", {"entrega": e}) for e in s["tarefas"]]

    def especialista(s):
        e = Entrega.model_validate(s["entrega"])
        return {"entregas": [e.model_dump()]}

    def integrar(s):
        c = Coordenador()
        for e in s["entregas"]:
            c.receber(e)
        return {"dossie": c.concluir()}

    def revisar(s):
        d = s["dossie"]
        if d["status"] != "divergencia":
            return {"resultado": d["status"]}
        resposta = interrupt({"digest": d["digest"], "entregas": d["entregas"]})
        valores = {e["prioridade"] for e in d["entregas"].values()}
        if (type(resposta) is not dict or resposta.get("digest") != d["digest"]
                or resposta.get("prioridade") not in valores):
            raise ValueError("revisao_nao_vinculada")
        return {"resultado": "proposta_revisada_"+resposta["prioridade"]}

    g = StateGraph(EstadoEquipe)
    g.add_node("especialista", especialista)
    g.add_node("integrar", integrar)
    g.add_node("revisar", revisar)
    g.add_conditional_edges(START, distribuir)
    g.add_edge("especialista", "integrar")
    g.add_edge("integrar", "revisar")
    g.add_edge("revisar", END)
    return g.compile(checkpointer=InMemorySaver())
# fim:equipe


def demonstrar():
    from langgraph.types import Command
    g = criar_equipe()
    config = {"configurable": {"thread_id": "equipe-1"}}
    r = g.invoke({"tarefas": [entrega(), entrega("operacao", "normal")],
                  "entregas": []}, config)
    retomada = g.invoke(Command(resume={"digest": r["dossie"]["digest"],
                                       "prioridade": "alta"}), config)
    c = Coordenador()
    c.reatribuir("impacto")
    antiga = c.receber(entrega())
    c.receber(entrega(tentativa=2, mensagem="M2"))
    c.receber(entrega("operacao"))
    return {"pausou": bool(r.get("__interrupt__")), "resultado": retomada["resultado"],
            "atrasada": antiga, "dossie_atual": c.concluir(),
            "autenticacao_revisor": "responsabilidade_do_servico_cap24"}
