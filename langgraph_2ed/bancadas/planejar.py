"""Compara políticas em grafos completos sem trocar as ferramentas entre tratamentos."""
import argparse
from pathlib import Path
from typing import TypedDict,Annotated
from operator import add
import json
from langgraph.graph import StateGraph,START,END
from l18.runtime import servidor,Modelo


class Plano(TypedDict,total=False):
    objetivo:str
    passos:Annotated[list[str],add]
    proximo:str
    fontes:Annotated[list[str],add]
    desfecho:str


def montar(politica,modelo,disponivel):
    def decidir(s):
        passos=s.get("passos",[])
        if s.get("fontes"):
            return {"proximo":"fim","desfecho":"resolvida"}
        if len(passos)>=2:
            return {"proximo":"fim","desfecho":"orcamento"}
        if politica=="fixa":op="M"
        elif politica=="busca":op="M" if not passos else "C"
        else:
            op=modelo.gerar("planejador","M = manual, C = catálogo, X = abandonar. "
                            "Prefira o manual. Se falhar, tente o catálogo alternativo.",
                            s["objetivo"],passos,"MCX")
        if op=="X":
            return {"proximo":"fim","desfecho":"abandonada"}
        return {"proximo":op}
    def ferramenta(s):
        op=s["proximo"]
        if op=="M" and not disponivel:
            return {"passos":["M: indisponível"],"fontes":[]}
        return {"passos":[op+": chegou J47"],"fontes":["J47"]}
    g=StateGraph(Plano)
    g.add_node("decidir",decidir);g.add_node("consultar",ferramenta)
    g.add_edge(START,"decidir")
    g.add_conditional_edges("decidir",lambda s:END if s["proximo"]=="fim" else "consultar")
    g.add_edge("consultar","decidir")
    return g.compile()


def executar(modelo,exe,saida):
    saida.mkdir(parents=True,exist_ok=False);dados=[]
    with servidor(modelo,exe) as url:
        for disponivel in (True,False):
            for politica in ("fixa","busca","modelo"):
                m=Modelo(url,17,{"timeout_s":90,"chamadas":2,"saida_max":4,"tokens":1600,"temperatura":0})
                final=montar(politica,m,disponivel).invoke({"objetivo":"localizar o código da VPN"})
                dados.append({"politica":politica,"manual_disponivel":disponivel,"final":final,"chamadas":m.chamadas})
    (saida/"L08.json").write_text(json.dumps(dados,indent=2,ensure_ascii=False),encoding="utf8")


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("modelo",type=Path);p.add_argument("exe",type=Path)
    p.add_argument("saida",type=Path);a=p.parse_args();executar(a.modelo,a.exe,a.saida)
