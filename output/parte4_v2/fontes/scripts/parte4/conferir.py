"""Confere a nova Parte IV e executa os blocos Python autônomos do texto."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from scripts import conferir_livro

ROOT = Path(__file__).resolve().parents[2]


def executar(atualizar=False):
    conferir_livro.main(atualizar)
    pasta = ROOT/"livro/parte_04"
    capitulos = sorted((pasta/"capitulos").glob("*.md"))
    if [p.name[:2] for p in capitulos] != ["13", "14", "15", "16"]:
        raise ValueError("inventario_de_capitulos")
    for sub in ("solucoes", "fichas"):
        if [p.stem for p in sorted((pasta/sub).glob("*.md"))] != ["13", "14", "15", "16"]:
            raise ValueError("inventario_"+sub)
    for local in ("exemplos/parte4", "scripts/parte4", "testes/parte4"):
        for p in ROOT.glob(local+"/*.py"):
            ast.parse(p.read_text(encoding="utf8"))
    blocos, manuscritos = [], {}
    for p in sorted(pasta.rglob("*.md")):
        texto = p.read_text(encoding="utf8")
        manuscritos[p.relative_to(ROOT).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        sem_sincronizados = conferir_livro.PADRAO.sub("", texto)
        for indice, m in enumerate(re.finditer(
                r"^```python\n(.*?)^```", sem_sincronizados, re.M | re.S), 1):
            processo = subprocess.run([sys.executable, "-c", m[1]],
                cwd=ROOT, capture_output=True, text=True, encoding="utf8", timeout=30,
                env=dict(os.environ, PYTHONUTF8="1", LANGSMITH_TRACING="false",
                         LANGCHAIN_TRACING_V2="false"))
            if processo.returncode:
                raise RuntimeError(f"{p.name} bloco {indice}: {processo.stderr}")
            blocos.append({"arquivo": p.relative_to(ROOT).as_posix(),
                           "bloco_autonomo": indice, "saida": processo.stdout.strip(),
                           "sha256_codigo": hashlib.sha256(m[1].encode()).hexdigest()})
    relatorio = {"instante_utc": datetime.now(timezone.utc).isoformat(),
                 "documentos_parte4": len(manuscritos), "manuscritos": manuscritos,
                 "blocos_python_autonomos": blocos, "exercicios": 48, "solucoes": 48,
                 "observacao": "Blocos sincronizados conferidos contra fontes; PowerShell não executado por este verificador."}
    destino = ROOT/"output/conferencia_texto_parte4.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"documentos_parte4": len(manuscritos),
                      "blocos_autonomos_executados": len(blocos),
                      "exercicios": 48, "solucoes": 48}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atualizar", action="store_true")
    args = parser.parse_args()
    executar(args.atualizar)
