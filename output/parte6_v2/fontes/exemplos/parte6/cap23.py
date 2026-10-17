"""Assistente integrado: corpus versionado, contexto limitado e fontes."""
import json
from pathlib import Path
import re
import time
import unicodedata
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from .base import Problema, conexao, digest, json_texto


def normalizar(texto):
    sem_acentos = "".join(c for c in unicodedata.normalize("NFD", texto)
                         if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", sem_acentos.casefold()))


class Preferencia(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    formato: Literal["curto", "detalhado"]
    ttl: int = Field(ge=1, le=86400)


class Conhecimento:
    def __init__(self, pasta, limite=600, relogio=time.time):
        self.arquivo = Path(pasta)/"conhecimento.sqlite"
        self.limite, self.relogio = limite, relogio
        with conexao(self.arquivo) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS corpus(
                    versao TEXT PRIMARY KEY, digest TEXT, documentos TEXT);
                CREATE TABLE IF NOT EXISTS atual(
                    id INTEGER PRIMARY KEY CHECK(id=1), versao TEXT);
                CREATE TABLE IF NOT EXISTS preferencias(
                    org TEXT, sujeito TEXT, formato TEXT, vence REAL,
                    PRIMARY KEY(org,sujeito));
                CREATE TABLE IF NOT EXISTS cache(
                    chave TEXT PRIMARY KEY, resposta TEXT);
            """)
        self.publicar("corpus-1", somente_inicial=True)

    # trecho:corpus
    def publicar(self, versao, somente_inicial=False):
        fixture = json.loads((Path(__file__).parent/"fixtures/corpus.json")
                             .read_text(encoding="utf8"))
        lote = next((v for v in fixture["versoes"] if v["id"] == versao), None)
        if lote is None:
            raise ValueError("corpus_ausente")
        docs = lote["documentos"]
        if len({(d["org"], d["id"]) for d in docs}) != len(docs):
            raise ValueError("documento_duplicado")
        with conexao(self.arquivo, True) as db:
            if somente_inicial and db.execute("SELECT 1 FROM atual").fetchone():
                return
            anterior = db.execute("SELECT digest FROM corpus WHERE versao=?",
                                  (versao,)).fetchone()
            if anterior and anterior["digest"] != digest(docs):
                raise ValueError("versao_imutavel")
            db.execute("INSERT OR IGNORE INTO corpus VALUES(?,?,?)",
                       (versao, digest(docs), json_texto(docs)))
            db.execute("INSERT INTO atual VALUES(1,?) ON CONFLICT(id) "
                       "DO UPDATE SET versao=excluded.versao", (versao,))
    # fim:corpus

    def preferir(self, pessoa, dado):
        p = Preferencia.model_validate(dado)
        with conexao(self.arquivo, True) as db:
            db.execute("INSERT INTO preferencias VALUES(?,?,?,?) "
                "ON CONFLICT(org,sujeito) DO UPDATE SET "
                "formato=excluded.formato,vence=excluded.vence",
                (pessoa.org, pessoa.sujeito, p.formato, self.relogio()+p.ttl))
        return {"formato": p.formato}

    def formato(self, pessoa):
        with conexao(self.arquivo) as db:
            r = db.execute("SELECT * FROM preferencias WHERE org=? AND sujeito=?",
                           (pessoa.org, pessoa.sujeito)).fetchone()
            return r["formato"] if r and self.relogio() < r["vence"] else "curto"

    # trecho:recuperacao
    def recuperar(self, pessoa, pergunta):
        termos = normalizar(pergunta).split()
        with conexao(self.arquivo) as db:
            r = db.execute("SELECT c.* FROM corpus c JOIN atual a "
                           "ON c.versao=a.versao WHERE a.id=1").fetchone()
            docs = json.loads(r["documentos"])
        permitidos = [d for d in docs if d["org"] == pessoa.org]
        candidatos = [d for d in permitidos if d["assunto"] in termos]
        if "nao" in termos or len(candidatos) != 1:
            candidatos = []
        escolhidos, usado = [], 0
        for d in candidatos:
            tamanho = len(d["texto"])
            if usado+tamanho <= self.limite:
                escolhidos.append(d); usado += tamanho
        return r["versao"], escolhidos
    # fim:recuperacao

    # trecho:resposta
    def responder(self, pessoa, pergunta, versao, docs, formato):
        chave = digest({"org": pessoa.org, "sujeito": pessoa.sujeito,
            "permissao": pessoa.revisao, "corpus": versao,
            "pergunta": normalizar(pergunta), "formato": formato,
            "contexto": digest(docs), "politica": "extrativa-v1"})
        with conexao(self.arquivo, True) as db:
            r = db.execute("SELECT resposta FROM cache WHERE chave=?",
                           (chave,)).fetchone()
            if r:
                return {**json.loads(r["resposta"]), "cache": True}
            fontes = [{"id": d["id"], "revisao": d["revisao"],
                       "trecho": d["texto"]} for d in docs]
            texto = " ".join(d["texto"] for d in docs)
            if not docs:
                texto = "Não há evidência suficiente para esta pergunta."
            elif formato == "detalhado":
                texto = "Segundo o corpus "+versao+": "+texto
            resposta = {"situacao": "concluida", "resposta": texto,
                        "fontes": fontes, "absteve": not bool(docs),
                        "corpus": versao, "formato": formato}
            db.execute("INSERT INTO cache VALUES(?,?)",
                       (chave, json_texto(resposta)))
            return {**resposta, "cache": False}
    # fim:resposta


# trecho:identidade
def pessoa_atual(ctx):
    with conexao(ctx.app.dominio.arquivo) as db:
        p = ctx.app.dominio.conta(db, ctx.trabalho["dono"])
        ctx.app.dominio.autorizar(p, "ler", ctx.trabalho["org"])
        return p
# fim:identidade


def buscar(s, runtime: Runtime):
    ctx = runtime.context
    p = pessoa_atual(ctx)
    base = ctx.app.conhecimento
    versao, docs = base.recuperar(p, s["pedido"]["texto"])
    return {"corpus": versao, "documentos": docs, "formato": base.formato(p)}


def responder(s, runtime: Runtime):
    ctx = runtime.context
    p = pessoa_atual(ctx)
    return {"resultado": ctx.app.conhecimento.responder(p,
        s["pedido"]["texto"], s["corpus"], s["documentos"], s["formato"])}


def criar_grafo(saver, tipo="conhecimento"):
    from .cap21 import Estado, Contexto
    g = StateGraph(Estado, context_schema=Contexto)
    g.add_node("buscar", buscar); g.add_node("responder", responder)
    g.add_edge(START, "buscar"); g.add_edge("buscar", "responder")
    g.add_edge("responder", END)
    return g.compile(checkpointer=saver)


def julgar(saida, caso):
    fontes = saida.get("fontes", [])
    return (saida.get("situacao") == "concluida"
            and saida.get("corpus") == "corpus-1"
            and [f["id"] for f in fontes] == caso["fontes"]
            and [f["revisao"] for f in fontes] == caso["revisoes"]
            and saida.get("absteve") == caso["absteve"]
            and saida.get("resposta") == caso["resposta"]
            and (not fontes or " ".join(f["trecho"] for f in fontes)
                 == caso["resposta"]))


# trecho:aceitacao
def avaliar(url, tokens):
    from .cap21 import chamar, aguardar
    dados = json.loads((Path(__file__).parent/"fixtures/aceitacao.json")
                       .read_text(encoding="utf8"))
    dev, teste = dados["desenvolvimento"], dados["aceitacao"]
    if {c["grupo"] for c in dev} & {c["grupo"] for c in teste}:
        raise ValueError("grupos_sobrepostos")
    resultados = []
    for caso in teste:
        token = tokens[caso["conta"]]
        status, r = chamar(url, token, "POST", "/execucoes",
            {"tipo": "conhecimento", "texto": caso["texto"]}, "aceite-"+caso["id"])
        if status not in (200, 202):
            raise RuntimeError("admissao_falhou")
        fim = aguardar(url, token, r["id"], {"concluida", "falhou"})
        saida = fim["resultado"]
        correta = fim["status"] == "concluida" and julgar(saida, caso)
        resultados.append({"caso": caso["id"], "correta": correta,
                           "saida": saida})
    return {"versao": dados["versao"], "casos": resultados,
            "corretos": sum(c["correta"] for c in resultados),
            "inferencia_real": False}
# fim:aceitacao


def executar():
    from tempfile import TemporaryDirectory
    from .cap21 import Aplicacao, servir
    with TemporaryDirectory() as pasta:
        app = Aplicacao(pasta); tokens = app.dominio.preparar()
        with servir(app) as url:
            return avaliar(url, tokens)


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
