"""Contratos locais e medidas com população e unidade explícitas."""
import hashlib
import json
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


# trecho:contrato
class Proposta(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    versao: Literal[1] = 1
    operacao: str = Field(min_length=1, max_length=80)
    organizacao: str = Field(min_length=1, max_length=80)
    recurso: str = Field(pattern=r"^A-[0-9]{2}$")
    revisao: int = Field(ge=0)
    prioridade: Literal["alta", "baixa"]


def digest(proposta):
    dados = json.dumps(proposta.model_dump(), sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False).encode("utf8")
    return hashlib.sha256(dados).hexdigest()


def conferir_aprovacao(proposta, aprovado_digest, expira_em, agora):
    if not all(math.isfinite(t) for t in (expira_em, agora)):
        raise ValueError("instante_invalido")
    if agora >= expira_em:
        raise ValueError("aprovacao_expirada")
    if digest(proposta) != aprovado_digest:
        raise ValueError("conteudo_divergente")
    return True
# fim:contrato


class Amostra(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    pedido: str = Field(min_length=1)
    status: Literal["concluida", "falhou", "desconhecida", "recusada"]
    latencia_ms: float = Field(ge=0, allow_inf_nan=False)
    custo_usd: float = Field(ge=0, allow_inf_nan=False)


# trecho:medidas
def resumir(amostras, janela_s):
    if not math.isfinite(janela_s) or janela_s <= 0:
        raise ValueError("janela_invalida")
    if len({a.pedido for a in amostras}) != len(amostras):
        raise ValueError("pedido_duplicado")
    concluidas = [a for a in amostras if a.status == "concluida"]
    latencias = sorted(a.latencia_ms for a in concluidas)
    n, c = len(amostras), len(concluidas)
    total = sum(a.custo_usd for a in amostras)
    return {
        "pedidos": n, "concluidas": c,
        "falhas": sum(a.status == "falhou" for a in amostras),
        "desconhecidas": sum(a.status == "desconhecida" for a in amostras),
        "recusadas": sum(a.status == "recusada" for a in amostras),
        "taxa_conclusao": c / n if n else None,
        "conclusoes_por_s": c / janela_s,
        "p95_concluidas_ms": latencias[math.ceil(.95*c)-1] if c else None,
        "custo_total_usd": total,
        "custo_por_conclusao_usd": total / c if c else None,
    }
# fim:medidas


def demonstrar():
    valores = [("concluida", 100., .02), ("concluida", 300., .03),
               ("falhou", 50., .01), ("desconhecida", 500., .04),
               ("recusada", 5., 0.)]
    return resumir([Amostra(pedido=str(i), status=s, latencia_ms=t, custo_usd=c)
                    for i, (s, t, c) in enumerate(valores)], 2.)


if __name__ == "__main__":
    print(json.dumps(demonstrar(), indent=2))
