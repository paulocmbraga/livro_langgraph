"""L15. Mesmos candidatos, dois geradores. Reavalia chamadas reais preservadas."""
import argparse
import json
from pathlib import Path
import re


def extrair(candidatos):
    doc=candidatos[0]
    if "fora do escopo" in doc or "só pode ler" in doc:
        return "NEGADO"
    codigos=re.findall(r"\b[A-Z][0-9]{2}\b",doc)
    return codigos[-1] if codigos else "ABSTER"


def executar(entrada,saida):
    saida.mkdir(parents=True,exist_ok=False)
    reserva=json.loads((entrada/"protocolo.json").read_text(encoding="utf8"))["reserva"]
    docs={ident:doc for ident,_,doc,_ in reserva}
    resultados=json.loads((entrada/"resultados.json").read_text(encoding="utf8"))["L15_L22"]
    chamadas=[json.loads(s) for s in (entrada/"chamadas.jsonl").read_text(encoding="utf8").splitlines()]
    respostas=[x["chamadas"][0] for x in chamadas if x["papel"]=="L15/L22"]
    assert len(respostas)==len(resultados)
    trilhas=[]
    for r,c in zip(resultados,respostas):
        if r["arquitetura"]!="com_recuperacao":
            continue
        doc=docs[r["id"]]
        assert doc in c["prompt"] and c["texto"]==r["resposta"]
        regra=extrair([doc])
        trilhas.append({"id":r["id"],"seed":r["seed"],"candidatos":[doc],"extrativo":regra,
                        "modelo":r["resposta"],"referencia":r["referencia"],
                        "acerto_extrativo":regra==r["referencia"],"acerto_modelo":r["regra"]})
    (saida/"L15.json").write_text(json.dumps(trilhas,indent=2,ensure_ascii=False),encoding="utf8")


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("entrada",type=Path);p.add_argument("saida",type=Path)
    a=p.parse_args();executar(a.entrada,a.saida)
