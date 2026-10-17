"""Clientes e processos descartáveis usados nas verificações locais."""
from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
from .base import Problema
from .cap21 import Aplicacao, aguardar, chamar
from .servico import preparar, carregar


def caso(nome, observado, esperado):
    return {"nome": nome, "observado": observado, "esperado": esperado,
            "confere": observado == esperado}


def recusado(funcao):
    try:
        funcao()
    except Problema as e:
        return e.codigo
    return "aceito"


@contextmanager
def bancada(**opcoes):
    with TemporaryDirectory() as pasta:
        app = Aplicacao(pasta, **opcoes)
        tokens = app.dominio.preparar()
        app.executor_token = tokens["bot"]
        yield app, tokens


def solicitar(url, tokens, chave="pedido", tipo="operacao", texto="A-17 alta"):
    status, r = chamar(url, tokens["ana"], "POST", "/execucoes",
                       {"tipo": tipo, "texto": texto}, chave)
    if status not in (200, 202):
        raise RuntimeError(r)
    id = r["id"]
    pausa = aguardar(url, tokens["ana"], id, {"revisao", "falhou"})
    if pausa["status"] != "revisao":
        raise RuntimeError(pausa)
    return id, pausa


def aprovar(url, tokens, id, pausa, aceitar=True):
    return chamar(url, tokens["bia"], "POST", f"/execucoes/{id}/decisao",
                  {"aceitar": aceitar, "digest": pausa["digest"]})


def desconectar(url, token, id):
    u = urlparse(url)
    cliente = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    cliente.request("GET", f"/execucoes/{id}/eventos",
                    headers={"Authorization": "Bearer "+token})
    resposta = cliente.getresponse()
    linhas = []
    while True:
        linha = resposta.readline().decode("utf8")
        if linha == "\n" or not linha:
            break
        linhas.append(linha)
    resposta.close(); cliente.close()
    return "".join(linhas)


def eventos_http(url, token, id, apos=0):
    u = urlparse(url)
    cliente = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    cliente.request("GET", f"/execucoes/{id}/eventos?apos={apos}",
                    headers={"Authorization": "Bearer "+token})
    resposta = cliente.getresponse()
    texto = resposta.read().decode("utf8")
    resposta.close(); cliente.close()
    return texto


def ambiente_processo():
    return dict(os.environ, PYTHONUTF8="1", LANGSMITH_TRACING="false",
                LANGCHAIN_TRACING_V2="false")


@contextmanager
def processo_http(pasta):
    processo = subprocess.Popen([sys.executable, "-m", "exemplos.parte6.servico",
        "servir", str(pasta), "--porta", "0"], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf8", env=ambiente_processo())
    saidas = queue.Queue()
    leitor = threading.Thread(target=lambda: saidas.put(processo.stdout.readline()), daemon=True)
    leitor.start()
    pid_servidor = None
    try:
        linha = saidas.get(timeout=15)
        if not linha:
            raise RuntimeError("servidor_nao_iniciou: "+processo.stderr.read())
        pronto = json.loads(linha)
        pid_servidor = pronto["pid"]
        yield pronto["url"]
    finally:
        # O launcher de um venv no Windows pode ter um PID diferente do Python.
        if pid_servidor is not None and processo.poll() is None:
            try:
                os.kill(pid_servidor, signal.SIGTERM)
            except ProcessLookupError:
                pass
            processo.wait(timeout=10)
        if processo.poll() is None:
            processo.terminate()
        processo.wait(timeout=10)
        leitor.join(2)
        processo.stdout.close(); processo.stderr.close()


def passo_processo(pasta, falha=""):
    r = subprocess.run([sys.executable, "-m", "exemplos.parte6.servico", "passo",
        str(pasta), "--falha", falha], capture_output=True, text=True,
        encoding="utf8", env=ambiente_processo(), timeout=20)
    if r.returncode not in (0, 24):
        raise RuntimeError(r.stderr)
    return r.returncode


def queda_apos_efeito():
    with TemporaryDirectory() as raiz:
        pasta = Path(raiz)/"bancada"
        preparar(pasta)
        app = carregar(pasta)
        tokens = json.loads((pasta/"credenciais-locais.json").read_text())
        id = app.criar(tokens["ana"], "queda", {"tipo": "operacao", "texto": "A-17 alta"})["id"]
        passo_processo(pasta)
        pausa = app.consultar(tokens["ana"], id)
        app.decidir(tokens["bia"], id, {"aceitar": True, "digest": pausa["digest"]})
        retorno = passo_processo(pasta, "encerrar_processo")
        intermediario = app.fila.obter(id)["status"]
        efeitos_antes = app.dominio.efeitos()
        passo_processo(pasta)
        final = app.consultar(tokens["ana"], id)
        return {"retorno": retorno, "status_antes": intermediario,
                "efeitos_antes": efeitos_antes, "status_final": final["status"],
                "efeitos_depois": app.dominio.efeitos()}
