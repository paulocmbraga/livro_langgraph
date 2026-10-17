"""Funções discutidas no caderno de soluções da Parte III."""
from copy import deepcopy
from .destino import digest


# trecho:identidade
def identidade_operacao(organizacao, recurso, intencao):
    if not all(isinstance(v, str) and v.strip()
               for v in (organizacao, recurso, intencao)):
        raise ValueError("identidade_incompleta")
    return digest({"organizacao": organizacao,
                   "recurso": recurso, "intencao": intencao})
# fim:identidade


# trecho:unknown
def decidir_unknown(situacao, idempotente, ausencia_autoritativa,
                    tentativas, limite):
    if any(type(n) is not int or n < 0 for n in (tentativas, limite)):
        raise ValueError("orcamento_invalido")
    if situacao == "confirmed":
        return "concluir"
    if situacao not in {"ausente", "unknown"}:
        raise ValueError("situacao_invalida")
    if tentativas >= limite:
        return "encaminhar"
    if situacao == "ausente" and ausencia_autoritativa and idempotente:
        return "reenviar_mesma_identidade"
    return "consultar_depois"
# fim:unknown


# trecho:backoff
def atrasos(tentativas, base=0.5, teto=5.0):
    if type(tentativas) is not int or not 1 <= tentativas <= 100:
        raise ValueError("tentativas_invalidas")
    if not 0 < base <= teto:
        raise ValueError("intervalos_invalidos")
    return [min(base * 2**i, teto) for i in range(tentativas-1)]
# fim:backoff


# trecho:metadados
def acrescentar_rotulo(estado, rotulo):
    if not isinstance(rotulo, str) or not rotulo.strip():
        raise ValueError("rotulo_invalido")
    novo = deepcopy(estado)
    novo["rotulo_interface"] = rotulo
    return novo


def aprovacao_vinculada(estado):
    aprovacao = estado.get("aprovacao") or {}
    return aprovacao.get("digest") == digest(estado["proposta"])
# fim:metadados
