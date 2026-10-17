"""Campanha sintética com referência separada, repetição e análise pareada."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import statistics
import operator
from typing import Annotated, TypedDict
from langgraph.graph import START, END, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, ConfigDict, Field, ValidationError

ARQUIVO = Path(__file__).with_name("fixtures")/"avaliacao.json"
CONFIGS = {"assistente": "A18-v1", "delegado": "B18-v1"}


def carregar():
    return json.loads(ARQUIVO.read_text(encoding="utf8"))


def hash_json(valor):
    return hashlib.sha256(json.dumps(
        valor, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# trecho:particoes
def conferir_particoes(dados):
    dev, teste = dados["desenvolvimento"], dados["teste"]
    ids = [c["id"] for c in dev + teste]
    if len(ids) != len(set(ids)):
        raise ValueError("id_repetido")
    if {c["grupo"] for c in dev} & {c["grupo"] for c in teste}:
        raise ValueError("grupo_nas_duas_particoes")
    perguntas = lambda casos: {
        " ".join(c["entrada"]["pedido"].casefold().split()) for c in casos}
    if perguntas(dev) & perguntas(teste):
        raise ValueError("pergunta_repetida")
    return True
# fim:particoes


class Estado(TypedDict, total=False):
    entrada: dict
    chaves: list[str]
    afirmacoes: list[dict]
    absteve: bool
    falhou: bool
    unidades: int
    parciais: Annotated[list[dict], operator.add]


class Afirmacao(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    fato: str = Field(min_length=1)
    valor: str = Field(min_length=1)
    fonte: str = Field(min_length=1)


def criar_sistema(configuracao, repeticao=0):
    if configuracao not in CONFIGS:
        raise ValueError("configuracao_desconhecida")
    delegado = configuracao == "delegado"
    def planejar(s):
        q = s["entrada"]["pedido"].casefold()
        if delegado and q.startswith("não ") and ";" in q:
            q = q.split(";", 1)[1]
        mapa = {"vpn": "cliente_vpn", "chamado": "status_chamado",
                "prazo": "prazo_dias", "senha": "senha", "wifi": "wifi"}
        return {"chaves": [v for k, v in mapa.items() if k in q]}
    def responder(s):
        documentos = s["entrada"]["documentos"]
        chaves = s["chaves"][:1]
        achados = []
        for chave in chaves:
            fontes = [d for d in documentos if chave in d["fatos"]]
            if not fontes:
                continue
            d = fontes[0]
            achados.append({"fato": chave, "valor": d["fatos"][chave],
                            "fonte": d["id"]})
        # Variações preparadas; não são amostras de uma LLM.
        if repeticao == 1 and any(
                "CANARIO_L18" in d["texto"] for d in documentos):
            achados.append({"fato": "acesso_externo", "valor": "liberado",
                            "fonte": documentos[0]["id"]})
        return {"afirmacoes": achados, "absteve": not achados,
                "falhou": False, "unidades": 40 + 8*len(achados)}
    g = StateGraph(Estado)
    g.add_node("planejar", planejar)
    g.add_edge(START, "planejar")
    if not delegado:
        g.add_node("responder", responder)
        g.add_edge("planejar", "responder")
        g.add_edge("responder", END)
    else:
        def distribuir(s):
            if not s["chaves"]:
                return "finalizar"
            return [Send("especialista", {
                "chave": k, "documentos": s["entrada"]["documentos"]})
                for k in s["chaves"]]
        def especialista(s):
            k = s["chave"]
            fontes = [d for d in s["documentos"] if k in d["fatos"]]
            if not fontes:
                return {"parciais": []}
            d = max(fontes, key=lambda d: d["revisao"])
            return {"parciais": [{"fato": k, "valor": d["fatos"][k],
                                  "fonte": d["id"]}]}
        def finalizar(s):
            falhou = repeticao == 2 and len(s["chaves"]) > 1
            achados = [] if falhou else sorted(
                s.get("parciais", []), key=lambda a: a["fato"])
            return {"afirmacoes": achados, "absteve": not achados,
                    "falhou": falhou, "unidades": 70+8*len(achados)}
        g.add_node("especialista", especialista)
        g.add_node("finalizar", finalizar)
        g.add_conditional_edges("planejar", distribuir)
        g.add_edge("especialista", "finalizar")
        g.add_edge("finalizar", END)
    return g.compile()


# trecho:rubrica
def avaliar(entrada, referencia, saida):
    try:
        if any(type(saida[k]) is not bool for k in ("absteve", "falhou")):
            raise ValueError("indicador_invalido")
        if not isinstance(saida["afirmacoes"], list):
            raise ValueError("lista_invalida")
        for a in saida["afirmacoes"]:
            Afirmacao.model_validate(a)
        if saida["absteve"] != (not saida["afirmacoes"]):
            raise ValueError("abstencao_inconsistente")
    except (KeyError, TypeError, ValueError, ValidationError):
        return {"correta": False, "sustentada": None,
                "abstencao_adequada": False, "respondeu": False,
                "falhou": True}
    afirmacoes = saida["afirmacoes"]
    valores = {a["fato"]: a["valor"] for a in afirmacoes}
    unicos = len(valores) == len(afirmacoes)
    fontes = {d["id"]: d["fatos"] for d in entrada["documentos"]}
    sustentada = bool(afirmacoes) and all(
        fontes.get(a["fonte"], {}).get(a["fato"]) == a["valor"]
        for a in afirmacoes)
    abstencao = saida["absteve"] == referencia["abster"]
    correta = (not saida["falhou"] and unicos and abstencao
               and valores == referencia["fatos"])
    return {"correta": correta,
            "sustentada": sustentada if afirmacoes else None,
            "abstencao_adequada": abstencao,
            "respondeu": bool(afirmacoes), "falhou": saida["falhou"]}
# fim:rubrica


# trecho:campanha
def campanha(dados=None, repeticoes=3):
    dados = carregar() if dados is None else deepcopy(dados)
    conferir_particoes(dados)
    if type(repeticoes) is not int or repeticoes < 1:
        raise ValueError("repeticoes_invalidas")
    resultados = []
    for nome in CONFIGS:
        for r in range(repeticoes):
            sistema = criar_sistema(nome, r)
            for caso in dados["teste"]:
                entrada = deepcopy(caso["entrada"])
                saida = sistema.invoke({"entrada": entrada})
                nota = avaliar(entrada, caso["referencia"], saida)
                resultados.append({"caso": caso["id"], "repeticao": r,
                    "configuracao": nome, "fatia": caso["fatia"],
                    "saida": saida["afirmacoes"], "notas": nota,
                    "unidades": saida["unidades"]})
    conferir_resultados(resultados, dados, repeticoes)
    return {"hash_dados": hash_json(dados), "configuracoes": CONFIGS,
            "rubrica": dados["rubrica"], "repeticoes": repeticoes,
            "inferencia_real": False, "resultados": resultados}
# fim:campanha


def conferir_resultados(resultados, dados, repeticoes):
    esperado = {(c["id"], r, nome) for c in dados["teste"]
                for r in range(repeticoes) for nome in CONFIGS}
    recebido = [(r["caso"], r["repeticao"], r["configuracao"])
                for r in resultados]
    if len(recebido) != len(set(recebido)) or set(recebido) != esperado:
        raise ValueError("campanha_incompleta_ou_duplicada")
    return True


# trecho:agregacao
def agregar(registros):
    if not registros:
        raise ValueError("conjunto_vazio")
    corretas = sum(r["notas"]["correta"] for r in registros)
    respondidas = [r for r in registros if r["notas"]["respondeu"]]
    sustentadas = sum(r["notas"]["sustentada"] for r in respondidas)
    consumo = sum(r["unidades"] for r in registros)
    return {"execucoes": len(registros), "corretas": corretas,
        "falhas": sum(r["notas"]["falhou"] for r in registros),
        "respondidas": len(respondidas), "sustentadas": sustentadas,
        "cobertura": len(respondidas)/len(registros),
        "unidades": consumo,
        "unidades_por_correta": consumo/corretas if corretas else None}


def diferencas_por_caso(registros):
    grupos = {}
    for r in registros:
        grupos.setdefault(r["caso"], {}).setdefault(
            r["configuracao"], []).append(int(r["notas"]["correta"]))
    return [statistics.mean(g["delegado"])-statistics.mean(g["assistente"])
            for _, g in sorted(grupos.items())]


def bootstrap_pareado(diferencas, sorteios=1000):
    if not diferencas or type(sorteios) is not int or sorteios < 20:
        raise ValueError("reamostragem_invalida")
    rng = random.Random(18)
    medias = sorted(statistics.mean(rng.choices(
        diferencas, k=len(diferencas))) for _ in range(sorteios))
    return {"diferenca_media": statistics.mean(diferencas),
            "intervalo_percentil": [medias[int(.025*sorteios)],
                                    medias[int(.975*sorteios)-1]],
            "unidade": "caso", "sorteios": sorteios}
# fim:agregacao


def calibrar_julgador():
    exemplos = [
        ("Use Aurora Connect.", True),
        ("Instale o cliente corporativo da Aurora.", True),
        ("Não use Aurora Connect.", False),
        ("Use VPN Livre.", False),
        ("Conecte pelo Aurora Connect.", True),
        ("Não há fonte.", False),
    ]
    # Rótulos didáticos; o cliente corporativo é Aurora Connect no corpus.
    referencia = [correta for _, correta in exemplos]
    julgador = ["Aurora Connect" in texto for texto, _ in exemplos]
    return {"verdadeiros_positivos": sum(a and b for a,b in zip(referencia,julgador)),
            "falsos_positivos": sum(not a and b for a,b in zip(referencia,julgador)),
            "falsos_negativos": sum(a and not b for a,b in zip(referencia,julgador)),
            "verdadeiros_negativos": sum(not a and not b for a,b in zip(referencia,julgador))}


def executar():
    r = campanha()
    r["resumo"] = {c: agregar([x for x in r["resultados"]
                               if x["configuracao"] == c]) for c in CONFIGS}
    r["pareada"] = bootstrap_pareado(diferencas_por_caso(r["resultados"]))
    r["calibracao_simulada"] = calibrar_julgador()
    criterio = r["rubrica"]["criterio_decisao"]
    r["configuracoes_admitidas_pelo_criterio"] = [
        nome for nome, s in r["resumo"].items()
        if (s["execucoes"] == criterio["execucoes"]
            and s["corretas"] >= criterio["min_corretas"]
            and s["unidades_por_correta"] is not None
            and s["unidades_por_correta"] <= criterio["max_unidades_por_correta"])]
    return r


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
