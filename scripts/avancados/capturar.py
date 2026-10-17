"""Executa laboratórios adicionais e suíte integral; vincula evidência por hash."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "output/avancados_v04"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fontes():
    return sorted([p for pasta in ("exemplos", "scripts", "testes")
                   for p in (ROOT / pasta).rglob("*.py")]) + [ROOT / "requirements.lock.txt"]


def conferir():
    m = json.loads((DEST / "manifesto.json").read_text(encoding="utf8"))
    assert set(m["fontes"]) == {p.relative_to(ROOT).as_posix() for p in fontes()}
    for rel, h in {**m["fontes"], **m["artefatos"]}.items():
        assert sha(ROOT / rel) == h, rel
    assert m["testes"]["sucesso"] is True
    assert len(m["laboratorios"]) == 6
    return m


def main():
    DEST.mkdir(parents=True, exist_ok=False)
    env = dict(__import__("os").environ, PYTHONUTF8="1", LANGSMITH_TRACING="false",
               LANGCHAIN_TRACING_V2="false")
    comando = [sys.executable, "-m", "unittest", "discover", "-s", "testes", "-v"]
    p = subprocess.run(comando, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf8")
    log = DEST / "testes.txt"
    log.write_text(p.stdout + p.stderr, encoding="utf8", newline="\n")
    if p.returncode:
        raise RuntimeError("Falha na suíte: " + str(log))
    total = int(re.search(r"Ran (\d+) tests", p.stderr)[1])
    from exemplos.avancados.laboratorios import MODULOS, executar
    laboratorios = {}
    for nome in MODULOS:
        dado = executar(nome)
        arquivo = DEST / (nome + ".json")
        arquivo.write_text(json.dumps(dado, ensure_ascii=False, indent=2), encoding="utf8")
        laboratorios[nome] = arquivo.relative_to(ROOT).as_posix()
    m = {"data_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
         "modelo_real": False, "protocolos": {"mcp": "2025-11-25", "a2a": "1.0"},
         "testes": {"comando": comando, "quantidade": total, "sucesso": True},
         "laboratorios": laboratorios,
         "fontes": {p.relative_to(ROOT).as_posix(): sha(p) for p in fontes()},
         "artefatos": {p.relative_to(ROOT).as_posix(): sha(p)
                       for p in [log, *(ROOT/v for v in laboratorios.values())]}}
    (DEST / "manifesto.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf8")
    conferir()
    print(json.dumps({"testes": total, "laboratorios": len(laboratorios), "sucesso": True}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--conferir", action="store_true")
    if p.parse_args().conferir:
        print(json.dumps({"conferido": bool(conferir())}))
    else:
        main()
