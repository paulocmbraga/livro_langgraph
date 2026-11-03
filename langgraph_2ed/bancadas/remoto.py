"""Perfil A2A 1.0 de criação, consulta e cancelamento. TLS e descoberta OAuth fora do ensaio."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
from uuid import uuid4

from .controles import escrever
from exemplos.avancados.a2a_local import Cliente, cartao
from exemplos.avancados.mcp_local import ErroProtocolo
from l11.campanha import CTX, servico
from l11.destino import digest, requisicao


def operacao(db, destino, dono, metodo, params, cair_apos_credito=False):
    with closing(sqlite3.connect(db, timeout=6)) as con, con:
        con.row_factory = sqlite3.Row
        con.execute("BEGIN IMMEDIATE")
        if metodo == "SendMessage":
            m = params["message"]
            if (set(m) != {"messageId","role","parts"} or m["role"]!="ROLE_USER" or
                    not isinstance(m["messageId"],str) or not m["messageId"] or
                    len(m["parts"])!=1 or not isinstance(m["parts"][0].get("text"),str)):
                raise ValueError("-32602")
            r = con.execute("SELECT * FROM tarefas WHERE dono=? AND mid=?", (dono,m["messageId"])).fetchone()
            if r and r["assinatura"] != digest(m):
                raise ValueError("-32602")
            if not r:
                ident = str(uuid4())
                con.execute("INSERT INTO tarefas VALUES (?,?,?,?,?,?,?,?,0)",
                            (ident,dono,m["messageId"],digest(m),str(uuid4()),"WORKING",None,1))
                r = con.execute("SELECT * FROM tarefas WHERE id=?", (ident,)).fetchone()
        elif metodo in ("GetTask","CancelTask","concluir_local"):
            r = con.execute("SELECT * FROM tarefas WHERE id=? AND dono=?", (params["id"],dono)).fetchone()
            if not r:
                raise ValueError("-32001")
            status = r["status"]
            if metodo == "CancelTask":
                if status=="COMPLETED":
                    raise ValueError("-32002")
                if r["iniciada"] and status=="WORKING":
                    # O POST pode estar em voo. Ausência ainda não permite cancelar.
                    code, corpo = requisicao(destino,"/recibo/a2a-"+r["id"])
                    if code == 200:
                        con.execute("UPDATE tarefas SET status='COMPLETED',recibo=? WHERE id=?",
                                    (corpo["recibo"],r["id"]))
                        con.commit()
                    raise ValueError("-32002")
                con.execute("UPDATE tarefas SET status='CANCELED' WHERE id=?", (r["id"],))
            if metodo == "concluir_local" and status=="WORKING":
                con.execute("UPDATE tarefas SET iniciada=1 WHERE id=?",(r["id"],))
                con.commit()
                con.execute("BEGIN IMMEDIATE")
                code, recibo = requisicao(destino,"/creditos",{"chave":"a2a-"+r["id"],
                    "pedido":{"intencao":r["id"],"minutos":30}})
                if code not in (200,201):
                    raise RuntimeError("efeito não confirmado")
                if cair_apos_credito:
                    os._exit(74)
                con.execute("UPDATE tarefas SET status='COMPLETED', recibo=? WHERE id=?",
                            (recibo["recibo"],r["id"]))
            r = con.execute("SELECT * FROM tarefas WHERE id=?",(r["id"],)).fetchone()
        else:
            raise ValueError("-32601")
        tarefa = {"id":r["id"],"contextId":r["contexto"],"status":{"state":"TASK_STATE_"+r["status"]}}
        if r["recibo"]:
            tarefa["artifacts"] = [{"artifactId":r["id"]+"-v1","parts":[{"text":r["recibo"]}],
                                    "metadata":{"geracao":r["geracao"]}}]
        return {"task":tarefa} if metodo=="SendMessage" else tarefa


def atender(db, destino, tokens, porta, perder, marco):
    with closing(sqlite3.connect(db)) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS tarefas(id TEXT PRIMARY KEY,dono TEXT,mid TEXT,
                    assinatura TEXT,contexto TEXT,status TEXT,recibo TEXT,geracao INTEGER,
                    iniciada INTEGER NOT NULL DEFAULT 0,UNIQUE(dono,mid))""")
    class API(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def enviar(self, status, resposta):
            b = json.dumps(resposta).encode()
            self.send_response(status)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path=="/.well-known/agent-card.json":
                self.enviar(200, cartao(url))
            else:
                self.enviar(404,{})

        def do_POST(self):
            dono = tokens.get(self.headers.get("Authorization",""))
            if not dono:
                return self.enviar(401,{})
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            ident = req.get("id")
            try:
                if self.path!="/rpc" or self.headers.get("A2A-Version")!="1.0":
                    raise ValueError("-32009")
                # A conclusão é operação privada do worker; não integra o protocolo remoto.
                if req["method"]=="concluir_local":
                    raise ValueError("-32601")
                r = operacao(db,destino,dono,req["method"],req["params"])
                if perder and req["method"]=="SendMessage":
                    marco.set()
                    os._exit(73)  # só o especialista descartável; commit precede este ponto.
                resp = {"result":r}
            except ValueError as exc:
                resp = {"error":{"code":int(str(exc)),"message":"operação recusada"}}
            self.enviar(200,{"jsonrpc":"2.0","id":ident,**resp})
    with ThreadingHTTPServer(("127.0.0.1",0),API) as s:
        url=f"http://127.0.0.1:{s.server_port}"
        porta.send(url)
        porta.close()
        s.serve_forever()


@contextmanager
def especialista(db,destino,tokens,perder=False):
    rx,tx=CTX.Pipe(False)
    marco=CTX.Event()
    p=CTX.Process(target=atender,args=(db,destino,tokens,tx,perder,marco))
    p.start()
    tx.close()
    try:
        if not rx.poll(20):
            raise TimeoutError("especialista não iniciou")
        yield rx.recv(),p,marco
    finally:
        rx.close()
        if p.is_alive():
            p.terminate()
        p.join(10)


def campanha(saida):
    saida.mkdir(parents=True,exist_ok=False)
    import httpx
    ta,tb=secrets.token_urlsafe(),secrets.token_urlsafe()
    tokens={"Bearer "+ta:"A","Bearer "+tb:"B"}
    with tempfile.TemporaryDirectory() as td, servico(Path(td)) as (destino,*_):
        db=Path(td)/"tarefas.sqlite"
        with especialista(db,destino,tokens,True) as (url,p,barreira):
            c=Cliente(url,ta)
            c.descobrir()
            try:
                c.enviar("reservar","m1")
                raise AssertionError("resposta deveria ter sido perdida")
            except httpx.TransportError:
                pass
            p.join(10)
            assert barreira.is_set() and p.exitcode==73
            with closing(sqlite3.connect(db)) as con:
                antes=con.execute("SELECT id,contexto FROM tarefas").fetchall()
            assert len(antes)==1
        with especialista(db,destino,tokens) as (url,p,_):
            c=Cliente(url,ta)
            rev=c.enviar("reservar","m1")
            ident=rev["id"]
            assert [(ident,rev["contextId"])]==antes
            erros={}
            for nome,acao in [("digest",lambda:c.enviar("alterada","m1")),
                              ("outro_principal",lambda:Cliente(url,tb).chamar("GetTask",{"id":ident}))]:
                try:
                    acao()
                    raise AssertionError("operação deveria falhar")
                except ErroProtocolo as e:
                    erros[nome]=str(e)
            assert erros=={"digest":"-32602","outro_principal":"-32001"}
            def concluir(t):
                return operacao(db,destino,"A","concluir_local",{"id":t})
            antes_cancelar=c.enviar("reservar","m2")["id"]
            c.chamar("CancelTask",{"id":antes_cancelar})
            assert concluir(antes_cancelar)["status"]["state"]=="TASK_STATE_CANCELED"
            ok=concluir(ident)
            try:
                c.chamar("CancelTask",{"id":ident})
                raise AssertionError("cancelamento terminal admitido")
            except ErroProtocolo as e:
                assert str(e)=="-32002"
            corrida=c.enviar("reservar","m3")["id"]
            def cancelar():
                try:
                    return c.chamar("CancelTask",{"id":corrida})["status"]["state"]
                except ErroProtocolo as e:
                    return str(e)
            with ThreadPoolExecutor(2) as pool:
                f=pool.submit(cancelar)
                g=pool.submit(concluir,corrida)
                f.result();g.result()
            terminal=c.chamar("GetTask",{"id":corrida})
            def contar(t):
                return requisicao(destino,"/auditoria/"+t)[1]
            livro={t:contar(t) for t in (ident,antes_cancelar,corrida)}
            assert len(livro[ident])==1 and not livro[antes_cancelar]
            assert len(livro[corrida])==int(terminal["status"]["state"]=="TASK_STATE_COMPLETED")
            assert ok["artifacts"][0]["parts"][0]["text"]==livro[ident][0]["recibo"]
            perdida=c.enviar("reservar","m4")["id"]
            filho=CTX.Process(target=operacao,args=(db,destino,"A","concluir_local",{"id":perdida},True))
            filho.start();filho.join(20)
            if filho.is_alive():
                filho.kill();filho.join()
            assert filho.exitcode==74 and len(contar(perdida))==1
            antes_consulta=c.chamar("GetTask",{"id":perdida})
            assert antes_consulta["status"]["state"]=="TASK_STATE_WORKING"
            try:
                c.chamar("CancelTask",{"id":perdida})
                raise AssertionError("cancelamento de efeito confirmado foi admitido")
            except ErroProtocolo as e:
                assert str(e)=="-32002"
            recuperada=c.chamar("GetTask",{"id":perdida})
            assert recuperada["artifacts"][0]["parts"][0]["text"]==contar(perdida)[0]["recibo"]
            # O consumidor conserva a geração corrente e rejeita uma entrega tardia.
            corrente=ok["artifacts"][0]
            atrasado={**corrente,"metadata":{"geracao":0}}
            publicados=[a for a in (corrente,atrasado) if a["metadata"]["geracao"]==1]
            assert publicados==[corrente]
            escrever(saida/"resultado.json",{"versao":"1.0","saida_primeiro":73,"antes":antes,
                "retomada":rev,"erros":erros,"concluida":ok,"corrida":terminal,"livro":livro,
                "geracoes_recebidas":[1,0],"artefatos_publicados":publicados,
                "queda_apos_credito":{"saida":74,"antes":antes_consulta,"depois":recuperada,
                "efeitos":contar(perdida)}})


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("saida",type=Path)
    campanha(cli.parse_args().saida)
