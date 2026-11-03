"""Serviço HTTP descartável de créditos de suporte. Livro e recibo na mesma linha."""
from contextlib import closing
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def digest(pedido):
    wire = json.dumps(pedido, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)
    return sha256(wire.encode("utf-8")).hexdigest()


def requisicao(url, caminho, dados=None, timeout=6):
    body = None if dados is None else json.dumps(dados).encode()
    req = Request(url + caminho, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as res:
            return res.status, json.load(res)
    except HTTPError as exc:
        with exc:
            return exc.code, json.load(exc)


def aplicar(db, chave, pedido):
    assinatura = digest(pedido)
    with closing(sqlite3.connect(db)) as con, con:
        con.execute("BEGIN IMMEDIATE")
        existente = con.execute("SELECT digest, recibo FROM creditos WHERE chave=?",
                                (chave,)).fetchone()
        if existente:
            if existente[0] != assinatura:
                return 409, {"erro": "chave reutilizada com outro conteúdo"}
            return 200, {"chave": chave, "digest": assinatura, "recibo": existente[1]}
        recibo = "rc-" + sha256(chave.encode()).hexdigest()[:24]
        con.execute("INSERT INTO creditos VALUES (?, ?, ?, ?, ?)",
                    (chave, pedido["intencao"], assinatura, pedido["minutos"], recibo))
        return 201, {"chave": chave, "digest": assinatura, "recibo": recibo}


def servir(db, porta, commit_sem_resposta, liberar_resposta, ocultar_consulta):
    with closing(sqlite3.connect(db)) as con:
        con.execute("""CREATE TABLE creditos (
            chave TEXT PRIMARY KEY, intencao TEXT NOT NULL, digest TEXT NOT NULL,
            minutos INTEGER NOT NULL, recibo TEXT UNIQUE NOT NULL)""")

    class API(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def responder(self, status, doc):
            body = json.dumps(doc).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionError, OSError):
                pass  # Cliente morto ou timeout depois do commit.

        def do_GET(self):
            rota, _, ident = urlsplit(self.path).path.lstrip("/").partition("/")
            with closing(sqlite3.connect(db)) as con:
                con.row_factory = sqlite3.Row
                if rota == "auditoria":
                    rows = con.execute("SELECT * FROM creditos WHERE intencao=? ORDER BY chave",
                                       (ident,)).fetchall()
                    self.responder(200, [dict(r) for r in rows])
                elif rota == "recibo" and ocultar_consulta.is_set():
                    self.responder(503, {"erro": "consulta indisponível"})
                elif rota == "recibo":
                    r = con.execute("SELECT * FROM creditos WHERE chave=?", (ident,)).fetchone()
                    self.responder(200 if r else 404, dict(r) if r else {})
                else:
                    self.responder(404, {})

        def do_POST(self):
            if self.path != "/creditos":
                return self.responder(404, {})
            doc = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            status, res = aplicar(db, doc["chave"], doc["pedido"])
            if doc.get("reter_resposta") and status == 201:
                # aplicar() já fechou o contexto que efetua o commit.
                commit_sem_resposta.set()
                if not liberar_resposta.wait(60):
                    return
            self.responder(status, res)

    with ThreadingHTTPServer(("127.0.0.1", 0), API) as http:
        porta.send(http.server_port)
        porta.close()
        http.serve_forever()
