"""Contraprovas de visibilidade, concorrência, autoridade e durabilidade."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Event,Thread
from typing import TypedDict
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph,START,END
from .controles import escrever
from exemplos.avancados.mcp_local import Servidor,VERSAO
from exemplos.parte4.cap15 import criar_pai,Contexto
from l11.campanha import CTX


class S(TypedDict,total=False):
    valor:str
    etapa:str


def worker9(db,modo,barreira):
    with SqliteSaver.from_conn_string(str(db)) as saver:
        g=StateGraph(S)
        g.add_node("registrar",lambda s:{"etapa":"registrada"})
        def esperar(s):
            barreira.set()
            Event().wait(40)
            raise TimeoutError("worker deveria cair")
        g.add_node("esperar",esperar)
        g.add_edge(START,"registrar");g.add_edge("registrar","esperar");g.add_edge("esperar",END)
        g.compile(checkpointer=saver).invoke({"valor":"A"}, {"configurable":{"thread_id":"queda"}},durability=modo)


def modos(pasta):
    registros=[]
    for modo in ("sync","async","exit"):
        db=pasta/(modo+".db")
        barreira=CTX.Event()
        p=CTX.Process(target=worker9,args=(db,modo,barreira))
        p.start()
        try:
            assert barreira.wait(20) and p.is_alive()
        finally:
            p.kill();p.join(10)
        with SqliteSaver.from_conn_string(str(db)) as saver:
            ck=saver.get_tuple({"configurable":{"thread_id":"queda"}})
        dados={} if ck is None else ck.checkpoint["channel_values"]
        assert modo!="sync" or dados.get("etapa")=="registrada"
        registros.append({"modo":modo,"barreira":"esperar","saida_worker":p.exitcode,
                          "checkpoint":ck is not None,"etapa":dados.get("etapa")})
    return registros


def visibilidade():
    class Saida(TypedDict):
        resultado:str
    class Trabalho(Saida,total=False):
        reservado:str
    g=StateGraph(Trabalho,output_schema=Saida)
    g.add_node("analisar",lambda s:{"reservado":"MARCADOR-INTERNO","resultado":"ok"})
    g.add_edge(START,"analisar");g.add_edge("analisar",END)
    app=g.compile()
    final=app.invoke({"resultado":""})
    bruto=list(app.stream({"resultado":""},stream_mode="updates"))
    publico=[{"resultado":v["resultado"]} for ev in bruto for v in ev.values() if "resultado" in v]
    assert "reservado" not in final and "MARCADOR" in str(bruto) and "MARCADOR" not in str(publico)
    return {"final":final,"evento_bruto":bruto,"projecao":publico}


def posse(pasta):
    db=pasta/"posse.db"
    with closing(sqlite3.connect(db)) as c, c:
        c.execute("CREATE TABLE recurso(id PRIMARY KEY,epoca,prioridade)")
        c.execute("INSERT INTO recurso VALUES(1,1,'normal')")
    def gravar(epoca,valor,proteger):
        with closing(sqlite3.connect(db)) as c,c:
            if proteger:
                return c.execute("UPDATE recurso SET prioridade=? WHERE id=1 AND epoca=?",(valor,epoca)).rowcount
            return c.execute("UPDATE recurso SET prioridade=? WHERE id=1",(valor,)).rowcount
    with closing(sqlite3.connect(db)) as c,c:
        c.execute("UPDATE recurso SET epoca=2 WHERE id=1")
    lider=gravar(2,"alta",True)
    antigo=gravar(1,"normal",True)
    mutante=gravar(1,"normal",False)
    assert (lider,antigo,mutante)==(1,0,1)
    return {"novo":lider,"antigo_com_precondicao":antigo,"antigo_sem_precondicao":mutante}


def subgrafos():
    pai=criar_pai(InMemorySaver(),pausar=False)
    def consulta(org):
        cfg={"configurable":{"thread_id":org}}
        ctx=Contexto(org,{"entradas_pai":0,"buscas":0,"revisoes":0})
        return pai.invoke({"pergunta":"VPN"},cfg,context=ctx)["publicado"]
    with ThreadPoolExecutor(2) as pool:
        a,b=pool.map(consulta,["aurora","outra"])
    assert a!=b and "nota_interna" not in str([a,b])
    return {"aurora":a,"outra":b}


def mcp_http():
    import secrets
    token=secrets.token_urlsafe()
    servidor=Servidor()
    config={"permitido":True,"nome":"consultar_chamado"}
    class API(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            if self.path!="/mcp" or self.headers.get("Authorization")!="Bearer "+token:
                self.send_error(401);return
            req=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if req["method"]!="initialize" and self.headers.get("MCP-Protocol-Version")!=VERSAO:
                self.send_error(400);return
            r=servidor.receber(req)
            if req["method"]=="tools/list":
                r["result"]["tools"]=[{**t,"name":config["nome"]} for t in r["result"]["tools"]]
            if req["method"]=="tools/call" and (not config["permitido"] or
                    req["params"]["name"]!=config["nome"]):
                r={"jsonrpc":"2.0","id":req["id"],"result":{"isError":True,"content":[{"type":"text","text":"Recusada"}]}}
            b=b"" if r is None else json.dumps(r).encode()
            self.send_response(202 if r is None else 200)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(b)))
            self.end_headers();self.wfile.write(b)
    with ThreadingHTTPServer(("127.0.0.1",0),API) as h:
        t=Thread(target=h.serve_forever,daemon=True);t.start()
        def chamada(metodo,params,cred=token):
            pedido={"method":metodo,"params":params,"jsonrpc":"2.0"}
            if not metodo.startswith("notifications"):
                pedido["id"]=1
            req=Request(f"http://127.0.0.1:{h.server_port}/mcp",data=json.dumps(pedido).encode(),
                headers={"Authorization":"Bearer "+cred,"Content-Type":"application/json","MCP-Protocol-Version":VERSAO,
                         "Accept":"application/json, text/event-stream"})
            try:
                with urlopen(req,timeout=4) as res:
                    raw=res.read()
                    return json.loads(raw) if raw else res.status
            except HTTPError as e:
                return e.code
        try:
            init=chamada("initialize",{"protocolVersion":VERSAO,"capabilities":{},"clientInfo":{"name":"bancada","version":"1"}})
            assert chamada("notifications/initialized",{})==202
            catalogo=chamada("tools/list",{})["result"]["tools"][0]["name"]
            args={"name":catalogo,"arguments":{"recurso":"A-17"}}
            permitida=chamada("tools/call",args)["result"]
            config["permitido"]=False
            revogada=chamada("tools/call",args)["result"]["isError"]
            config.update(permitido=True,nome="consultar_revisado")
            obsoleta=chamada("tools/call",args)["result"]["isError"]
            invalido=chamada("tools/list",{},"invalida")
            assert not permitida["isError"] and revogada and obsoleta and invalido==401
            return {"versao":init["result"]["protocolVersion"],"catalogo":catalogo,"permitida":permitida,
                    "revogacao_recusada":revogada,"catalogo_obsoleto_recusado":obsoleta,"credencial_invalida":invalido}
        finally:
            h.shutdown();t.join()


def executar(saida):
    saida.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory() as d:
        for n,f in [(2,visibilidade),(9,lambda:modos(Path(d))),(12,lambda:posse(Path(d))),
                    (17,subgrafos),(19,mcp_http)]:
            escrever(saida/f"L{n:02}.json",f())
            print(n,flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("saida",type=Path)
    executar(p.parse_args().saida)
