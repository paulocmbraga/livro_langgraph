"""Agente de operações: proposta, revisão, destino e pendências duráveis."""
import json
import os
from tempfile import TemporaryDirectory
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from .base import Acao, Problema, digest
from .fila import VERSAO


# trecho:proposta
def planejar(s, runtime: Runtime):
    ctx = runtime.context
    texto = s["pedido"]["texto"]
    # Gramática deliberadamente fechada; não é interpretação por modelo.
    partes = texto.split()
    if len(partes) != 2 or partes[0] not in ("A-17", "B-29"):
        raise Problema("pedido_fora_da_gramatica", 422)
    recurso = ctx.app.dominio.ler_recurso(ctx.trabalho["dono"], partes[0])
    acao = Acao(recurso=partes[0], prioridade=partes[1],
                revisao=recurso["revisao"])
    return {"proposta": {"execucao": ctx.trabalho["id"],
                         "versao": VERSAO, "acao": acao.model_dump()}}
# fim:proposta


def obter_recibo(app, dono, proposta):
    if not app.consulta_disponivel:
        return None
    return app.dominio.consultar_recibo(app.executor_token, dono, proposta)


# trecho:efeito
def aplicar(s, runtime: Runtime):
    ctx = runtime.context
    app, trabalho = ctx.app, ctx.trabalho
    proposta, decisao = s["proposta"], s["decisao"]
    if not decisao["aceitar"]:
        return {"resultado": {"situacao": "rejeitada"}}
    if decisao["digest"] != digest(proposta):
        raise Problema("proposta_divergente")
    if app.fila.enviado(trabalho["id"], proposta):
        recibo = obter_recibo(app, trabalho["dono"], proposta)
        situacao = "concluida" if recibo else "desconhecida"
        return {"resultado": {"situacao": situacao, "recibo": recibo}}
    recibo = app.dominio.aplicar(app.executor_token, trabalho["dono"],
                                proposta, decisao["revisao"])
    if app.falha_destino == "encerrar_processo":
        os._exit(24)  # Somente no subprocesso descartável do laboratório.
    if app.falha_destino == "perder_resposta":
        return {"resultado": {"situacao": "desconhecida", "recibo": None}}
    return {"resultado": {"situacao": "concluida", "recibo": recibo}}
# fim:efeito


# trecho:grafo
def criar_grafo(saver, tipo="operacao"):
    from .cap21 import Contexto, Estado, revisar
    g = StateGraph(Estado, context_schema=Contexto)
    g.add_node("planejar", planejar)
    g.add_node("revisar", revisar)
    g.add_node("aplicar", aplicar)
    g.add_edge(START, "planejar")
    g.add_edge("planejar", "revisar")
    g.add_edge("revisar", "aplicar"); g.add_edge("aplicar", END)
    return g.compile(checkpointer=saver)
# fim:grafo


def executar():
    from .cap21 import Aplicacao, servir, chamar, aguardar
    with TemporaryDirectory() as pasta:
        app = Aplicacao(pasta, falha_destino="perder_resposta")
        tokens = app.dominio.preparar()
        app.executor_token = tokens["bot"]
        with servir(app) as url:
            _, r = chamar(url, tokens["ana"], "POST", "/execucoes",
                {"tipo": "operacao", "texto": "A-17 alta"}, "operacao-24")
            id = r["id"]
            pausa = aguardar(url, tokens["ana"], id, {"revisao"})
            chamar(url, tokens["bia"], "POST", f"/execucoes/{id}/decisao",
                   {"aceitar": True, "digest": pausa["digest"]})
            desconhecida = aguardar(url, tokens["ana"], id, {"desconhecida"})
            _, final = chamar(url, tokens["bia"], "POST",
                              f"/execucoes/{id}/conciliar", {})
            return {"antes": desconhecida["status"], "depois": final["status"],
                    "efeitos": app.dominio.efeitos(),
                    "historico": app.fila.eventos(id)}


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
