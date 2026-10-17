"""Fronteira persistente de identidade, revisão e destino da bancada."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field


def json_texto(dado):
    return json.dumps(dado, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(dado):
    return hashlib.sha256(json_texto(dado).encode("utf8")).hexdigest()


class Problema(Exception):
    def __init__(self, codigo, status=409):
        self.codigo, self.status = codigo, status
        super().__init__(codigo)


@contextmanager
def conexao(arquivo, escrita=False):
    db = sqlite3.connect(arquivo, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        if escrita:
            db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


# trecho:contratos
class Pedido(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    tipo: Literal["revisao", "eco", "conhecimento", "operacao"]
    texto: str = Field(min_length=1, max_length=1000)


class Decisao(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    aceitar: bool
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Acao(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    recurso: Literal["A-17", "B-29"]
    prioridade: Literal["alta", "baixa"]
    revisao: int = Field(ge=0)


@dataclass(frozen=True)
class Pessoa:
    sujeito: str
    org: str
    papeis: frozenset[str]
    revisao: int
# fim:contratos


class Dominio:
    def __init__(self, pasta, relogio=time.time):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo = self.pasta / "dominio.sqlite"
        self.relogio = relogio
        with conexao(self.arquivo) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pessoas(
                    id TEXT PRIMARY KEY, org TEXT, papeis TEXT,
                    revisao INTEGER, ativa INTEGER);
                CREATE TABLE IF NOT EXISTS sessoes(
                    hash TEXT PRIMARY KEY, sujeito TEXT,
                    revisao INTEGER, vence REAL);
                CREATE TABLE IF NOT EXISTS recursos(
                    id TEXT PRIMARY KEY, org TEXT,
                    prioridade TEXT, revisao INTEGER);
                CREATE TABLE IF NOT EXISTS revisoes(
                    id TEXT PRIMARY KEY, operacao TEXT, digest TEXT,
                    dono TEXT, org TEXT, revisor TEXT,
                    revisao_revisor INTEGER, vence REAL);
                CREATE TABLE IF NOT EXISTS recibos(
                    operacao TEXT PRIMARY KEY, digest TEXT,
                    dono TEXT, org TEXT, recibo TEXT);
                CREATE TABLE IF NOT EXISTS auditoria(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    operacao TEXT, tipo TEXT, instante REAL);
            """)

    def preparar(self):
        """Provisionamento confiável, somente em banco ainda sem contas."""
        contas = [("ana", "aurora", ["criar", "ler"]),
                  ("bia", "aurora", ["criar", "ler", "revisar"]),
                  ("bot", "aurora", ["executar"]),
                  ("caio", "boreal", ["criar", "ler", "revisar"])]
        with conexao(self.arquivo, True) as db:
            if db.execute("SELECT count(*) FROM pessoas").fetchone()[0]:
                raise Problema("bancada_ja_preparada")
            for nome, org, papeis in contas:
                db.execute("INSERT INTO pessoas VALUES(?,?,?,1,1)",
                           (nome, org, json_texto(papeis)))
            db.executemany("INSERT INTO recursos VALUES(?,?,?,?)", [
                ("A-17", "aurora", "baixa", 3),
                ("B-29", "boreal", "baixa", 2)])
        return {nome: self.emitir(nome) for nome, _, _ in contas}

    def conta(self, db, sujeito):
        r = db.execute("SELECT * FROM pessoas WHERE id=?",
                       (sujeito,)).fetchone()
        if r is None or not r["ativa"]:
            raise Problema("negado", 403)
        return Pessoa(r["id"], r["org"], frozenset(json.loads(r["papeis"])),
                      r["revisao"])

    def emitir(self, sujeito, ttl=86400):
        if type(ttl) is not int or ttl <= 0:
            raise ValueError("ttl_invalido")
        token = secrets.token_urlsafe(32)
        with conexao(self.arquivo, True) as db:
            p = self.conta(db, sujeito)
            db.execute("INSERT INTO sessoes VALUES(?,?,?,?)",
                       (digest(token), sujeito, p.revisao, self.relogio()+ttl))
        return token

    # trecho:identidade
    def autenticar_em(self, db, token):
        if not isinstance(token, str) or len(token) > 256:
            raise Problema("credencial_invalida", 401)
        r = db.execute("SELECT * FROM sessoes WHERE hash=?",
                       (digest(token),)).fetchone()
        if r is None or self.relogio() >= r["vence"]:
            raise Problema("credencial_invalida", 401)
        p = self.conta(db, r["sujeito"])
        if p.revisao != r["revisao"]:
            raise Problema("credencial_invalida", 401)
        return p

    def autenticar(self, token):
        with conexao(self.arquivo) as db:
            return self.autenticar_em(db, token)

    def autorizar(self, pessoa, papel, org):
        if papel not in pessoa.papeis or pessoa.org != org:
            raise Problema("negado", 403)
    # fim:identidade

    def revogar(self, sujeito):
        with conexao(self.arquivo, True) as db:
            db.execute("UPDATE pessoas SET ativa=0,revisao=revisao+1 WHERE id=?",
                       (sujeito,))

    def ler_recurso(self, sujeito, recurso):
        with conexao(self.arquivo) as db:
            p = self.conta(db, sujeito)
            r = db.execute("SELECT * FROM recursos WHERE id=?",
                           (recurso,)).fetchone()
            if r is None:
                raise Problema("negado", 403)
            self.autorizar(p, "criar", r["org"])
            return dict(r)

    # trecho:aprovar
    def aprovar(self, token, dono, proposta, ttl=300):
        if type(ttl) is not int or not 1 <= ttl <= 86400:
            raise Problema("prazo_invalido", 422)
        with conexao(self.arquivo, True) as db:
            revisor = self.autenticar_em(db, token)
            autor = self.conta(db, dono)
            self.autorizar(revisor, "revisar", autor.org)
            self.autorizar(autor, "criar", revisor.org)
            id_revisao = str(uuid4())
            db.execute("INSERT INTO revisoes VALUES(?,?,?,?,?,?,?,?)", (
                id_revisao, proposta["execucao"], digest(proposta), dono,
                autor.org, revisor.sujeito, revisor.revisao,
                self.relogio()+ttl))
            return id_revisao
    # fim:aprovar

    # trecho:destino
    def aplicar(self, token, dono, proposta, id_revisao):
        acao = Acao.model_validate(proposta["acao"])
        op, vinculo = proposta["execucao"], digest(proposta)
        with conexao(self.arquivo, True) as db:
            executor = self.autenticar_em(db, token)
            autor = self.conta(db, dono)
            self.autorizar(executor, "executar", autor.org)
            self.autorizar(autor, "criar", executor.org)
            r = db.execute("SELECT * FROM revisoes WHERE id=?",
                           (id_revisao,)).fetchone()
            if (r is None or r["operacao"] != op or r["dono"] != dono
                    or r["digest"] != vinculo or self.relogio() >= r["vence"]):
                raise Problema("revisao_invalida", 403)
            revisor = self.conta(db, r["revisor"])
            self.autorizar(revisor, "revisar", autor.org)
            if revisor.revisao != r["revisao_revisor"]:
                raise Problema("revisao_invalida", 403)
            anterior = db.execute("SELECT * FROM recibos WHERE operacao=?",
                                  (op,)).fetchone()
            if anterior:
                if anterior["digest"] != vinculo:
                    raise Problema("colisao_operacao")
                return json.loads(anterior["recibo"])
            recurso = db.execute("SELECT * FROM recursos WHERE id=?",
                                 (acao.recurso,)).fetchone()
            if recurso is None or recurso["org"] != autor.org:
                raise Problema("negado", 403)
            if recurso["revisao"] != acao.revisao:
                raise Problema("recurso_alterado")
            db.execute("UPDATE recursos SET prioridade=?,revisao=revisao+1 "
                       "WHERE id=?", (acao.prioridade, acao.recurso))
            recibo = {"operacao": op, "digest": vinculo,
                      "recurso": acao.recurso, "revisao": acao.revisao+1}
            db.execute("INSERT INTO recibos VALUES(?,?,?,?,?)",
                       (op, vinculo, dono, autor.org, json_texto(recibo)))
            db.execute("INSERT INTO auditoria(operacao,tipo,instante) "
                       "VALUES(?,?,?)", (op, "efeito", self.relogio()))
            return recibo
    # fim:destino

    def consultar_recibo(self, token, dono, proposta):
        with conexao(self.arquivo) as db:
            executor = self.autenticar_em(db, token)
            autor = self.conta(db, dono)
            self.autorizar(executor, "executar", autor.org)
            r = db.execute("SELECT * FROM recibos WHERE operacao=?",
                           (proposta["execucao"],)).fetchone()
            if not r:
                return None
            if r["digest"] != digest(proposta) or r["dono"] != dono:
                raise Problema("colisao_operacao")
            return json.loads(r["recibo"])

    def efeitos(self):
        with conexao(self.arquivo) as db:
            return db.execute("SELECT count(*) FROM recibos").fetchone()[0]
