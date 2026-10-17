"""Recorte MCP 2025-11-25 em stdio real: inicialização, lista e chamada de leitura."""
from contextlib import AbstractContextManager
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading

VERSAO = "2025-11-25"
RAIZ = Path(__file__).resolve().parents[2]
SCHEMA = {"type": "object", "properties": {"recurso": {"type": "string"}},
          "required": ["recurso"], "additionalProperties": False}
FERRAMENTA = {"name": "consultar_chamado", "description": "Consulta no escopo Aurora.",
              "inputSchema": SCHEMA}


class ErroProtocolo(ValueError):
    pass


# trecho:correlacao
def validar_resposta(resposta, identidade):
    if type(resposta) is not dict or resposta.get("jsonrpc") != "2.0":
        raise ErroProtocolo("envelope_invalido")
    if type(resposta.get("id")) is not int or resposta["id"] != identidade:
        raise ErroProtocolo("id_divergente")
    if ("result" in resposta) == ("error" in resposta):
        raise ErroProtocolo("resultado_ambiguo")
    if "error" in resposta:
        raise ErroProtocolo(str(resposta["error"].get("code")))
    return resposta["result"]
# fim:correlacao


class Servidor:
    def __init__(self):
        self.estado = "novo"

    def receber(self, pedido):
        identidade = pedido.get("id") if type(pedido) is dict else None
        def erro(codigo, mensagem):
            return {"jsonrpc": "2.0", "id": identidade,
                    "error": {"code": codigo, "message": mensagem}}
        if type(pedido) is not dict or pedido.get("jsonrpc") != "2.0":
            return erro(-32600, "Invalid Request")
        metodo, params = pedido.get("method"), pedido.get("params", {})
        if type(metodo) is not str or type(params) is not dict:
            return erro(-32600, "Invalid Request")
        if "id" not in pedido:
            if metodo == "notifications/initialized" and self.estado == "negociado":
                self.estado = "pronto"
            return None
        if type(identidade) is not int:
            return erro(-32600, "Invalid Request")
        if metodo == "initialize":
            if (self.estado != "novo" or type(params.get("capabilities")) is not dict
                    or type(params.get("clientInfo")) is not dict
                    or type(params.get("protocolVersion")) is not str):
                return erro(-32602, "Invalid params")
            self.estado = "negociado"
            result = {"protocolVersion": VERSAO, "capabilities": {"tools": {}},
                      "serverInfo": {"name": "aurora-leitura", "version": "1.0"}}
        elif self.estado != "pronto":
            return erro(-32000, "Not initialized")
        elif metodo == "tools/list":
            if params:
                return erro(-32602, "Invalid params")
            result = {"tools": [FERRAMENTA]}
        elif metodo == "tools/call":
            if params.get("name") != FERRAMENTA["name"]:
                return erro(-32602, "Unknown tool")
            args = params.get("arguments")
            ok = (type(args) is dict and set(args) == {"recurso"}
                  and type(args["recurso"]) is str
                  and re.fullmatch(r"A-\d{2}", args["recurso"]) is not None)
            # Conhecer o nome não autoriza outro tenant nem cria recurso.
            if not ok or args["recurso"] != "A-17":
                result = {"content": [{"type": "text", "text": "Consulta recusada."}],
                          "isError": True}
            else:
                dado = {"recurso": "A-17", "status": "aberto", "revisao": 1}
                result = {"structuredContent": dado, "isError": False,
                          "content": [{"type": "text", "text": json.dumps(dado)}]}
        else:
            return erro(-32601, "Method not found")
        return {"jsonrpc": "2.0", "id": identidade, "result": result}


def servir():
    servidor = Servidor()
    while linha := sys.stdin.readline(16385):
        if len(linha) > 16384:
            raise SystemExit("limite_de_mensagem")
        try:
            resposta = servidor.receber(json.loads(linha))
        except json.JSONDecodeError:
            resposta = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "Parse error"}}
        if resposta is not None:
            print(json.dumps(resposta, ensure_ascii=False), flush=True)


class Cliente(AbstractContextManager):
    def __init__(self, timeout=3):
        self.timeout, self.sequencia, self.transcrito = timeout, 0, []
        self.processo = subprocess.Popen(
            [sys.executable, "-m", "exemplos.avancados.mcp_local", "--servidor"],
            cwd=RAIZ, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf8", bufsize=1,
            env=dict(os.environ, PYTHONUTF8="1"),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.fila = queue.Queue()
        def ler():
            for linha in self.processo.stdout:
                self.fila.put(linha)
            self.fila.put(None)
        self.leitor = threading.Thread(target=ler, daemon=True)
        self.leitor.start()

    def enviar(self, pedido):
        self.processo.stdin.write(json.dumps(pedido)+"\n")
        self.processo.stdin.flush()
        self.transcrito.append({"envio": pedido})

    def chamar(self, metodo, params=None):
        self.sequencia += 1
        self.enviar({"jsonrpc": "2.0", "id": self.sequencia,
                     "method": metodo, "params": params or {}})
        try:
            linha = self.fila.get(timeout=self.timeout)
        except queue.Empty as e:
            raise TimeoutError("mcp_sem_resposta") from e
        if linha is None:
            raise ErroProtocolo("servidor_encerrado")
        resposta = json.loads(linha)
        self.transcrito.append({"recebimento": resposta})
        return validar_resposta(resposta, self.sequencia)

    # trecho:inicializacao
    def inicializar(self, versao=VERSAO):
        r = self.chamar("initialize", {
            "protocolVersion": versao, "capabilities": {},
            "clientInfo": {"name": "livro-langgraph", "version": "1.0"}})
        if r["protocolVersion"] != versao or "tools" not in r["capabilities"]:
            raise ErroProtocolo("negociacao_incompativel")
        self.enviar({"jsonrpc": "2.0", "method": "notifications/initialized"})
        catalogo = self.chamar("tools/list")["tools"]
        if catalogo != [FERRAMENTA]:
            raise ErroProtocolo("catalogo_divergente")
        return catalogo

    def consultar(self, recurso):
        r = self.chamar("tools/call", {"name": "consultar_chamado",
                                       "arguments": {"recurso": recurso}})
        if r.get("isError") is not False:
            raise ValueError("ferramenta_recusou")
        d = r.get("structuredContent")
        if (type(d) is not dict or set(d) != {"recurso", "status", "revisao"}
                or d["recurso"] != recurso or d["status"] not in {"aberto", "fechado"}
                or type(d["revisao"]) is not int or d["revisao"] < 1):
            raise ErroProtocolo("retorno_da_ferramenta_invalido")
        return d
    # fim:inicializacao

    def __exit__(self, *args):
        self.processo.stdin.close()
        try:
            self.processo.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.processo.kill()
            self.processo.wait(timeout=2)
        self.leitor.join(timeout=2)
        self.processo.stdout.close()


def demonstrar():
    with Cliente() as c:
        catalogo = c.inicializar()
        d = c.consultar("A-17")
        recusa = c.chamar("tools/call", {"name": "consultar_chamado", "arguments": {"recurso": "B-29"}})
        return {"versao": VERSAO, "ferramentas": len(catalogo), "consulta": d,
                "cruzamento_recusado": recusa["isError"], "transcrito": c.transcrito}


if __name__ == "__main__":
    if "--servidor" in sys.argv:
        servir()
    else:
        print(json.dumps(demonstrar(), ensure_ascii=False))
