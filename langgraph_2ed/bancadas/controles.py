"""Reexecuta os controles preservados da coleção com a numeração da segunda edição."""
import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import time

BOOK = Path(__file__).resolve().parents[1]
COL = BOOK.parent
sys.path.insert(0, str(COL))
# Os controles que abrem subprocessos precisam encontrar os módulos da coleção.
os.environ["PYTHONPATH"] = os.pathsep.join([str(COL), str(BOOK), os.environ.get("PYTHONPATH", "")])
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
MAPA = {1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:"planejamento",9:9,10:"funcional",
        12:11,13:13,14:8,15:23,16:14,17:15,19:"mcp_local",20:"a2a_local",
        21:17,22:18,23:"guardrails",24:20,25:21,26:19,27:22,28:12,29:23,
        30:24,31:"integracao",32:22}


def controle(origem):
    if origem == "funcional":
        from exemplos.apendices.composicao import comparar
        return {"aceitar":comparar(True), "recusar":comparar(False)}
    if isinstance(origem, str):
        from exemplos.avancados.laboratorios import executar
        return executar(origem)
    if origem <= 4:
        from exemplos.laboratorios import LABORATORIOS
        return {"casos":LABORATORIOS[origem]()}
    parte = (origem-1)//4+1
    mod = importlib.import_module(f"exemplos.parte{parte}.laboratorios")
    return getattr(mod, f"l{origem}")() if parte == 6 else mod.executar(origem)


def escrever(p, doc):
    p.write_text(json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")


def executar(saida, capitulos):
    saida.mkdir(parents=True,exist_ok=False)
    for n in capitulos:
        inicio = time.monotonic()
        r = controle(MAPA[n])
        if not all(c["confere"] for c in r.get("casos",[])):
            raise ValueError(f"controle L{n:02} divergiu")
        escrever(saida/f"L{n:02}.json",{"capitulo":n,"origem":MAPA[n],"segundos":round(time.monotonic()-inicio,3),
                                        "observacao":r})
        print(f"L{n:02} concluído",flush=True)


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("saida",type=Path)
    p.add_argument("capitulos",nargs="*",type=int)
    a=p.parse_args()
    executar(a.saida,a.capitulos or MAPA)
