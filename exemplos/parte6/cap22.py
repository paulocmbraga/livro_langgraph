"""Backup offline, restauração isolada e medição da carga declarada."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sqlite3
import time
from .base import Problema, conexao, json_texto
from .fila import VERSAO, exclusividade


ARQUIVOS = ("servico.sqlite", "dominio.sqlite", "checkpoints.sqlite",
            "conhecimento.sqlite")


def hash_arquivo(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# trecho:backup
def backup(pasta, destino):
    pasta, destino = Path(pasta), Path(destino)
    with exclusividade(pasta):
        if any(not (pasta/n).is_file() for n in ARQUIVOS):
            raise Problema("bancos_incompletos")
        destino.mkdir(parents=True, exist_ok=False)
        registros = {}
        for nome in ARQUIVOS:
            with conexao(pasta/nome) as origem:
                copia = sqlite3.connect(destino/nome)
                try:
                    origem.backup(copia)
                    if copia.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise Problema("backup_invalido")
                finally:
                    copia.close()
            registros[nome] = hash_arquivo(destino/nome)
        manifesto = {"versao": VERSAO, "arquivos": registros,
            "instante_utc": datetime.now(timezone.utc).isoformat(),
            "coordenacao": "servico_parado_lock_exclusivo",
            "credenciais_brutas_incluidas": False}
        (destino/"manifesto.json").write_text(json_texto(manifesto), encoding="utf8")
        return manifesto
# fim:backup


# trecho:restauracao
def restaurar(copia, destino):
    copia, destino = Path(copia), Path(destino)
    m = json.loads((copia/"manifesto.json").read_text(encoding="utf8"))
    if m["versao"] != VERSAO or set(m["arquivos"]) != set(ARQUIVOS):
        raise Problema("backup_incompativel")
    for nome, esperado in m["arquivos"].items():
        if hash_arquivo(copia/nome) != esperado:
            raise Problema("backup_alterado")
    destino.mkdir(parents=True, exist_ok=False)
    for nome in ARQUIVOS:
        shutil.copyfile(copia/nome, destino/nome)
        with conexao(destino/nome) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise Problema("restauracao_invalida")
    with conexao(destino/"servico.sqlite", True) as db:
        db.execute("UPDATE configuracao SET valor='true' WHERE chave='isolado'")
    return {"isolado": True, "arquivos": len(ARQUIVOS)}
# fim:restauracao


# trecho:carga
def medir_carga(url, token, quantidade=12, concorrencia=3, prefixo="carga"):
    from .cap21 import chamar, aguardar
    if quantidade < 1 or concorrencia < 1:
        raise ValueError("carga_invalida")
    def uma(i):
        inicio = time.perf_counter_ns()
        status, r = chamar(url, token, "POST", "/execucoes",
            {"tipo": "eco", "texto": f"item {i}"}, f"{prefixo}-{i}")
        if status not in (200, 202):
            return {"aceita": False, "status_http": status,
                    "latencia_ms": (time.perf_counter_ns()-inicio)/1e6}
        fim = aguardar(url, token, r["id"], {"concluida", "falhou"})
        return {"aceita": True, "status": fim["status"],
                "latencia_ms": (time.perf_counter_ns()-inicio)/1e6}
    inicio = time.perf_counter_ns()
    with ThreadPoolExecutor(max_workers=concorrencia) as pool:
        linhas = list(pool.map(uma, range(quantidade)))
    segundos = (time.perf_counter_ns()-inicio)/1e9
    concluidas = [l for l in linhas if l.get("status") == "concluida"]
    tempos = sorted(l["latencia_ms"] for l in concluidas)
    return {"oferecidas": quantidade, "concorrencia_clientes": concorrencia,
        "concluidas": len(concluidas), "rejeitadas": sum(not l["aceita"] for l in linhas),
        "duracao_s": segundos, "vazao_por_s": len(concluidas)/segundos,
        "p95_concluidas_ms": tempos[math.ceil(.95*len(tempos))-1] if tempos else None,
        "metodo_percentil": "posto_mais_proximo", "observacoes": linhas,
        "protocolo": "HTTP loopback, um worker, clientes fechados, sem aquecimento"}
# fim:carga


# trecho:postgres
def sondar_postgres(dsn):
    """Somente em banco descartável autorizado pelo operador da bancada."""
    from uuid import uuid4
    from langgraph.checkpoint.postgres import PostgresSaver
    from .cap21 import criar_grafo
    with PostgresSaver.from_conn_string(dsn) as saver:
        saver.setup()
        grafo = criar_grafo(saver, "eco")
        config = {"configurable": {"thread_id": "livro-"+str(uuid4())}}
        grafo.invoke({"pedido": {"tipo": "eco", "texto": "sonda"}},
                     config, durability="sync")
        return {"resposta": grafo.get_state(config).values["resultado"]["resposta"],
                "checkpointer": "PostgresSaver", "migracao_do_servico": False}
# fim:postgres


def executar():
    from tempfile import TemporaryDirectory
    from .cap21 import Aplicacao, servir
    with TemporaryDirectory() as temporario:
        pasta = Path(temporario)/"origem"
        app = Aplicacao(pasta)
        tokens = app.dominio.preparar()
        with servir(app) as url:
            carga = medir_carga(url, tokens["ana"])
        m = backup(pasta, Path(temporario)/"copia")
        r = restaurar(Path(temporario)/"copia", Path(temporario)/"restaurada")
        return {"carga": carga, "backup": m, "restauracao": r,
                "postgres": "nao_executado"}


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
