"""Checkpoints, histórico e ramificação, com destino separado."""
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict
import json
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from .destino import Destino


# trecho:grafo
class Estado(TypedDict, total=False):
    chamado_id: str
    observacao: dict
    resumo: str


@dataclass
class Contexto:
    destino: Destino


def consultar(estado: Estado, runtime: Runtime[Contexto]):
    if estado["chamado_id"] != "A-17":
        raise ValueError("chamado_fora_da_bancada")
    runtime.context.destino.evento("consulta")
    return {"observacao": runtime.context.destino.ler()}


def resumir(estado: Estado):
    dado = estado["observacao"]
    return {"resumo": f'{dado["id"]}: {dado["status"]}, revisão {dado["revisao"]}'}


def criar_grafo(checkpointer, pausar=False):
    grafo = StateGraph(Estado, context_schema=Contexto)
    grafo.add_node("consultar", consultar)
    grafo.add_node("resumir", resumir)
    grafo.add_edge(START, "consultar")
    grafo.add_edge("consultar", "resumir")
    grafo.add_edge("resumir", END)
    return grafo.compile(
        checkpointer=checkpointer,
        interrupt_after=["consultar"] if pausar else None)
# fim:grafo


# trecho:inspecao
def configuracao(thread_id):
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("thread_id_obrigatorio")
    return {"configurable": {"thread_id": thread_id}}


def inspecionar(grafo, config):
    estado = grafo.get_state(config)
    return {
        "existe": bool(estado.values),
        "valores": estado.values,
        "proximos": list(estado.next),
        "checkpoint_id": estado.config["configurable"].get("checkpoint_id"),
        "origem": estado.metadata.get("source") if estado.metadata else None,
    }
# fim:inspecao


# trecho:ramificacao
def ramificar(grafo, checkpoint, novo_status):
    copia = dict(checkpoint.values["observacao"])
    copia["status"] = novo_status
    ramo = grafo.update_state(
        checkpoint.config, {"observacao": copia}, as_node="consultar")
    resultado = grafo.invoke(None, ramo, durability="sync")
    return ramo, resultado
# fim:ramificacao


def executar():
    with TemporaryDirectory() as pasta:
        destino = Destino(pasta)
        with SqliteSaver.from_conn_string(str(Path(pasta)/"grafo.sqlite")) as saver:
            grafo = criar_grafo(saver, pausar=True)
            config = configuracao("aurora:leitura:01")
            grafo.invoke({"chamado_id": "A-17"}, config,
                         context=Contexto(destino), durability="sync")
            pausa = grafo.get_state(config)
            grafo.invoke(None, config, context=Contexto(destino), durability="sync")
            _, ramo = ramificar(grafo, pausa, "simulado")
            return {"original": pausa.values["observacao"]["status"],
                    "ramo": ramo["resumo"], "destino": destino.ler()["status"],
                    "consultas": destino.contadores()["consultas"]}


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
