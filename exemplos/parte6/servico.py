"""Comandos locais para preparar, servir, recuperar e copiar a bancada."""
import argparse
import json
import os
from pathlib import Path
import time
from .cap21 import Aplicacao, servir
from .cap22 import backup, restaurar
from .fila import exclusividade


def preparar(pasta):
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=False)
    app = Aplicacao(pasta)
    tokens = app.dominio.preparar()
    caminho = pasta/"credenciais-locais.json"
    caminho.write_text(json.dumps(tokens, indent=2), encoding="utf8")
    return {"pasta": str(pasta), "credenciais_locais": str(caminho)}


def carregar(pasta, credenciais=None, **opcoes):
    caminho = Path(credenciais) if credenciais else Path(pasta)/"credenciais-locais.json"
    tokens = json.loads(caminho.read_text(encoding="utf8"))
    return Aplicacao(pasta, executor_token=tokens["bot"], **opcoes)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("comando", choices=["preparar", "servir", "passo", "backup", "restaurar", "corpus"])
    p.add_argument("pasta", type=Path)
    p.add_argument("--destino", type=Path)
    p.add_argument("--porta", type=int, default=8766)
    p.add_argument("--falha", choices=["", "encerrar_processo", "perder_resposta"], default="")
    p.add_argument("--versao", default="corpus-2")
    p.add_argument("--credenciais", type=Path)
    a = p.parse_args()
    if a.comando == "preparar":
        print(json.dumps(preparar(a.pasta), ensure_ascii=False))
    elif a.comando in ("backup", "restaurar"):
        if not a.destino:
            p.error("--destino obrigatório")
        funcao = backup if a.comando == "backup" else restaurar
        print(json.dumps(funcao(a.pasta, a.destino), ensure_ascii=False))
    else:
        app = carregar(a.pasta, a.credenciais, falha_destino=a.falha)
        if a.comando == "servir":
            with servir(app, a.porta) as url:
                print(json.dumps({"url": url, "pid": os.getpid()}), flush=True)
                try:
                    while True: time.sleep(.2)
                except KeyboardInterrupt:
                    pass
        elif a.comando == "passo":
            with exclusividade(a.pasta):
                app.fila.recuperar()
                print(json.dumps({"processou": app.processar_um()}))
        else:
            with exclusividade(a.pasta):
                app.conhecimento.publicar(a.versao)
                print(json.dumps({"corpus": a.versao}))


if __name__ == "__main__":
    main()
