"""Quatro incidentes compostos com controles que divergem no requisito de negócio."""
import argparse
from pathlib import Path
import sqlite3
from contextlib import closing
import secrets
import tempfile
from typing import TypedDict
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt,Command
from .controles import escrever
from .remoto import especialista, operacao
from l11.campanha import servico
from l11.destino import requisicao
from exemplos.avancados.a2a_local import Cliente
from exemplos.avancados.mcp_local import Cliente as Ferramenta
import httpx


class Conhecimento(TypedDict,total=False):
    pergunta:str
    trecho:str
    revisao:int
    resposta:str


def conhecimento(proteger):
    indice={"r":1,"texto":"O manual recomenda a porta 8443."}
    def recuperar(s):
        return {"trecho":indice["texto"],"revisao":indice["r"]}
    def atualizar(s):
        indice.update(r=2,texto="O manual recomenda a porta 9443.")
        return {}
    def publicar(s):
        if proteger and s["revisao"]!=indice["r"]:
            return {"resposta":"abster: revisão mudou"}
        return {"resposta":s["trecho"]+f" [manual r{indice['r']}]"}
    g=StateGraph(Conhecimento)
    g.add_sequence([recuperar,atualizar,publicar])
    g.add_edge(START,"recuperar");g.add_edge("publicar",END)
    return g.compile().invoke({"pergunta":"Que porta devo usar?"})


def operacoes(pasta):
    from l11.campanha import preparar,ler_grafo,worker,concluir
    d=pasta/"grafo";d.mkdir()
    with servico(pasta) as (url,commit,liberar,ocultar):
        _,voto=preparar(d,url,"op")
        with worker(d,url,"op","estavel","timeout",False,voto) as (w,_):
            assert commit.wait(30)
            ocultar.set()
            concluir(w)
        fase=ler_grafo(d,url,"op")["estado"]["fase"]
        liberar.set();ocultar.clear()
        # Revogação impede *novos* efeitos. O reconciliador usa apenas GET.
        papel={"pode_escrever":False}
        def reconciliar(ident):
            status,body=requisicao(url,"/recibo/aurora-"+ident)
            if status==200:
                return {"fase":"confirmada","recibo":body["recibo"]}
            return {"fase":"negada" if not papel["pode_escrever"] else "revisar"}
        confirmada=reconciliar("op");negada=reconciliar("nova")
        livro=requisicao(url,"/auditoria/op")[1]
        assert fase=="desconhecida" and confirmada["recibo"]==livro[0]["recibo"] and negada["fase"]=="negada"
        return {"antes":fase,"apos_revogacao":papel,"historica":confirmada,"nova":negada,
                "efeitos_antigos":len(livro),"efeitos_novos":len(requisicao(url,"/auditoria/nova")[1])}


def especialistas(pasta):
    token=secrets.token_urlsafe()
    cred={"Bearer "+token:"A"}
    with servico(pasta) as (destino,*_), Ferramenta() as mcp:
        mcp.inicializar()
        consulta=mcp.consultar("A-17")
        db=pasta/"agente.sqlite"
        with especialista(db,destino,cred,True) as (url,p,marco):
            try:
                Cliente(url,token).enviar("priorizar "+consulta["recurso"],"assoc-1")
                raise AssertionError("perda não observada")
            except httpx.TransportError:
                pass
            p.join(10)
            assert marco.is_set() and p.exitcode==73
        with especialista(db,destino,cred) as (url,p,_):
            cli=Cliente(url,token)
            tarefa=cli.enviar("priorizar "+consulta["recurso"],"assoc-1")
            operacao(db,destino,"A","concluir_local",{"id":tarefa["id"]})
            final=cli.chamar("GetTask",{"id":tarefa["id"]})
            bom=final["artifacts"][0]
            antigo={**bom,"artifactId":"anterior","metadata":{"geracao":0}}
            versoes=[bom,antigo]
            ingenuo=versoes[-1]
            atual=next(a for a in reversed(versoes) if a["metadata"]["geracao"]==1)
            assert atual==bom and ingenuo!=bom
            return {"ferramenta":consulta,"mensagem":"assoc-1","tarefa":tarefa["id"],"contexto":tarefa["contextId"],
                    "revisao_esperada":1,"mutante":ingenuo,"publicado":atual,
                    "efeitos":len(requisicao(destino,"/auditoria/"+tarefa["id"])[1])}


class Revisao(TypedDict,total=False):
    proposta:int
    autorizado:bool
    versao:str


def restaurar(pasta):
    cfg={"configurable":{"thread_id":"plantao"}}
    def grafo(con,versao,livro):
        def revisar(s):
            voto=interrupt({"minutos":s["proposta"],"versao":s["versao"]})
            # Mutante ignora a versão do voto e dobra o pedido no despacho.
            minutos=s["proposta"]*(2 if versao=="regressao" else 1)
            if voto=={"minutos":s["proposta"],"versao":s["versao"]}:
                livro.append(minutos)
            return {"autorizado":bool(livro)}
        g=StateGraph(Revisao)
        g.add_node("revisar",revisar);g.add_edge(START,"revisar");g.add_edge("revisar",END)
        return g.compile(checkpointer=SqliteSaver(con))
    origem=pasta/"origem.db";livro_original=[]
    with closing(sqlite3.connect(origem,check_same_thread=False)) as c:
        g=grafo(c,"v1",livro_original)
        g.invoke({"proposta":30,"versao":"v1"},cfg,durability="sync")
        registros={}
        for nome in ("regressao","v1"):
            with closing(sqlite3.connect(pasta/(nome+".db"),check_same_thread=False)) as cp:
                c.backup(cp)
                isolado=[]
                candidato=grafo(cp,nome,isolado)
                candidato.invoke(Command(resume={"minutos":30,"versao":"v1"}),cfg,durability="sync")
                registros[nome]=isolado
        assert g.get_state(cfg).next==("revisar",) and not livro_original
    assert registros=={"regressao":[60],"v1":[30]}
    return {"restauros":registros,"origem":"pausada","efeitos_na_origem":livro_original,
            "decisao":"rejeitar regressão; manter v1"}


def executar(saida):
    saida.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory() as td:
        base=Path(td)
        for n,func in [(29,lambda _:{"mutante":conhecimento(False),"candidata":conhecimento(True)}),
                       (30,operacoes),(31,especialistas),(32,restaurar)]:
            pasta=base/str(n);pasta.mkdir()
            doc=func(pasta)
            escrever(saida/f"L{n}.json",doc)
            print(n,flush=True)


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("saida",type=Path)
    executar(cli.parse_args().saida)
