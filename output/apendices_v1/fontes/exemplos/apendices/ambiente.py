"""Identifica o interpretador e o conjunto efetivamente instalado."""
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys


# trecho:ambiente
def diagnostico():
    raiz = Path(__file__).resolve().parents[2]
    return {
        "python": platform.python_version(),
        "executavel": sys.executable,
        "sistema": platform.system(),
        "raiz": str(raiz),
        "na_raiz": Path.cwd().resolve() == raiz,
        "pacotes": {
            nome: version(nome) for nome in (
                "langgraph", "langchain-core",
                "langgraph-checkpoint-sqlite", "pydantic",
            )
        },
    }
# fim:ambiente


if __name__ == "__main__":
    print(json.dumps(diagnostico(), ensure_ascii=False, indent=2))
