"""A mesma revisão em Graph API e Functional API; reinício por subprocesso."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import TypedDict
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.func import entrypoint, task
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt


class Estado(TypedDict, total=False):
    texto: str
    proposta: str
    aprovado: bool


def registrar(pasta, evento):
    # Sonda local de reentrada, deliberadamente fora do checkpoint.
    with (pasta / "sonda.jsonl").open("a", encoding="utf8") as arquivo:
        arquivo.write(json.dumps(evento) + "\n")


def validar(valor):
    if type(valor) is not bool:
        raise ValueError("decisao_deve_ser_booleana")
    return valor


# trecho:graph
def construir_graph(saver, pasta):
    def preparar(estado):
        registrar(pasta, "preparo")
        return {"proposta": estado["texto"].strip().upper()}

    def revisar(estado):
        registrar(pasta, "corpo_revisao")
        resposta = interrupt({"proposta": estado["proposta"]})
        return {"aprovado": validar(resposta)}

    grafo = StateGraph(Estado)
    grafo.add_node("preparar", preparar)
    grafo.add_node("revisar", revisar)
    grafo.add_edge(START, "preparar")
    grafo.add_edge("preparar", "revisar")
    grafo.add_edge("revisar", END)
    return grafo.compile(checkpointer=saver)
# fim:graph


# trecho:functional
def construir_functional(saver, pasta):
    @task
    def preparar(texto):
        registrar(pasta, "preparo")
        return texto.strip().upper()

    @entrypoint(checkpointer=saver)
    def fluxo(entrada):
        registrar(pasta, "corpo_entrypoint")
        proposta = preparar(entrada["texto"]).result()
        resposta = interrupt({"proposta": proposta})
        return {"proposta": proposta,
                "aprovado": validar(resposta)}

    return fluxo
# fim:functional


# trecho:passo
def passo(pasta, estilo, fase, aceitar=True, thread="revisao-v1"):
    pasta.mkdir(parents=True, exist_ok=True)
    construtor = {"graph": construir_graph,
                  "functional": construir_functional}[estilo]
    config = {"configurable": {"thread_id": thread}}
    with SqliteSaver.from_conn_string(str(pasta / "estado.db")) as saver:
        fluxo = construtor(saver, pasta)
        entrada = {"texto": "  aurora  "} if fase == "iniciar" else Command(resume=aceitar)
        resultado = fluxo.invoke(entrada, config, durability="sync")
        pendente = fluxo.get_state(config).interrupts
        if pendente:
            return {"status": "revisao", "proposta": pendente[0].value["proposta"]}
        return {"status": "concluida", "proposta": resultado["proposta"],
                "aprovado": resultado["aprovado"]}
# fim:passo


def processo(pasta, estilo, fase, aceitar=True):
    comando = [sys.executable, "-m", "exemplos.apendices.composicao",
               "--pasta", str(pasta), "--estilo", estilo, "--fase", fase]
    if not aceitar:
        comando.append("--rejeitar")
    p = subprocess.run(comando, check=True, capture_output=True,
                       text=True, encoding="utf8", timeout=30,
                       cwd=Path(__file__).resolve().parents[2])
    return json.loads(p.stdout)


def comparar(aceitar=True):
    saidas = {}
    with TemporaryDirectory() as tmp:
        for estilo in ("graph", "functional"):
            pasta = Path(tmp) / estilo
            inicio = processo(pasta, estilo, "iniciar")
            fim = processo(pasta, estilo, "retomar", aceitar)
            eventos = [json.loads(linha) for linha in
                       (pasta / "sonda.jsonl").read_text().splitlines()]
            saidas[estilo] = {"inicio": inicio, "fim": fim,
                              "preparos": eventos.count("preparo"),
                              "reentradas_corpo": len(eventos) - eventos.count("preparo")}
    return saidas


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pasta", type=Path)
    p.add_argument("--estilo", choices=("graph", "functional"))
    p.add_argument("--fase", choices=("iniciar", "retomar"))
    p.add_argument("--rejeitar", action="store_true")
    a = p.parse_args()
    if a.pasta and (not a.estilo or not a.fase):
        p.error("--pasta requer --estilo e --fase")
    resultado = (passo(a.pasta, a.estilo, a.fase, not a.rejeitar)
                 if a.pasta else comparar(not a.rejeitar))
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
