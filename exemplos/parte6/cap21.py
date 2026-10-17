"""API local, worker independente da conexão e revisão vinculada."""
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import TypedDict
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from pydantic import ValidationError
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from .base import (Decisao, Dominio, Pedido, Problema, conexao,
                   digest, json_texto)
from .fila import Fila, TERMINAIS, VERSAO, exclusividade


class Estado(TypedDict, total=False):
    pedido: dict
    proposta: dict
    decisao: dict
    resultado: dict
    corpus: str
    documentos: list[dict]
    formato: str
    chave_cache: str


@dataclass
class Contexto:
    app: object
    trabalho: dict


# trecho:grafo
def planejar(s: Estado, runtime: Runtime[Contexto]):
    ctx = runtime.context
    time.sleep(ctx.app.atraso)
    return {"proposta": {"execucao": ctx.trabalho["id"],
                         "versao": VERSAO,
                         "acao": {"mensagem": s["pedido"]["texto"]}}}


def revisar(s: Estado):
    resposta = interrupt({"digest": digest(s["proposta"])})
    return {"decisao": resposta}


def encerrar(s: Estado):
    aceita = s["decisao"]["aceitar"]
    return {"resultado": {"situacao": "concluida" if aceita else "rejeitada",
                          "resposta": "Revisão registrada."}}


def criar_grafo(saver, tipo):
    g = StateGraph(Estado, context_schema=Contexto)
    if tipo == "eco":
        g.add_node("eco", lambda s: {"resultado": {
            "situacao": "concluida", "resposta": s["pedido"]["texto"]}})
        g.add_edge(START, "eco"); g.add_edge("eco", END)
    else:
        g.add_node("planejar", planejar)
        g.add_node("revisar", revisar)
        g.add_node("encerrar", encerrar)
        g.add_edge(START, "planejar")
        g.add_edge("planejar", "revisar")
        g.add_edge("revisar", "encerrar"); g.add_edge("encerrar", END)
    return g.compile(checkpointer=saver)
# fim:grafo


