"""Spans locais, relógio lógico, custo incompleto e cache de respostas."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import time
from typing import TypedDict
from uuid import uuid4
from langgraph.graph import START, END, StateGraph


class Relogio:
    def __init__(self): self.ms = 0
    def agora(self): return self.ms
    def avancar(self, ms):
        if type(ms) is not int or ms < 0:
            raise ValueError("duracao_invalida")
        self.ms += ms


# trecho:spans
class Coletor:
    def __init__(self, relogio, execucao="execucao-19"):
        self.relogio = relogio
        self.execucao = execucao
        self.spans, self.pilha = [], []

    @contextmanager
    def medir(self, etapa, tentativa=1):
        span = {"execucao": self.execucao, "id": len(self.spans)+1,
                "pai": self.pilha[-1] if self.pilha else None,
                "etapa": etapa, "tentativa": tentativa,
                "inicio_ms": self.relogio.agora(), "situacao": "ok"}
        self.spans.append(span)
        self.pilha.append(span["id"])
        try:
            yield span
        except Exception:
            span["situacao"] = "erro"
            raise
        finally:
            span["fim_ms"] = self.relogio.agora()
            span["duracao_ms"] = span["fim_ms"]-span["inicio_ms"]
            self.pilha.pop()
# fim:spans


class Estado(TypedDict, total=False):
    estimativa_entrada: int
    resposta: str


def ensaio(atraso=0, repetir=False, contexto=1):
    if type(contexto) is not int or contexto < 1:
        raise ValueError("contexto_invalido")
    relogio = Relogio()
    coletor = Coletor(relogio)
    usos = []
    def recuperar(s):
        with coletor.medir("recuperar"):
            relogio.avancar(10+atraso)
        return {"estimativa_entrada": 40*contexto}
    def modelo(s):
        for tentativa in range(1, 3 if repetir else 2):
            try:
                with coletor.medir("modelo", tentativa):
                    falha = repetir and tentativa == 1
                    relogio.avancar(20 if falha else 30)
                    usos.append({"tentativa": tentativa,
                        "estimativa_entrada": s["estimativa_entrada"],
                        "entrada": None if falha else s["estimativa_entrada"],
                        "saida": None if falha else 10,
                        "origem": "simulada"})
                    if falha:
                        raise TimeoutError("falha_preparada")
            except TimeoutError:
                continue
        return {"resposta": "Instale Aurora Connect."}
    def ferramenta(s):
        with coletor.medir("ferramenta"):
            relogio.avancar(5)
        return {}
    g = StateGraph(Estado)
    for nome,no in (("recuperar",recuperar),("modelo",modelo),
                    ("ferramenta",ferramenta)):
        g.add_node(nome,no)
    for a,b in ((START,"recuperar"),("recuperar","modelo"),
                ("modelo","ferramenta"),("ferramenta",END)):
        g.add_edge(a,b)
    with coletor.medir("requisicao"):
        with coletor.medir("fila"):
            relogio.avancar(20)
        resultado = g.compile().invoke({})
    return {"spans": coletor.spans, "usos": usos,
            "resultado": resultado, "relogio": "logico_ms"}


# trecho:custo
def custo(usos, entrada_por_milhao="2", saida_por_milhao="6"):
    pe, ps = Decimal(entrada_por_milhao), Decimal(saida_por_milhao)
    if not pe.is_finite() or not ps.is_finite() or min(pe, ps) < 0:
        raise ValueError("preco_invalido")
    parcial, desconhecidas = Decimal(0), 0
    for uso in usos:
        contagens = (uso["entrada"], uso["saida"])
        if any(n is not None and (type(n) is not int or n < 0)
               for n in contagens):
            raise ValueError("uso_invalido")
        for n, preco in zip(contagens, (pe, ps)):
            if n is not None:
                parcial += Decimal(n)*preco/Decimal(1_000_000)
        desconhecidas += any(n is None for n in contagens)
    return {"parcial_conhecido": str(parcial),
            "total": None if desconhecidas else str(parcial),
            "tentativas_incompletas": desconhecidas,
            "moeda": "unidade_monetaria_ficticia"}


def percentil(valores, p):
    if not valores or not 0 < p <= 1:
        raise ValueError("percentil_invalido")
    return sorted(valores)[math.ceil(p*len(valores))-1]
# fim:custo


# trecho:cache
@dataclass(frozen=True)
class ChaveCache:
    organizacao: str
    escopo_acesso: str
    revisao_permissao: int
    revisao_corpus: str
    revisao_prompt: str
    modelo: str
    pergunta: str

    def digest(self):
        return hashlib.sha256(json.dumps(
            asdict(self), sort_keys=True).encode()).hexdigest()


class Cache:
    def __init__(self): self.itens = {}

    def consultar(self, chave, agora, ttl, autorizar, gerar):
        if any(type(n) is not int or n < 0 for n in (agora, ttl)):
            raise ValueError("tempo_invalido")
        autorizar()  # Inclusive em hits; autoridade não vem do cache.
        k = chave.digest()
        item = self.itens.get(k)
        if item is not None and agora < item["vence"]:
            return deepcopy(item["resposta"]), True
        resposta = gerar()
        self.itens[k] = {"resposta": deepcopy(resposta), "vence": agora+ttl}
        return deepcopy(resposta), False
# fim:cache


# trecho:exportacao
def resumo_publicavel(ensaio):
    spans = ensaio["spans"]
    return {"versao": "L19-v1", "relogio": "logico_ms",
            "duracao_ms": spans[0]["duracao_ms"],
            "tentativas_modelo": sum(s["etapa"] == "modelo" for s in spans),
            "erros": sum(s["situacao"] == "erro" for s in spans)}


def exportar_langsmith(ensaio, cliente, projeto):
    # Recebe cliente; importar o módulo não cria uma instância.
    agora = datetime.now(timezone.utc)
    cliente.create_run(name="laboratorio-19", run_type="chain",
        id=uuid4(), project_name=projeto, inputs={},
        outputs=resumo_publicavel(ensaio),
        start_time=agora, end_time=agora,
        extra={"metadata": {"origem": "simulacao_local"}})
# fim:exportacao


def medir_chamada_real(funcao):
    inicio = time.perf_counter_ns()
    resultado = funcao()
    return {"resultado": resultado,
            "duracao_observada_ns": time.perf_counter_ns()-inicio}


def executar():
    cenarios = {"base": ensaio(), "atraso": ensaio(atraso=100),
                "reenvio": ensaio(repetir=True), "contexto": ensaio(contexto=20)}
    return {nome: {**r, "custo": custo(r["usos"])}
            for nome, r in cenarios.items()}


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
