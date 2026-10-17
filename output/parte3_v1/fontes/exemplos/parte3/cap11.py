"""Repetição seletiva, pending writes e posse de trabalho."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, TypedDict
import json
import operator
import sqlite3
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from .cap09 import configuracao
from .cap10 import proposta_padrao
from .destino import Destino


class Transitoria(RuntimeError):
    pass


class Definitiva(RuntimeError):
    pass


# trecho:retry
def criar_retry(contadores, falhas=2, definitiva=False):
    class Estado(TypedDict):
        valor: int

    def consultar(estado):
        contadores["tentativas"] += 1
        if definitiva:
            raise Definitiva("argumento_inaceitavel")
        if contadores["tentativas"] <= falhas:
            raise Transitoria("indisponibilidade_preparada")
        return {"valor": 17}

    grafo = StateGraph(Estado)
    grafo.add_node("consultar", consultar, retry_policy=RetryPolicy(
        max_attempts=3, initial_interval=0.001,
        backoff_factor=2, max_interval=0.01, jitter=False,
        retry_on=Transitoria))
    grafo.add_edge(START, "consultar")
    grafo.add_edge("consultar", END)
    return grafo.compile()
# fim:retry


# trecho:pendencias
def criar_paralelo(checkpointer, contadores, falhar):
    class Estado(TypedDict):
        evidencias: Annotated[list[str], operator.add]

    def a(estado):
        contadores["a"] += 1
        return {"evidencias": ["A"]}

    def b(estado):
        contadores["b"] += 1
        if falhar:
            raise Transitoria("B_interrompido")
        return {"evidencias": ["B"]}

    grafo = StateGraph(Estado)
    grafo.add_node("a", a)
    grafo.add_node("b", b)
    grafo.add_edge(START, "a")
    grafo.add_edge(START, "b")
    grafo.add_edge("a", END)
    grafo.add_edge("b", END)
    return grafo.compile(checkpointer=checkpointer)
# fim:pendencias


class Fila:
    def __init__(self, arquivo):
        self.arquivo = Path(arquivo)
        with self.conexao() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS trabalhos(
                operacao TEXT PRIMARY KEY, dono TEXT, geracao INTEGER,
                ate REAL, situacao TEXT)""")

    @contextmanager
    def conexao(self):
        db = sqlite3.connect(self.arquivo, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    # trecho:posse
    def adquirir(self, operacao, dono, agora, ttl=10):
        if not dono or ttl <= 0:
            raise ValueError("posse_invalida")
        with self.conexao() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO trabalhos VALUES(?,NULL,0,0,'pendente')",
                       (operacao,))
            row = db.execute("SELECT * FROM trabalhos WHERE operacao=?",
                             (operacao,)).fetchone()
            if row["situacao"] == "concluido" or row["ate"] > agora:
                return None
            geracao = row["geracao"] + 1
            db.execute(
                "UPDATE trabalhos SET dono=?,geracao=?,ate=? WHERE operacao=?",
                (dono, geracao, agora+ttl, operacao))
            return geracao

    def concluir(self, operacao, dono, geracao, agora):
        with self.conexao() as db:
            alterou = db.execute("""
                UPDATE trabalhos SET situacao='concluido'
                WHERE operacao=? AND dono=? AND geracao=? AND ate>?
                  AND situacao='pendente'
            """, (operacao, dono, geracao, agora))
            return alterou.rowcount == 1
    # fim:posse


# trecho:compensacao
def compensar(destino, proposta, recibo):
    if recibo["operacao"] != proposta["operacao"]:
        raise ValueError("recibo_incompativel")
    from .destino import digest
    if recibo["digest"] != digest(proposta):
        raise ValueError("conteudo_incompativel")
    inversa = {
        "operacao": proposta["operacao"] + ":compensar",
        "organizacao": proposta["organizacao"],
        "chamado_id": proposta["chamado_id"],
        "novo_status": "aberto",
        "expected_revision": recibo["revisao"],
    }
    return destino.aplicar(inversa)
# fim:compensacao


def executar():
    with TemporaryDirectory() as pasta:
        destino = Destino(pasta)
        fila = Fila(Path(pasta)/"fila.sqlite")
        proposta = proposta_padrao()
        a = fila.adquirir("op-001", "worker-a", 0)
        b = fila.adquirir("op-001", "worker-b", 11)
        destino.aplicar(proposta)
        destino.aplicar(proposta)
        antigo = fila.concluir("op-001", "worker-a", a, 12)
        atual = fila.concluir("op-001", "worker-b", b, 12)
        return {"geracoes": [a, b], "concluiu_a": antigo,
                "concluiu_b": atual, **destino.contadores()}


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
