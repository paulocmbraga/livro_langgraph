"""Versões explícitas e migração supervisionada de uma execução parada."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, TypedDict
import json
import sqlite3
from pydantic import ConfigDict, Field
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from .cap09 import configuracao
from .cap10 import Proposta, Decisao, proposta_padrao, aprovar
from .destino import Destino, digest, canonico


class Incompativel(RuntimeError):
    pass


# trecho:versoes
class PropostaV2(Proposta):
    model_config = ConfigDict(strict=True, extra="forbid")
    expected_revision: int = Field(ge=1)


class Estado(TypedDict, total=False):
    versao: int
    proposta: dict
    aprovacao: dict | None
    recibo: dict | None
    situacao: str
    migracao: dict | None


def validar_estado(estado, versao_runtime):
    if (type(estado.get("versao")) is not int
            or estado["versao"] != versao_runtime):
        raise Incompativel("versao_do_estado_incompativel")
    contrato = {1: Proposta, 2: PropostaV2}.get(versao_runtime)
    if contrato is None:
        raise Incompativel("versao_nao_suportada")
    return contrato.model_validate(estado["proposta"]).model_dump()
# fim:versoes


@dataclass
class Contexto:
    destino: Destino
    revisor: str = "ana"


# trecho:grafo
def criar_grafo(saver, versao_runtime):
    def revisar(estado, runtime: Runtime[Contexto]):
        proposta = validar_estado(estado, versao_runtime)
        resposta = interrupt({"versao": versao_runtime,
                              "proposta": proposta, "digest": digest(proposta)})
        decisao = Decisao.model_validate(resposta)
        aceita = (decisao.aceitar and decisao.digest == digest(proposta)
                  and decisao.operacao == proposta["operacao"])
        return {"aprovacao": (
            {"digest": decisao.digest, "revisor": runtime.context.revisor}
            if aceita else None), "situacao": "revisada"}

    def executar(estado, runtime: Runtime[Contexto]):
        proposta = validar_estado(estado, versao_runtime)
        if (estado.get("aprovacao") or {}).get("digest") != digest(proposta):
            return {"situacao": "sem_aprovacao", "recibo": None}
        return {"situacao": "confirmed",
                "recibo": runtime.context.destino.aplicar(proposta)}

    grafo = StateGraph(Estado, context_schema=Contexto)
    grafo.add_node("revisar", revisar)
    grafo.add_node("executar", executar)
    grafo.add_edge(START, "revisar")
    grafo.add_edge("revisar", "executar")
    grafo.add_edge("executar", END)
    return grafo.compile(checkpointer=saver, interrupt_after=["revisar"])
# fim:grafo


class Catalogo:
    """Gate local: todos os workers desta bancada devem passar por ele."""
    def __init__(self, arquivo):
        self.arquivo = Path(arquivo)
        with self.conexao() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS execucoes(
                thread TEXT PRIMARY KEY, versao INTEGER, situacao TEXT,
                origem TEXT, entrada TEXT)""")

    @contextmanager
    def conexao(self):
        db = sqlite3.connect(self.arquivo, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def cadastrar(self, thread, versao, origem=None):
        if versao not in (1, 2):
            raise Incompativel("versao_nao_suportada")
        with self.conexao() as db:
            db.execute("INSERT INTO execucoes VALUES(?,?,'ativa',?,NULL)",
                       (thread, versao, origem))

    def entrada_migrada(self, thread):
        with self.conexao() as db:
            row = db.execute("SELECT entrada FROM execucoes WHERE thread=?",
                             (thread,)).fetchone()
            if row is None or row["entrada"] is None:
                raise Incompativel("entrada_migrada_ausente")
            return json.loads(row["entrada"])

    # trecho:gate
    def invocar(self, grafos, entrada, config, contexto):
        thread = config["configurable"]["thread_id"]
        with self.conexao() as db:
            row = db.execute("SELECT * FROM execucoes WHERE thread=?",
                             (thread,)).fetchone()
            if row is None or row["situacao"] != "ativa":
                raise Incompativel("execucao_indisponivel")
            grafo = grafos[row["versao"]]
            return grafo.invoke(entrada, config, context=contexto,
                                durability="sync")
    # fim:gate

    # trecho:migracao
    def migrar(self, grafo_v1, config, destino, nova_thread, nova_operacao):
        origem = config["configurable"]["thread_id"]
        with self.conexao() as db:
            row = db.execute("SELECT * FROM execucoes WHERE thread=?",
                             (origem,)).fetchone()
            if row is None or row["situacao"] != "ativa" or row["versao"] != 1:
                raise Incompativel("origem_nao_migravel")
            snapshot = grafo_v1.get_state(config)
            antiga = validar_estado(snapshot.values, 1)
            if snapshot.next != ("executar",):
                raise Incompativel("origem_fora_da_fronteira")
            if nova_thread == origem or nova_operacao == antiga["operacao"]:
                raise Incompativel("identidade_nova_obrigatoria")
            resultado = destino.consultar(antiga["operacao"], digest(antiga))
            if resultado["situacao"] != "ausente":
                raise Incompativel("efeito_antigo_exige_conciliacao")
            revisao = destino.ler()["revisao"]
            nova = PropostaV2.model_validate({
                **antiga, "operacao": nova_operacao,
                "expected_revision": revisao}).model_dump()
            trilha = {
                "origem": origem,
                "checkpoint_id": snapshot.config["configurable"]["checkpoint_id"],
                "digest_anterior": digest(antiga), "digest_novo": digest(nova)}
            entrada = {"versao": 2, "proposta": nova, "aprovacao": None,
                       "recibo": None, "situacao": "aguardando_revisao",
                       "migracao": trilha}
            db.execute("UPDATE execucoes SET situacao='migrada' WHERE thread=?",
                       (origem,))
            db.execute("INSERT INTO execucoes VALUES(?,2,'ativa',?,?)",
                       (nova_thread, origem, canonico(entrada)))
            return entrada
    # fim:migracao


def fixture_v1():
    arquivo = Path(__file__).with_name("fixtures")/"estado_v1.json"
    return json.loads(arquivo.read_text(encoding="utf8"))


def executar():
    with TemporaryDirectory() as pasta:
        destino = Destino(pasta)
        catalogo = Catalogo(Path(pasta)/"catalogo.sqlite")
        contexto = Contexto(destino)
        catalogo.cadastrar("antiga", 1)
        with SqliteSaver.from_conn_string(str(Path(pasta)/"grafo.sqlite")) as saver:
            grafos = {v: criar_grafo(saver, v) for v in (1, 2)}
            entrada, config = fixture_v1(), configuracao("antiga")
            catalogo.invocar(grafos, entrada, config, contexto)
            catalogo.invocar(grafos, aprovar(entrada["proposta"]), config, contexto)
            nova = catalogo.migrar(grafos[1], config, destino, "nova", "op-nova")
            nova_config = configuracao("nova")
            catalogo.invocar(grafos, nova, nova_config, contexto)
            catalogo.invocar(grafos, aprovar(nova["proposta"]), nova_config, contexto)
            final = catalogo.invocar(grafos, None, nova_config, contexto)
            return {"situacao": final["situacao"],
                    "expected_revision": nova["proposta"]["expected_revision"],
                    "aprovacao_migrada": nova["aprovacao"],
                    **destino.contadores()}


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
