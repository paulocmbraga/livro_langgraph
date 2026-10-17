"""Recorte A2A 1.0, JSON-RPC por HTTP local; sem certificação de conformidade."""
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
from urllib.parse import urlparse
from uuid import uuid4
import httpx
from .coordenacao import digest
from .mcp_local import validar_resposta

VERSAO = "1.0"
FINAL = {"TASK_STATE_COMPLETED", "TASK_STATE_CANCELED"}


class Falha(Exception):
    def __init__(self, codigo, mensagem):
        self.codigo, self.mensagem = codigo, mensagem
        super().__init__(mensagem)


class Agente:
    def __init__(self):
        self.tokens = {secrets.token_urlsafe(24): "equipe-A",
                       secrets.token_urlsafe(24): "equipe-B"}
        self.tarefas, self.donos, self.recibos = {}, {}, {}
        self.lock = threading.RLock()

    def obter(self, dono, id):
        if self.donos.get(id) != dono:
            raise Falha(-32001, "Tarefa não encontrada")
        return self.tarefas[id]

    # trecho:mensagem
    def enviar(self, dono, mensagem):
        permitidas = {"messageId", "role", "parts", "taskId", "contextId"}
        if not isinstance(mensagem, dict) or set(mensagem) - permitidas:
            raise Falha(-32602, "Mensagem inválida")
        mid, partes = mensagem.get("messageId"), mensagem.get("parts")
        if (type(mid) is not str or not mid or len(mid) > 128
                or mensagem.get("role") != "ROLE_USER"
                or not isinstance(partes, list) or len(partes) != 1
                or not isinstance(partes[0], dict)
                or set(partes[0]) != {"text"}
                or type(partes[0]["text"]) is not str
                or not 1 <= len(partes[0]["text"]) <= 2000):
            raise Falha(-32602, "Conteúdo fora do recorte")
        chave, h = (dono, mid), digest(mensagem)
        if chave in self.recibos:
            anterior, resposta = self.recibos[chave]
            if anterior != h:
                raise Falha(-32602, "messageId reutilizado com outro conteúdo")
            return deepcopy(resposta)
        tarefa = self.continuar_ou_criar(dono, mensagem)
        self.responder(tarefa, partes[0]["text"])
        resposta = {"task": deepcopy(tarefa)}
        self.recibos[chave] = (h, resposta)
        return deepcopy(resposta)
    # fim:mensagem

    def continuar_ou_criar(self, dono, mensagem):
        if "taskId" in mensagem:
            if type(mensagem["taskId"]) is not str:
                raise Falha(-32602, "taskId inválido")
            tarefa = self.obter(dono, mensagem["taskId"])
            if (mensagem.get("contextId") != tarefa["contextId"]
                    or tarefa["status"]["state"] in FINAL):
                raise Falha(-32602, "Continuação inválida")
            return tarefa
        if "contextId" in mensagem:
            raise Falha(-32602, "Novo contexto é criado pelo servidor local")
        id = str(uuid4())
        tarefa = {"id": id, "contextId": str(uuid4()),
                  "status": {"state": "TASK_STATE_SUBMITTED"}}
        self.tarefas[id], self.donos[id] = tarefa, dono
        return tarefa

    def responder(self, tarefa, texto):
        if texto == "priorizar?":
            tarefa["status"] = {"state": "TASK_STATE_INPUT_REQUIRED",
                "message": {"messageId": str(uuid4()), "role": "ROLE_AGENT",
                            "parts": [{"text": "Informe alta ou normal."}]}}
            return
        dado = {"prioridade": "alta" if texto == "alta" else "normal",
                "fonte": "D1", "revisao": 1,
                "texto": "Recomendação preparada para revisão local."}
        tarefa["status"] = {"state": "TASK_STATE_COMPLETED"}
        tarefa["artifacts"] = [{"artifactId": str(uuid4()),
            "parts": [{"text": json.dumps(dado, ensure_ascii=False)}]}]

    def executar(self, dono, metodo, parametros):
        with self.lock:
            if not isinstance(parametros, dict):
                raise Falha(-32602, "Parâmetros inválidos")
            if metodo == "SendMessage":
                if set(parametros) != {"message"}:
                    raise Falha(-32602, "Opção fora do recorte")
                return self.enviar(dono, parametros["message"])
            if metodo in {"GetTask", "CancelTask"}:
                if set(parametros) != {"id"} or type(parametros["id"]) is not str:
                    raise Falha(-32602, "Identificador inválido")
                tarefa = self.obter(dono, parametros["id"])
                if metodo == "CancelTask":
                    if tarefa["status"]["state"] in FINAL:
                        raise Falha(-32002, "Tarefa terminal")
                    tarefa["status"] = {"state": "TASK_STATE_CANCELED"}
                return deepcopy(tarefa)
            raise Falha(-32004, "Operação não implementada neste recorte")


def cartao(url):
    return {"name": "Especialista local", "description": "Propõe prioridade",
        "version": "1.0.0", "supportedInterfaces": [{"url": url + "/rpc",
        "protocolBinding": "JSONRPC", "protocolVersion": VERSAO}],
        "capabilities": {"streaming": False, "pushNotifications": False},
        "securitySchemes": {"bearer": {
            "httpAuthSecurityScheme": {"scheme": "Bearer"}}},
        "securityRequirements": [{"schemes": {"bearer": {"list": []}}}],
        "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
        "skills": [{"id": "prioridade", "name": "Recomendar",
                    "description": "Não altera chamados", "tags": ["triagem"]}]}


