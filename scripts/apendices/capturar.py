"""Preserva demonstrações, vinte testes e fontes dos apêndices."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from scripts.capturar import ROOT, ambiente, hash_arquivo, gravar


def fontes():
    arquivos = [ROOT/"requirements.lock.txt", ROOT/"exemplos/__init__.py",
                ROOT/"scripts/capturar.py"]
    for pasta in ("exemplos/apendices", "scripts/apendices", "testes/apendices"):
        arquivos.extend(ROOT.glob(pasta+"/*.py"))
    return {p.relative_to(ROOT).as_posix(): hash_arquivo(p) for p in sorted(arquivos)}


def executar(destino):
    origem, deps = fontes(), ambiente()
    destino.mkdir(parents=True, exist_ok=False)
    gravar(destino/"estado.json", {"completo": False})
    for relativo in origem:
        copia = destino/"fontes"/relativo
        copia.parent.mkdir(parents=True, exist_ok=True)
        copia.write_bytes((ROOT/relativo).read_bytes())
    registros = []
    env = dict(os.environ, PYTHONUTF8="1", LANGSMITH_TRACING="false",
               LANGCHAIN_TRACING_V2="false")
    for nome in ("ambiente", "composicao", "contratos", "diagnostico"):
        p = subprocess.run([sys.executable, "-m", "exemplos.apendices."+nome],
                           cwd=ROOT, env=env, capture_output=True, text=True,
                           encoding="utf8", timeout=60)
        if p.returncode:
            (destino/"erro.txt").write_text(p.stderr, encoding="utf8")
            raise RuntimeError(nome)
        dados = json.loads(p.stdout)
        gravar(destino/(nome+".json"), dados)
        registros.append(nome+".json")
    p = subprocess.run([sys.executable, "-m", "unittest",
                       "testes.apendices.test_apendices", "-v"], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf8", timeout=90)
    (destino/"testes.txt").write_text(p.stdout+p.stderr, encoding="utf8")
    if p.returncode or "Ran 20 tests" not in p.stderr or "\nOK" not in p.stderr:
        raise RuntimeError("testes_incompletos")
    registros.append("testes.txt")
    if origem != fontes() or deps != ambiente():
        raise ValueError("fontes_ou_ambiente_alterados")
    m = {"completo": True, "instante_utc": datetime.now(timezone.utc).isoformat(),
         "fontes": origem, "ambiente": deps, "testes": 20,
         "demonstracoes": 4, "inferencia_real": False,
         "resultados": {n: hash_arquivo(destino/n) for n in registros}}
    gravar(destino/"manifesto.json", m)
    gravar(destino/"estado.json", {"completo": True})
    return m


def conferir(destino):
    m = json.loads((destino/"manifesto.json").read_text(encoding="utf8"))
    if not m["completo"] or json.loads((destino/"estado.json").read_text()) != {"completo": True}:
        raise ValueError("captura_incompleta")
    if m["fontes"] != fontes() or m["ambiente"]["pacotes"] != ambiente()["pacotes"]:
        raise ValueError("fontes_ou_ambiente_divergentes")
    if set(m["resultados"]) != {"ambiente.json", "composicao.json", "contratos.json", "diagnostico.json", "testes.txt"}:
        raise ValueError("inventario_incompleto")
    for relativo, h in m["fontes"].items():
        if hash_arquivo(destino/"fontes"/relativo) != h:
            raise ValueError("copia_divergente")
    for nome, h in m["resultados"].items():
        if hash_arquivo(destino/nome) != h:
            raise ValueError("resultado_divergente")
    return m


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("destino", type=Path)
    p.add_argument("--conferir", action="store_true")
    a = p.parse_args()
    m = conferir(a.destino) if a.conferir else executar(a.destino)
    print(json.dumps({k: m[k] for k in ("completo", "testes", "demonstracoes")}))
