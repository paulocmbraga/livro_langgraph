"""Subprocessos descartáveis dos laboratórios 9 e 10."""
import argparse
import json
import os
from pathlib import Path
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from . import cap09, cap10
from .destino import Destino, Diario


def executar(pasta, acao):
    destino = Destino(pasta)
    arquivo = str(Path(pasta)/"grafo.sqlite")
    config = cap09.configuracao("aurora:duravel")
    if acao.startswith("memoria"):
        grafo = cap09.criar_grafo(InMemorySaver(), True)
        if acao == "memoria_iniciar":
            grafo.invoke({"chamado_id": "A-17"}, config,
                         context=cap09.Contexto(destino))
        return {"pid": os.getpid(), **cap09.inspecionar(grafo, config)}
    with SqliteSaver.from_conn_string(arquivo) as saver:
        if acao.startswith("leitura"):
            grafo = cap09.criar_grafo(saver, True)
            ctx = cap09.Contexto(destino)
            if acao == "leitura_iniciar":
                grafo.invoke({"chamado_id": "A-17"}, config,
                             context=ctx, durability="sync")
            elif acao == "leitura_continuar":
                grafo.invoke(None, config, context=ctx, durability="sync")
            return {"pid": os.getpid(), **cap09.inspecionar(grafo, config)}
        grafo = cap10.criar_grafo(saver)
        ctx = cap10.Contexto(destino, Diario(pasta))
        proposta = cap10.proposta_padrao()
        if acao == "operacao_iniciar":
            grafo.invoke({"proposta": proposta}, config, context=ctx,
                         durability="sync")
        elif acao == "operacao_cair":
            ctx.falha = "encerrar_processo"
            grafo.invoke(cap10.aprovar(proposta), config, context=ctx,
                         durability="sync")
            raise AssertionError("subprocesso_deveria_terminar")
        elif acao == "operacao_recuperar":
            grafo.invoke(None, config, context=ctx, durability="sync")
        else:
            raise ValueError("acao_invalida")
        snapshot = grafo.get_state(config)
        return {"pid": os.getpid(), "situacao": snapshot.values.get("situacao"),
                "proximos": list(snapshot.next), **destino.contadores()}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pasta", type=Path)
    p.add_argument("acao")
    args = p.parse_args()
    print(json.dumps(executar(args.pasta, args.acao), ensure_ascii=False))
