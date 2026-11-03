"""L27. Container PostgreSQL exclusivo e temporário, separado dos serviços do autor."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from typing import TypedDict
from urllib.parse import quote
import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph,START,END
from langgraph.types import Command,interrupt

IMAGEM="postgres@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"


def docker(*args,dados=None,ambiente=None):
    return subprocess.run(["docker",*args],input=dados,capture_output=True,check=True,timeout=100,env=ambiente).stdout


class Estado(TypedDict,total=False):
    pedido:str
    aprovado:bool


@contextmanager
def grafo(uri):
    with PostgresSaver.from_conn_string(uri) as saver:
        g=StateGraph(Estado)
        g.add_node("revisar",lambda s:{"aprovado":interrupt(s["pedido"]) is True})
        g.add_edge(START,"revisar");g.add_edge("revisar",END)
        yield g.compile(checkpointer=saver)


def esperar(nome):
    for _ in range(120):
        if subprocess.run(["docker","exec",nome,"pg_isready","-U","postgres"],capture_output=True).returncode==0:
            return
        time.sleep(.5)
    raise TimeoutError("PostgreSQL não disponível")


def medir(uri,prefixo,aberta):
    import threading
    admissao=threading.BoundedSemaphore(2)
    def uma(i):
        t=time.monotonic()
        if not admissao.acquire(blocking=not aberta):
            return {"id":i,"aceita":False,"ms":round(1000*(time.monotonic()-t),2)}
        try:
            with grafo(uri) as g:
                cfg={"configurable":{"thread_id":f"{prefixo}-{i}"}}
                g.invoke({"pedido":str(i)},cfg,durability="sync")
                g.invoke(Command(resume=True),cfg,durability="sync")
                assert g.get_state(cfg).values["aprovado"]
            return {"id":i,"aceita":True,"ms":round(1000*(time.monotonic()-t),2)}
        finally:
            admissao.release()
    with ThreadPoolExecutor(max_workers=8 if aberta else 2) as pool:
        resultados=[]
        for i in range(12):
            resultados.append(pool.submit(uma,i))
            if aberta:
                time.sleep(.002)
        return [f.result() for f in resultados]


def executar(saida):
    saida.mkdir(parents=True,exist_ok=False)
    nome="livro2-lg-"+secrets.token_hex(7)
    senha=secrets.token_urlsafe(20)
    docker("run","--detach","--name",nome,"--publish","127.0.0.1::5432",
           "--env","POSTGRES_PASSWORD",IMAGEM,ambiente={**os.environ,"POSTGRES_PASSWORD":senha})
    try:
        esperar(nome)
        def endereco(banco):
            porta=docker("port",nome,"5432/tcp").decode().strip().split(":")[-1]
            return f"postgresql://postgres:{quote(senha)}@127.0.0.1:{porta}/{banco}?connect_timeout=8"
        uri=endereco("postgres")
        with PostgresSaver.from_conn_string(uri) as s:
            s.setup()
        fechada=medir(uri,"f",False);aberta=medir(uri,"a",True)
        cfg={"configurable":{"thread_id":"pausada"}}
        with grafo(uri) as g:
            g.invoke({"pedido":"concessão"},cfg,durability="sync")
        docker("restart",nome);esperar(nome)
        uri=endereco("postgres")
        with grafo(uri) as g:
            assert g.get_state(cfg).next==("revisar",)
        dump=docker("exec",nome,"pg_dump","-U","postgres","-Fc","postgres")
        docker("exec",nome,"createdb","-U","postgres","restaurada")
        docker("exec","-i",nome,"pg_restore","-U","postgres","-d","restaurada","--exit-on-error",dados=dump)
        with grafo(endereco("restaurada")) as g:
            g.invoke(Command(resume=True),cfg,durability="sync")
            assert g.get_state(cfg).values["aprovado"]
        with grafo(uri) as g:
            assert g.get_state(cfg).next==("revisar",)
        with psycopg.connect(uri) as con:
            versao=con.execute("show server_version").fetchone()[0]
        resultado={"imagem":IMAGEM,"postgres":versao,"fechada":fechada,"aberta":aberta,"dump_bytes":len(dump),
                   "origem":"pausada","copia":"aprovada","efeitos_externos":0}
        (saida/"resultado.json").write_text(json.dumps(resultado,indent=2),encoding="utf8")
    finally:
        docker("rm","-f","-v",nome)


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("saida",type=Path)
    executar(cli.parse_args().saida)