@contextmanager
def servidor():
    agente = Agente()

    class HTTP(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def responder_json(self, status, dado):
            corpo = json.dumps(dado, ensure_ascii=False).encode("utf8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            if self.path == "/.well-known/agent-card.json":
                self.responder_json(200, cartao(url))
            else:
                self.responder_json(404, {"erro": "nao_encontrado"})

        def do_POST(self):
            if self.path != "/rpc":
                self.responder_json(404, {"erro": "nao_encontrado"}); return
            auth = self.headers.get("Authorization", "")
            dono = agente.tokens.get(auth.removeprefix("Bearer ")) if auth.startswith("Bearer ") else None
            if dono is None:
                self.responder_json(401, {"erro": "credencial_invalida"}); return
            id = None
            try:
                tamanho = int(self.headers.get("Content-Length", "0"))
                if not 0 < tamanho <= 16384:
                    raise Falha(-32600, "Corpo fora do limite")
                try:
                    pedido = json.loads(self.rfile.read(tamanho))
                except (ValueError, UnicodeError):
                    raise Falha(-32700, "JSON inválido") from None
                if (not isinstance(pedido, dict) or pedido.get("jsonrpc") != "2.0"
                        or type(pedido.get("id")) is not int
                        or type(pedido.get("method")) is not str):
                    raise Falha(-32600, "Envelope inválido")
                id = pedido["id"]
                if self.headers.get("A2A-Version", "0.3") != VERSAO:
                    raise Falha(-32009, "Versão não suportada")
                resultado = agente.executar(dono, pedido["method"], pedido.get("params"))
                resposta = {"jsonrpc": "2.0", "id": id, "result": resultado}
            except (ValueError, Falha) as e:
                resposta = {"jsonrpc": "2.0", "id": id, "error": {
                    "code": e.codigo if isinstance(e, Falha) else -32600,
                    "message": str(e)}}
            self.responder_json(200, resposta)

    http = ThreadingHTTPServer(("127.0.0.1", 0), HTTP)
    url = f"http://127.0.0.1:{http.server_port}"
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield url, agente
    finally:
        http.shutdown(); http.server_close(); thread.join(timeout=3)


class Cliente:
    def __init__(self, url, token):
        u = urlparse(url)
        if u.scheme != "http" or u.hostname != "127.0.0.1" or u.path:
            raise ValueError("Bancada restrita ao loopback")
        self.url, self.token, self.numero = url, token, 0

    def descobrir(self):
        with httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as c:
            r = c.get(self.url + "/.well-known/agent-card.json")
            r.raise_for_status(); card = r.json()
        esperada = {"url": self.url + "/rpc", "protocolBinding": "JSONRPC",
                    "protocolVersion": VERSAO}
        if card.get("supportedInterfaces") != [esperada]:
            raise ValueError("Interface não admitida")
        esquema = {"httpAuthSecurityScheme": {"scheme": "Bearer"}}
        requisitos = [{"schemes": {"bearer": {"list": []}}}]
        if (card.get("securitySchemes", {}).get("bearer") != esquema
                or card.get("securityRequirements") != requisitos):
            raise ValueError("Autenticação anunciada não admitida")
        return card

    def chamar(self, metodo, params, versao=VERSAO):
        self.numero += 1
        with httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as c:
            r = c.post(self.url + "/rpc", headers={"A2A-Version": versao,
                "Authorization": "Bearer " + self.token}, json={"jsonrpc": "2.0",
                "id": self.numero, "method": metodo, "params": params})
            r.raise_for_status()
        return validar_resposta(r.json(), self.numero)

    # trecho:continuidade
    def enviar(self, texto, mid, tarefa=None):
        mensagem = {"messageId": mid, "role": "ROLE_USER",
                    "parts": [{"text": texto}]}
        if tarefa:
            mensagem.update(taskId=tarefa["id"], contextId=tarefa["contextId"])
        recebida = self.chamar("SendMessage", {"message": mensagem})["task"]
        if tarefa and (recebida["id"] != tarefa["id"]
                or recebida["contextId"] != tarefa["contextId"]):
            raise ValueError("Resposta de outra tarefa")
        return recebida
    # fim:continuidade


def demonstrar():
    with servidor() as (url, agente):
        c = Cliente(url, next(iter(agente.tokens)))
        card = c.descobrir()
        pendente = c.enviar("priorizar?", "m1")
        final = c.enviar("alta", "m2", pendente)
        lida = c.chamar("GetTask", {"id": final["id"]})
        outra = c.enviar("priorizar?", "m3")
        cancelada = c.chamar("CancelTask", {"id": outra["id"]})
        return {"versao": card["supportedInterfaces"][0]["protocolVersion"],
                "estados": [pendente["status"]["state"], lida["status"]["state"],
                            cancelada["status"]["state"]],
                "artefato": json.loads(final["artifacts"][0]["parts"][0]["text"]),
                "transporte": "HTTP loopback / JSONRPC"}
