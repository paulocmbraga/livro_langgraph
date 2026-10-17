"""Captura somente a nova Parte II, sem alterar a referência da Parte I."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from scripts.capturar import ambiente, hash_arquivo, gravar, ROOT


def fontes():
    caminhos = [ROOT/"requirements.lock.txt", ROOT/"exemplos/__init__.py",
                ROOT/"scripts/capturar.py"]
    for pasta in ("exemplos/parte2", "scripts/parte2", "testes/parte2"):
        caminhos.extend(ROOT.glob(pasta+"/*.py"))
    return {p.relative_to(ROOT).as_posix(): hash_arquivo(p) for p in sorted(caminhos)}


def executar(destino):
    deps, origem = ambiente(), fontes()
    destino.mkdir(parents=True, exist_ok=False)
    gravar(destino/"estado.json", {"completo": False})
    for relativo in origem:
        copia = destino/"fontes"/relativo
        copia.parent.mkdir(parents=True, exist_ok=True)
        copia.write_bytes((ROOT/relativo).read_bytes())
    resultados = []
    for numero in range(5, 9):
        processo = subprocess.run(
            [sys.executable, "-m", "exemplos.parte2.laboratorios",
             "--capitulo", str(numero)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf8",
            env=dict(os.environ, PYTHONUTF8="1", LANGSMITH_TRACING="false",
                     LANGCHAIN_TRACING_V2="false"), timeout=60)
        if processo.returncode:
            (destino/f"erro_{numero}.txt").write_text(processo.stderr, encoding="utf8")
            raise RuntimeError(f"Falha no capítulo {numero}")
        dados = json.loads(processo.stdout)
        if not all(c["confere"] for c in dados["casos"]):
            raise ValueError("caso_divergente")
        arquivo = destino/f"capitulo_{numero:02}.json"
        gravar(arquivo, dados)
        resultados.append({"capitulo": numero, "casos": len(dados["casos"]),
                           "arquivo": arquivo.name, "sha256": hash_arquivo(arquivo)})
    if origem != fontes() or deps != ambiente():
        raise ValueError("fontes_ou_ambiente_alterados")
    manifesto = {"parte": 2, "completo": True,
                 "instante_utc": datetime.now(timezone.utc).isoformat(),
                 "ambiente": deps, "fontes": origem, "resultados": resultados,
                 "inferencia_real": False}
    gravar(destino/"manifesto.json", manifesto)
    gravar(destino/"estado.json", {"completo": True})
    return manifesto


def conferir(destino):
    m = json.loads((destino/"manifesto.json").read_text(encoding="utf8"))
    if not m["completo"] or json.loads((destino/"estado.json").read_text()) != {"completo": True}:
        raise ValueError("captura_incompleta")
    if m["fontes"] != fontes() or m["ambiente"]["pacotes"] != ambiente()["pacotes"]:
        raise ValueError("fontes_ou_ambiente_divergentes")
    for relativo, digest in m["fontes"].items():
        if hash_arquivo(destino/"fontes"/relativo) != digest:
            raise ValueError("copia_divergente")
    if [r["capitulo"] for r in m["resultados"]] != [5, 6, 7, 8]:
        raise ValueError("inventario_incompleto")
    for registro in m["resultados"]:
        arquivo = destino/registro["arquivo"]
        dados = json.loads(arquivo.read_text(encoding="utf8"))
        if (hash_arquivo(arquivo) != registro["sha256"]
                or len(dados["casos"]) != registro["casos"]
                or not all(c["confere"] and c["observado"] == c["esperado"]
                           for c in dados["casos"])):
            raise ValueError("resultado_divergente")
    return m


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destino", type=Path)
    parser.add_argument("--conferir", action="store_true")
    args = parser.parse_args()
    m = conferir(args.destino) if args.conferir else executar(args.destino)
    print(json.dumps({"completo": True, "capitulos": len(m["resultados"]),
                      "casos": sum(r["casos"] for r in m["resultados"])}, ensure_ascii=False))
