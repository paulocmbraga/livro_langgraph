"""Destino sintético: efeito e recibo na mesma transação SQLite."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3


def canonico(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def digest(valor):
    return hashlib.sha256(canonico(valor).encode("utf8")).hexdigest()


class RespostaPerdida(RuntimeError):
    pass


class Colisao(RuntimeError):
    pass


class RevisaoDivergente(RuntimeError):
    pass


class QuedaSimulada(RuntimeError):
    pass


class Destino:
    def __init__(self, pasta):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo = self.pasta/"destino.sqlite"
        with self.conexao() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chamados(
                    org TEXT, id TEXT, status TEXT, revisao INTEGER,
                    PRIMARY KEY(org,id));
                CREATE TABLE IF NOT EXISTS efeitos(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    operacao TEXT, digest TEXT, recibo TEXT);
                CREATE TABLE IF NOT EXISTS recibos(
                    operacao TEXT PRIMARY KEY, digest TEXT, recibo TEXT);
                CREATE TABLE IF NOT EXISTS eventos(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT);
                INSERT OR IGNORE INTO chamados VALUES
                    ('aurora','A-17','aberto',3);
            """)

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

    def evento(self, tipo):
        with self.conexao() as db:
            db.execute("INSERT INTO eventos(tipo) VALUES(?)", (tipo,))

    def ler(self):
        with self.conexao() as db:
            return dict(db.execute(
                "SELECT * FROM chamados WHERE org='aurora' AND id='A-17'"
            ).fetchone())

    # trecho:transacao
    def aplicar(self, proposta, *, deduplicar=True, falha=""):
        self.evento("despacho")
        chave, resumo = proposta["operacao"], digest(proposta)
        with self.conexao() as db:
            db.execute("BEGIN IMMEDIATE")
            anterior = db.execute(
                "SELECT * FROM recibos WHERE operacao=?", (chave,)
            ).fetchone()
            if anterior and deduplicar:
                if anterior["digest"] != resumo:
                    raise Colisao("chave_com_outro_conteudo")
                return json.loads(anterior["recibo"])
            atual = db.execute(
                "SELECT * FROM chamados WHERE org=? AND id=?",
                (proposta["organizacao"], proposta["chamado_id"]),
            ).fetchone()
            if atual is None:
                raise ValueError("recurso_indisponivel")
            esperada = proposta.get("expected_revision")
            if esperada is not None and atual["revisao"] != esperada:
                raise RevisaoDivergente("revisao_divergente")
            revisao = atual["revisao"] + 1
            db.execute(
                "UPDATE chamados SET status=?, revisao=? WHERE org=? AND id=?",
                (proposta["novo_status"], revisao,
                 proposta["organizacao"], proposta["chamado_id"]),
            )
            recibo = {"operacao": chave, "digest": resumo,
                      "revisao": revisao, "status": proposta["novo_status"]}
            dados = canonico(recibo)
            db.execute(
                "INSERT INTO efeitos(operacao,digest,recibo) VALUES(?,?,?)",
                (chave, resumo, dados))
            db.execute(
                "INSERT OR REPLACE INTO recibos VALUES(?,?,?)",
                (chave, resumo, dados))
            if falha == "antes_commit":
                raise RespostaPerdida("transacao_nao_confirmada")
        if falha == "depois_commit":
            raise RespostaPerdida("efeito_confirmado_resposta_perdida")
        return recibo
    # fim:transacao

    # trecho:consulta
    def consultar(self, operacao, resumo, *, disponivel=True):
        self.evento("consulta")
        if not disponivel:
            raise RespostaPerdida("consulta_indisponivel")
        with self.conexao() as db:
            row = db.execute("SELECT * FROM recibos WHERE operacao=?",
                             (operacao,)).fetchone()
        if row is None:
            return {"situacao": "ausente"}
        if row["digest"] != resumo:
            raise Colisao("recibo_de_outro_conteudo")
        return {"situacao": "confirmed", "recibo": json.loads(row["recibo"])}
    # fim:consulta

    def contadores(self):
        with self.conexao() as db:
            eventos = dict(db.execute(
                "SELECT tipo,COUNT(*) FROM eventos GROUP BY tipo").fetchall())
            efeitos = db.execute("SELECT COUNT(*) FROM efeitos").fetchone()[0]
        return {"revisoes": eventos.get("revisao", 0),
                "despachos": eventos.get("despacho", 0),
                "consultas": eventos.get("consulta", 0), "efeitos": efeitos}


class Diario:
    """Intenção durável separada do estado do grafo e do destino."""
    def __init__(self, pasta):
        self.arquivo = Path(pasta)/"intencoes.sqlite"
        with self.conexao() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS intencoes(
                operacao TEXT PRIMARY KEY, digest TEXT, proposta TEXT,
                situacao TEXT, recibo TEXT)""")

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

    # trecho:intencao
    def registrar(self, proposta):
        chave, resumo = proposta["operacao"], digest(proposta)
        with self.conexao() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO intencoes VALUES(?,?,?,'prepared',NULL)",
                       (chave, resumo, canonico(proposta)))
            row = db.execute("SELECT * FROM intencoes WHERE operacao=?",
                             (chave,)).fetchone()
            if row["digest"] != resumo:
                raise Colisao("intencao_com_outro_conteudo")
            return dict(row)

    def marcar(self, chave, situacao, recibo=None):
        if situacao not in {"sent", "unknown", "confirmed"}:
            raise ValueError("situacao_invalida")
        with self.conexao() as db:
            mudou = db.execute(
                "UPDATE intencoes SET situacao=?, recibo=? WHERE operacao=?",
                (situacao, canonico(recibo) if recibo else None, chave))
            if mudou.rowcount != 1:
                raise ValueError("intencao_ausente")
    # fim:intencao

    def ler(self, chave):
        with self.conexao() as db:
            row = db.execute("SELECT * FROM intencoes WHERE operacao=?",
                             (chave,)).fetchone()
            return dict(row) if row else None
