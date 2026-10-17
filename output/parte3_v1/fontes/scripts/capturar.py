"""Executa os quatro laboratórios em processos novos e preserva suas fontes."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def hash_arquivo(caminho):
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def ambiente():
    lock = dict(linha.split("==",1) for linha in (ROOT/"requirements.lock.txt").read_text().splitlines() if "==" in linha)
    instalados = {}
    for nome in lock:
        try:
            instalados[nome] = importlib.metadata.version(nome)
        except importlib.metadata.PackageNotFoundError:
            instalados[nome] = "ausente"
    if instalados != lock:
        raise ValueError("Ambiente atual diverge do lock: " + ", ".join(n for n in lock if lock[n] != instalados[n]))
    if sys.version_info[:2] != (3,12):
        raise ValueError("Esta edição requer Python 3.12")
    return {"python":platform.python_version(), "sistema":platform.platform(), "pacotes":instalados}


def fontes():
    arquivos = [*ROOT.glob("exemplos/*.py"), *ROOT.glob("scripts/*.py"), *ROOT.glob("testes/*.py"),
                ROOT/"requirements.txt", ROOT/"requirements.lock.txt"]
    return {p.relative_to(ROOT).as_posix(): hash_arquivo(p) for p in sorted(arquivos)}


def gravar(caminho, dados):
    caminho.write_text(json.dumps(dados,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")


def executar(destino):
    atual = ambiente()
    origem = fontes()
    destino.mkdir(parents=True,exist_ok=False)
    gravar(destino/"estado.json",{"completo":False})
    for relativo in origem:
        copia=destino/"fontes"/relativo
        copia.parent.mkdir(parents=True,exist_ok=True)
        copia.write_bytes((ROOT/relativo).read_bytes())
    resultados = []
    for capitulo in range(1,5):
        ambiente_processo = dict(os.environ,PYTHONUTF8="1",LANGSMITH_TRACING="false",LANGCHAIN_TRACING_V2="false")
        processo=subprocess.run([sys.executable,"-m","exemplos.laboratorios","--capitulo",str(capitulo)],
            cwd=ROOT,env=ambiente_processo,capture_output=True,text=True,encoding="utf8",timeout=60)
        if processo.returncode:
            (destino/f"erro_{capitulo}.txt").write_text(processo.stderr,encoding="utf8")
            raise RuntimeError(f"Laboratório {capitulo} falhou")
        dados=json.loads(processo.stdout)
        gravar(destino/f"capitulo_{capitulo:02}.json",dados)
        resultados.append({"capitulo":capitulo,"arquivo":f"capitulo_{capitulo:02}.json",
                           "sha256":hash_arquivo(destino/f"capitulo_{capitulo:02}.json"),"casos":len(dados["casos"])})
    if fontes()!=origem or ambiente()!=atual:
        raise ValueError("Fontes ou ambiente mudaram durante a captura")
    manifesto={"edicao":"reescrita-1", "completo":True,"instante_utc":datetime.now(timezone.utc).isoformat(),
               "ambiente":atual,"fontes":origem,"resultados":resultados}
    gravar(destino/"manifesto.json",manifesto)
    gravar(destino/"estado.json",{"completo":True})
    return manifesto


def conferir(destino):
    atual=ambiente()
    manifesto=json.loads((destino/"manifesto.json").read_text(encoding="utf8"))
    if not manifesto.get("completo") or json.loads((destino/"estado.json").read_text()) != {"completo":True}:
        raise ValueError("Captura incompleta")
    if manifesto["fontes"] != fontes() or manifesto["ambiente"]["pacotes"] != atual["pacotes"]:
        raise ValueError("Fontes ou dependências divergem da referência")
    for relativo, digest in manifesto["fontes"].items():
        if hash_arquivo(destino/"fontes"/relativo)!=digest:
            raise ValueError("Fonte preservada alterada: "+relativo)
    if [r["capitulo"] for r in manifesto["resultados"]] != [1,2,3,4]:
        raise ValueError("Inventário de capítulos incompleto")
    for registro in manifesto["resultados"]:
        arquivo=destino/registro["arquivo"]
        if hash_arquivo(arquivo)!=registro["sha256"]:
            raise ValueError("Resultado alterado")
        dados=json.loads(arquivo.read_text(encoding="utf8"))
        if len(dados["casos"])!=registro["casos"] or not all(c["confere"] is True and c["observado"]==c["esperado"] for c in dados["casos"]):
            raise ValueError("Caso divergente")
    return manifesto


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destino",type=Path)
    parser.add_argument("--conferir",action="store_true")
    args=parser.parse_args()
    manifesto=conferir(args.destino) if args.conferir else executar(args.destino)
    print(json.dumps({"completo":True,"capitulos":len(manifesto["resultados"]),
                      "casos":sum(r["casos"] for r in manifesto["resultados"]),"destino":str(args.destino)},ensure_ascii=False))