class Aplicacao:
    def __init__(self, pasta, executor_token=None, limite=16, atraso=0,
                 falha_destino="", consulta_disponivel=True):
        self.pasta = Path(pasta)
        self.dominio = Dominio(pasta)
        self.fila = Fila(pasta, limite)
        self.executor_token, self.atraso = executor_token, atraso
        self.falha_destino = falha_destino
        self.consulta_disponivel = consulta_disponivel
        self.parar = threading.Event()
        self.worker_vivo = False
        from .cap23 import Conhecimento
        self.conhecimento = Conhecimento(pasta)

    def acesso(self, token, id):
        p = self.dominio.autenticar(token)
        r = self.fila.obter(id)
        if p.org != r["org"] or (p.sujeito != r["dono"]
                                      and "revisar" not in p.papeis):
            raise Problema("nao_encontrada", 404)
        self.dominio.autorizar(p, "ler", r["org"])
        return p, r

    def criar(self, token, chave, corpo):
        p = self.dominio.autenticar(token)
        self.dominio.autorizar(p, "criar", p.org)
        pedido = Pedido.model_validate(corpo).model_dump()
        id, nova = self.fila.admitir(p, chave, pedido)
        return {"id": id, "nova": nova}

    def consultar(self, token, id):
        _, r = self.acesso(token, id)
        publico = {"id": id, "status": r["status"], "versao": r["versao"],
                   "resultado": json.loads(r["resultado"]) if r["resultado"] else None}
        if r["status"] == "revisao":
            proposta = json.loads(r["proposta"])
            publico.update(proposta=proposta, digest=digest(proposta))
        return publico

    # trecho:decisao
    def decidir(self, token, id, corpo):
        p, r = self.acesso(token, id)
        self.dominio.autorizar(p, "revisar", r["org"])
        d = Decisao.model_validate(corpo)
        if r["status"] != "revisao":
            raise Problema("revisao_nao_pendente")
        proposta = json.loads(r["proposta"])
        if d.digest != digest(proposta):
            raise Problema("proposta_divergente")
        revisao = (self.dominio.aprovar(token, r["dono"], proposta)
                   if d.aceitar else None)
        self.fila.decidir(id, {"aceitar": d.aceitar,
                              "digest": d.digest, "revisao": revisao})
        return {"id": id, "status": "fila"}
    # fim:decisao

    def cancelar(self, token, id):
        self.acesso(token, id)
        self.fila.cancelar(id)
        return {"id": id, "status": "cancelada"}

    def pendencias(self, token):
        p = self.dominio.autenticar(token)
        self.dominio.autorizar(p, "revisar", p.org)
        with conexao(self.fila.arquivo) as db:
            return {"execucoes": [dict(r) for r in db.execute(
                "SELECT id,status FROM execucoes WHERE org=? AND "
                "status IN ('desconhecida','bloqueada','falhou') ORDER BY criado",
                (p.org,))]}

    def conciliar(self, token, id):
        p, r = self.acesso(token, id)
        self.dominio.autorizar(p, "revisar", r["org"])
        if r["status"] != "desconhecida":
            raise Problema("nao_pendente_de_conciliacao")
        from .cap24 import obter_recibo
        recibo = obter_recibo(self, r["dono"], json.loads(r["proposta"]))
        if recibo is not None:
            self.fila.marcar(id, "concluida", {
                "situacao": "concluida", "recibo": recibo})
        return self.consultar(token, id)

    # trecho:worker
    def processar_um(self):
        r = self.fila.reservar()
        if r is None:
            return False
        id = r["id"]
        pedido = json.loads(r["pedido"])
        config = {"configurable": {"thread_id": id}}
        try:
            with conexao(self.dominio.arquivo) as db:
                autor = self.dominio.conta(db, r["dono"])
                self.dominio.autorizar(autor, "criar", r["org"])
            if self.fila.isolado() and pedido["tipo"] == "operacao":
                raise Problema("restauracao_isolada")
            with SqliteSaver.from_conn_string(
                    str(self.pasta/"checkpoints.sqlite")) as saver:
                if pedido["tipo"] == "conhecimento":
                    from .cap23 import criar_grafo as fabrica
                elif pedido["tipo"] == "operacao":
                    from .cap24 import criar_grafo as fabrica
                else:
                    fabrica = criar_grafo
                grafo = fabrica(saver, pedido["tipo"])
                snapshot = grafo.get_state(config)
                if r["decisao"] and snapshot.next:
                    entrada = Command(resume=json.loads(r["decisao"]))
                elif snapshot.values:
                    entrada = None
                else:
                    entrada = {"pedido": pedido}
                for parte in grafo.stream(entrada, config,
                        context=Contexto(self, r), stream_mode="updates",
                        version="v2", durability="sync"):
                    for nome in parte["data"]:
                        if nome == "__interrupt__":
                            continue
                        with conexao(self.fila.arquivo, True) as db:
                            self.fila.evento_em(db, id, "etapa", {"nome": nome})
                final = grafo.get_state(config)
                if final.next:
                    self.fila.marcar(id, "revisao", proposta=final.values["proposta"])
                else:
                    resultado = final.values["resultado"]
                    self.fila.marcar(id, resultado["situacao"], resultado,
                                     final.values.get("proposta"))
        except Problema as e:
            self.registrar_falha(id, e.codigo)
        except Exception:
            self.registrar_falha(id, "falha_interna")
        return True
    # fim:worker

    def registrar_falha(self, id, codigo):
        # Depois do marco de envio, uma exceção não prova ausência de efeito.
        status = "desconhecida" if self.fila.tem_envio(id) else "falhou"
        self.fila.marcar(id, status, {"situacao": status, "codigo": codigo})

    def trabalhar(self):
        self.worker_vivo = True
        try:
            while not self.parar.is_set():
                if not self.processar_um():
                    self.parar.wait(.01)
        finally:
            self.worker_vivo = False


# trecho:eventos
def quadro_sse(evento):
    return (f'id: {evento["id"]}\n'
            f'event: {evento["tipo"]}\n'
            f'data: {json_texto(evento["dados"])}\n\n').encode("utf8")


def transmitir(handler, app, token, id, apos):
    app.acesso(token, id)
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    prazo = time.monotonic()+2
    try:
        while time.monotonic() < prazo:
            app.acesso(token, id)  # Reconfere credencial durante a janela.
            eventos = app.fila.eventos(id, apos)
            for evento in eventos:
                handler.wfile.write(quadro_sse(evento))
                handler.wfile.flush()
                apos = evento["id"]
            if (len(eventos) < 100 and
                    app.fila.obter(id)["status"] in TERMINAIS | {"revisao"}):
                break
            time.sleep(.02)
    except (BrokenPipeError, ConnectionResetError, OSError, Problema):
        pass  # Encerra só esta assinatura. O worker continua independente.
    handler.close_connection = True
# fim:eventos


