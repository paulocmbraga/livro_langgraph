"""Admissão, diário público e exclusão de um worker por diretório."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4
from .base import Problema, conexao, digest, json_texto


VERSAO = "aurora-6-v1"
TERMINAIS = {"concluida", "rejeitada", "cancelada", "falhou", "desconhecida", "bloqueada"}


@contextmanager
def exclusividade(pasta):
    caminho = Path(pasta)/"servico.lock"
    with caminho.open("a+b") as f:
        try:
            # No Windows, ler o byte já bloqueado também é recusado.
            if os.fstat(f.fileno()).st_size == 0:
                f.write(b"0"); f.flush()
            f.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as erro:
            raise Problema("diretorio_em_uso", 503) from erro
        try:
            yield
        finally:
            f.seek(0)
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


class Fila:
    def __init__(self, pasta, limite=16):
        self.arquivo = Path(pasta)/"servico.sqlite"
        self.limite = limite
        with conexao(self.arquivo) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS execucoes(
                    id TEXT PRIMARY KEY, dono TEXT, org TEXT, chave TEXT,
                    digest TEXT, pedido TEXT, versao TEXT, status TEXT,
                    proposta TEXT, decisao TEXT, resultado TEXT, criado REAL,
                    iniciado REAL, terminado REAL,
                    UNIQUE(dono,org,chave));
                CREATE TABLE IF NOT EXISTS eventos(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    execucao TEXT, tipo TEXT, dados TEXT);
                CREATE TABLE IF NOT EXISTS envios(
                    execucao TEXT PRIMARY KEY, digest TEXT);
                CREATE TABLE IF NOT EXISTS configuracao(
                    chave TEXT PRIMARY KEY, valor TEXT);
                INSERT OR IGNORE INTO configuracao VALUES('isolado','false');
            """)

    def evento_em(self, db, id, tipo, dados=None):
        db.execute("INSERT INTO eventos(execucao,tipo,dados) VALUES(?,?,?)",
                   (id, tipo, json_texto(dados or {})))

    # trecho:admissao
    def admitir(self, pessoa, chave, pedido):
        if not isinstance(chave, str) or not re.fullmatch(r"[\w-]{1,80}", chave):
            raise Problema("chave_invalida", 422)
        vinculo = digest(pedido)
        with conexao(self.arquivo, True) as db:
            antigo = db.execute(
                "SELECT * FROM execucoes WHERE dono=? AND org=? AND chave=?",
                (pessoa.sujeito, pessoa.org, chave)).fetchone()
            if antigo:
                if antigo["digest"] != vinculo:
                    raise Problema("chave_com_outro_conteudo")
                return antigo["id"], False
            ativos = db.execute("SELECT count(*) FROM execucoes WHERE "
                "status IN ('fila','executando','revisao')").fetchone()[0]
            if ativos >= self.limite:
                raise Problema("capacidade_esgotada", 429)
            id = str(uuid4())
            db.execute("INSERT INTO execucoes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (id, pessoa.sujeito, pessoa.org, chave, vinculo,
                 json_texto(pedido), VERSAO, "fila", None, None, None,
                 time.time(), None, None))
            self.evento_em(db, id, "admitida")
            return id, True
    # fim:admissao

    def obter(self, id):
        with conexao(self.arquivo) as db:
            r = db.execute("SELECT * FROM execucoes WHERE id=?", (id,)).fetchone()
            if r is None:
                raise Problema("nao_encontrada", 404)
            return dict(r)

    # trecho:retomada
    def recuperar(self):
        # Chamado somente depois de adquirir o lock exclusivo do diretório.
        with conexao(self.arquivo, True) as db:
            rows = db.execute("SELECT id,versao FROM execucoes "
                              "WHERE status='executando'").fetchall()
            for r in rows:
                status = "fila" if r["versao"] == VERSAO else "bloqueada"
                db.execute("UPDATE execucoes SET status=? WHERE id=?",
                           (status, r["id"]))
                self.evento_em(db, r["id"], "recuperada", {"status": status})

    def reservar(self):
        with conexao(self.arquivo, True) as db:
            r = db.execute("SELECT * FROM execucoes WHERE status='fila' "
                           "ORDER BY criado,id LIMIT 1").fetchone()
            if not r:
                return None
            if r["versao"] != VERSAO:
                db.execute("UPDATE execucoes SET status='bloqueada' WHERE id=?",
                           (r["id"],))
                self.evento_em(db, r["id"], "versao_incompativel")
                return None
            db.execute("UPDATE execucoes SET status='executando',"
                       "iniciado=COALESCE(iniciado,?) WHERE id=?",
                       (time.time(), r["id"]))
            self.evento_em(db, r["id"], "iniciada")
            return dict(r)
    # fim:retomada

    def marcar(self, id, status, resultado=None, proposta=None):
        with conexao(self.arquivo, True) as db:
            db.execute("UPDATE execucoes SET status=?,resultado=?,"
                       "proposta=COALESCE(?,proposta),terminado=? WHERE id=?",
                (status, json_texto(resultado) if resultado is not None else None,
                 json_texto(proposta) if proposta is not None else None,
                 time.time() if status in TERMINAIS else None, id))
            self.evento_em(db, id, status)

    def decidir(self, id, decisao):
        with conexao(self.arquivo, True) as db:
            n = db.execute("UPDATE execucoes SET status='fila',decisao=? "
                           "WHERE id=? AND status='revisao'",
                           (json_texto(decisao), id)).rowcount
            if n != 1:
                raise Problema("revisao_nao_pendente")
            self.evento_em(db, id, "decisao_recebida")

    def cancelar(self, id):
        with conexao(self.arquivo, True) as db:
            n = db.execute("UPDATE execucoes SET status='cancelada',terminado=? "
                           "WHERE id=? AND status IN ('fila','revisao')",
                           (time.time(), id)).rowcount
            if n != 1:
                raise Problema("cancelamento_nao_admitido")
            self.evento_em(db, id, "cancelada")

    def eventos(self, id, apos=0):
        with conexao(self.arquivo) as db:
            return [{"id": r["seq"], "tipo": r["tipo"],
                     "dados": json.loads(r["dados"])} for r in db.execute(
                "SELECT * FROM eventos WHERE execucao=? AND seq>? "
                "ORDER BY seq LIMIT 100", (id, apos))]

    def enviado(self, id, proposta):
        with conexao(self.arquivo, True) as db:
            r = db.execute("SELECT digest FROM envios WHERE execucao=?",
                           (id,)).fetchone()
            if r:
                if r["digest"] != digest(proposta):
                    raise Problema("colisao_envio")
                return True
            db.execute("INSERT INTO envios VALUES(?,?)", (id, digest(proposta)))
            return False

    def isolado(self):
        with conexao(self.arquivo) as db:
            return db.execute("SELECT valor FROM configuracao WHERE chave='isolado'").fetchone()[0] == "true"

    def tem_envio(self, id):
        with conexao(self.arquivo) as db:
            return db.execute("SELECT 1 FROM envios WHERE execucao=?", (id,)).fetchone() is not None
