"""Ensaios de cancelamento, revogação, observabilidade e compatibilidade."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import sqlite3
import tempfile
import time
from threading import Event,Thread
from urllib.request import urlopen
from .controles import escrever


def bloqueio():
    entrou,liberar,acabou=Event(),Event(),Event()
    class API(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            entrou.set();liberar.wait(10)
            try:
                self.send_response(200);self.end_headers();self.wfile.write(b"ok")
            except OSError:
                pass
            finally:
                acabou.set()
    with ThreadingHTTPServer(("127.0.0.1",0),API) as h:
        t=Thread(target=h.serve_forever,daemon=True);t.start()
        try:
            inicio=time.monotonic()
            try:
                with urlopen(f"http://127.0.0.1:{h.server_port}",timeout=.15) as res:
                    res.read()
                raise AssertionError("timeout esperado")
            except TimeoutError:
                ms=(time.monotonic()-inicio)*1000
            assert entrou.is_set() and not acabou.is_set()
            liberar.set();assert acabou.wait(2)
            return {"cliente":"timeout","ms":round(ms,1),"remoto_no_timeout":"em execução",
                    "remoto_apos_liberacao":"concluído"}
        finally:
            liberar.set();h.shutdown();t.join()


def memoria(pasta):
    db=pasta/"registro.db"
    with closing(sqlite3.connect(db)) as c,c:
        c.execute("CREATE TABLE perfil(id PRIMARY KEY,valor,revisao,permite)")
        c.execute("INSERT INTO perfil VALUES(1,'pt',1,1)")
    lido,revogado=Event(),Event()
    def leitor():
        with closing(sqlite3.connect(db)) as c:
            cache=c.execute("SELECT valor,revisao FROM perfil WHERE id=1").fetchone()
            lido.set();assert revogado.wait(6)
            atual=c.execute("SELECT valor,revisao FROM perfil WHERE id=1 AND permite=1").fetchone()
        return {"indice_guardado":cache,"resumo_antigo":cache[0],"cache_sem_controle":cache[0],
                "publicacao_autorizada":atual}
    def escritor():
        assert lido.wait(6)
        with closing(sqlite3.connect(db)) as c,c:
            c.execute("UPDATE perfil SET valor='es', revisao=2, permite=0 WHERE id=1 AND revisao=1")
        revogado.set()
    with ThreadPoolExecutor(2) as pool:
        f=pool.submit(leitor);pool.submit(escritor).result();r=f.result()
    assert r["indice_guardado"]==("pt",1) and r["publicacao_autorizada"] is None
    return r


def intervalos():
    registros=[]
    for lento in ("fila","recuperacao","geracao"):
        inicio=time.perf_counter(); fases={}
        for nome in ("fila","recuperacao","geracao"):
            a=time.perf_counter()
            time.sleep(.04 if nome==lento else .002)
            fases[nome]=round((time.perf_counter()-a)*1000,3)
        registros.append({"atraso_em":lento,"fases_ms":fases,"parede_ms":round((time.perf_counter()-inicio)*1000,3),
                          "tokens":None,"perfil":"atraso injetado, sem inferência"})
        assert max(fases,key=fases.get)==lento
    return registros


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("saida",type=Path)
    saida=p.parse_args().saida;saida.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory() as temp:
        for n,r in [(7,bloqueio()),(16,memoria(Path(temp))),(26,intervalos())]:
            escrever(saida/f"L{n:02}.json",r)
