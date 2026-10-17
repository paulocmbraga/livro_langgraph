"""Execute: python -m exemplos.avancados.laboratorios todos."""
import argparse
import importlib
import json

MODULOS = ("guardrails", "planejamento", "coordenacao", "mcp_local", "a2a_local", "integracao")


def executar(nome):
    return importlib.import_module("exemplos.avancados." + nome).demonstrar()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("laboratorio", choices=(*MODULOS, "todos"))
    a = p.parse_args()
    nomes = MODULOS if a.laboratorio == "todos" else [a.laboratorio]
    print(json.dumps({n: executar(n) for n in nomes}, ensure_ascii=False, indent=2))