def handler_para(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def resposta(self, status, dado):
            corpo = json_texto(dado).encode("utf8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(corpo)))
            if status == 429:
                self.send_header("Retry-After", "1")
            self.end_headers(); self.wfile.write(corpo)

        def tratar(self):
            url = urlparse(self.path)
            partes = url.path.strip("/").split("/")
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if self.command == "GET" and url.path == "/":
                corpo = (Path(__file__).parent/"interface.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers(); self.wfile.write(corpo)
                return
            if self.command == "GET" and url.path in ("/saude", "/pronto"):
                with conexao(app.fila.arquivo) as db:
                    db.execute("SELECT 1").fetchone()
                pronta = app.worker_vivo and not app.parar.is_set()
                self.resposta(200 if url.path == "/saude" or pronta else 503,
                              {"vivo": True, "pronto": pronta, "versao": VERSAO})
                return
            app.dominio.autenticar(token)
            corpo = {}
            if self.command in ("POST", "PUT"):
                tamanho = int(self.headers.get("Content-Length", "0"))
                if not 0 < tamanho <= 16384:
                    raise Problema("tamanho_invalido", 413)
                corpo = json.loads(self.rfile.read(tamanho))
            if self.command == "POST" and partes == ["execucoes"]:
                dado = app.criar(token, self.headers.get("Idempotency-Key"), corpo)
                self.resposta(202 if dado["nova"] else 200, dado)
            elif self.command == "GET" and partes == ["pendencias"]:
                self.resposta(200, app.pendencias(token))
            elif self.command == "PUT" and partes == ["preferencias"]:
                p = app.dominio.autenticar(token)
                self.resposta(200, app.conhecimento.preferir(p, corpo))
            elif len(partes) in (2, 3) and partes[0] == "execucoes":
                id = partes[1]
                app.acesso(token, id)
                if self.command == "GET" and len(partes) == 2:
                    self.resposta(200, app.consultar(token, id))
                elif self.command == "GET" and partes[2:] == ["eventos"]:
                    apos = int(parse_qs(url.query).get("apos", [
                        self.headers.get("Last-Event-ID", "0")])[0])
                    if apos < 0:
                        raise Problema("cursor_invalido", 422)
                    transmitir(self, app, token, id, apos)
                elif self.command == "POST" and partes[2:] == ["decisao"]:
                    self.resposta(202, app.decidir(token, id, corpo))
                elif self.command == "POST" and partes[2:] == ["cancelar"]:
                    self.resposta(200, app.cancelar(token, id))
                elif self.command == "POST" and partes[2:] == ["conciliar"]:
                    self.resposta(200, app.conciliar(token, id))
                else:
                    raise Problema("rota_ausente", 404)
            else:
                raise Problema("rota_ausente", 404)

        def executar(self):
            self.connection.settimeout(5)
            try:
                self.tratar()
            except Problema as e:
                self.resposta(e.status, {"codigo": e.codigo})
            except (ValidationError, ValueError, TypeError):
                self.resposta(422, {"codigo": "entrada_invalida"})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.resposta(500, {"codigo": "falha_interna"})
        do_GET = do_POST = do_PUT = executar
    return Handler


@contextmanager
def servir(app, porta=0, worker=True):
    with exclusividade(app.pasta):
        app.fila.recuperar()
        app.parar.clear()
        servidor = ThreadingHTTPServer(("127.0.0.1", porta), handler_para(app))
        servidor.daemon_threads = True
        web = threading.Thread(target=lambda: servidor.serve_forever(.05), daemon=True)
        trabalho = threading.Thread(target=app.trabalhar, daemon=True)
        web.start()
        if worker:
            trabalho.start()
        try:
            yield f"http://127.0.0.1:{servidor.server_port}"
        finally:
            servidor.shutdown(); servidor.server_close(); web.join(5)
            app.parar.set()
            if worker:
                trabalho.join(10)
                if trabalho.is_alive():
                    raise RuntimeError("worker_nao_drenou")


def chamar(url, token, metodo, caminho, corpo=None, chave=None):
    headers = {"Authorization": "Bearer "+token}
    if chave:
        headers["Idempotency-Key"] = chave
    dados = None
    if corpo is not None:
        headers["Content-Type"] = "application/json"
        dados = json_texto(corpo).encode("utf8")
    req = Request(url+caminho, data=dados, method=metodo, headers=headers)
    try:
        resposta = urlopen(req, timeout=10)
    except HTTPError as e:
        resposta = e
    with resposta:
        return resposta.status, json.loads(resposta.read())


def aguardar(url, token, id, estados, timeout=10):
    prazo = time.monotonic()+timeout
    while time.monotonic() < prazo:
        status, r = chamar(url, token, "GET", "/execucoes/"+id)
        if status != 200:
            raise RuntimeError(r)
        if r["status"] in estados:
            return r
        time.sleep(.01)
    raise TimeoutError("estado_nao_observado")


def executar():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as pasta:
        app = Aplicacao(pasta)
        tokens = app.dominio.preparar()
        with servir(app) as url:
            _, r = chamar(url, tokens["ana"], "POST", "/execucoes",
                {"tipo": "revisao", "texto": "Conferir proposta"}, "pedido-21")
            pausa = aguardar(url, tokens["ana"], r["id"], {"revisao"})
            chamar(url, tokens["bia"], "POST", f'/execucoes/{r["id"]}/decisao',
                   {"aceitar": True, "digest": pausa["digest"]})
            return aguardar(url, tokens["ana"], r["id"], {"concluida"})


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
