"""Defeitos deliberados e oráculos independentes do caminho feliz."""
from copy import deepcopy
import hashlib
import itertools
import json
import operator
from typing import Annotated, Literal, TypedDict
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, END, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict, Field


# trecho:contrato
class Acao(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    recurso: str = Field(min_length=1)
    prioridade: Literal["alta", "baixa"]
    revisao: int = Field(ge=0)


def digest(acao):
    validada = Acao.model_validate(acao).model_dump()
    texto = json.dumps(validada, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(texto.encode()).hexdigest()


class Estado(TypedDict, total=False):
    acao: dict
    evidencias: list[dict]
    aprovado: str
    recibo: dict
    situacao: str
    passos: Annotated[list[str], operator.add]
# fim:contrato


def criar_grafo(defeito=None, trocar=False, efeitos=None, saver=None):
    permitidos = {None, "perder_evidencia", "aceitar_alteracao",
                  "finalizar_cedo", "metadado_inofensivo"}
    if defeito not in permitidos:
        raise ValueError("defeito_desconhecido")
    efeitos = [] if efeitos is None else efeitos
    saver = InMemorySaver() if saver is None else saver

    def coletar(s):
        Acao.model_validate(s["acao"])
        evidencia = {"fonte": "A-17:r3", "revisao": 3}
        return {"evidencias": [evidencia], "passos": ["coletar"]}

    # trecho:revisao
    def revisar(s):
        vinculo = digest(s["acao"])
        decisao = interrupt({"acao": s["acao"], "digest": vinculo})
        aceita = (isinstance(decisao, dict)
                  and decisao.get("aceitar") is True
                  and decisao.get("digest") == vinculo)
        if not aceita:
            return Command(update={"situacao": "recusada"}, goto=END)
        return Command(update={"aprovado": vinculo,
                               "passos": ["revisar"]}, goto="aplicar")
    # fim:revisao

    # trecho:efeito
    def aplicar(s):
        if defeito == "finalizar_cedo":
            return {"passos": ["aplicar_sem_efeito"]}
        acao = deepcopy(s["acao"])
        if trocar:
            acao["prioridade"] = "baixa"
        if (digest(acao) != s["aprovado"]
                and defeito != "aceitar_alteracao"):
            raise ValueError("acao_alterada")
        recibo = {"numero": len(efeitos) + 1, "acao": acao}
        efeitos.append(deepcopy(recibo))
        return {"recibo": recibo, "passos": ["aplicar"]}

    def finalizar(s):
        evidencias = ([] if defeito == "perder_evidencia"
                      else s["evidencias"])
        return {"situacao": "concluida", "evidencias": evidencias,
                "passos": ["finalizar"]}
    # fim:efeito
    g = StateGraph(Estado)
    for nome, no in (("coletar", coletar), ("revisar", revisar),
                     ("aplicar", aplicar), ("finalizar", finalizar)):
        g.add_node(nome, no)
    g.add_edge(START, "coletar")
    g.add_edge("coletar", "revisar")
    g.add_edge("aplicar", "finalizar")
    g.add_edge("finalizar", END)
    return g.compile(checkpointer=saver)


def entrada():
    return {"acao": {"recurso": "A-17", "prioridade": "alta", "revisao": 3}}


def rodar(defeito=None, trocar=False, aceitar=True):
    efeitos = []
    g = criar_grafo(defeito, trocar, efeitos)
    cfg = {"configurable": {"thread_id": "ensaio-17"}}
    pausa = g.invoke(entrada(), cfg)
    proposta = pausa["__interrupt__"][0].value
    try:
        final = g.invoke(Command(resume={"aceitar": aceitar,
                          "digest": proposta["digest"]}), cfg)
        erro = None
    except ValueError as exc:
        final, erro = {}, str(exc)
    return {"final": final, "efeitos": efeitos, "erro": erro,
            "proposta": proposta}


# trecho:oraculos
def verificar(resultado):
    s, efeitos = resultado["final"], resultado["efeitos"]
    passos = s.get("passos", [])
    ordem = ["coletar", "revisar", "aplicar", "finalizar"]
    presentes = all(p in passos for p in ordem)
    temporal = presentes and all(
        passos.index(a) < passos.index(b)
        for a, b in zip(ordem, ordem[1:]))
    return {
        "resposta_final": s.get("situacao") == "concluida",
        "evidencia": s.get("evidencias") == [
            {"fonte": "A-17:r3", "revisao": 3}],
        "efeito_revisado": bool(efeitos) and all(
            e["acao"] == entrada()["acao"] for e in efeitos),
        "recibo": len(efeitos) == 1 and s.get("recibo") == efeitos[0],
        "ordem": temporal,
    }
# fim:oraculos


# trecho:propriedade
def unir_por_id(a, b):
    indice = {}
    for item in a + b:
        chave = item["id"]
        if chave in indice and indice[chave] != item:
            raise ValueError("mesma_identidade_outro_conteudo")
        indice[chave] = deepcopy(item)
    return [indice[k] for k in sorted(indice)]


def permutacoes():
    partes = [[{"id": str(n), "valor": n}] for n in range(3)]
    esperado = [p[0] for p in partes]
    resultados = []
    for ordem in itertools.permutations(partes):
        atual = []
        for parte in ordem:
            atual = unir_por_id(atual, parte)
        resultados.append(atual == esperado)
    return resultados
# fim:propriedade


def executar():
    matriz = []
    for defeito in (None, "perder_evidencia", "aceitar_alteracao",
                    "finalizar_cedo", "metadado_inofensivo"):
        r = rodar(defeito, trocar=defeito == "aceitar_alteracao")
        matriz.append({"variante": defeito or "referencia",
                       "oraculos": verificar(r)})
    return {"matriz": matriz, "permutacoes": permutacoes()}


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
