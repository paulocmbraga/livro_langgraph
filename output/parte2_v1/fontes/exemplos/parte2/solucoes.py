"""Implementações dos exercícios práticos da Parte II."""
import hashlib
import json
from langgraph.graph import add_messages


# trecho:metricas
def metricas_propostas(registros):
    total = len(registros)
    validas = sum(r["valida"] for r in registros)
    corretas = sum(r["valida"] and r["correta"] for r in registros)
    return {
        "n": total,
        "validade": validas / total if total else None,
        "correcao_total": corretas / total if total else None,
        "correcao_entre_validas": corretas / validas if validas else None,
    }


def uso_total(mensagens):
    usos = [m.usage_metadata for m in mensagens]
    if any(u is None for u in usos):
        return None
    return sum(u["total_tokens"] for u in usos)
# fim:metricas


# trecho:mensagens
def substituir_mensagem(mensagens, nova):
    if nova.id is None:
        raise ValueError("id_obrigatorio")
    return add_messages(mensagens, [nova])
# fim:mensagens


# trecho:proposta
def vinculo_proposta(proposta, organizacao):
    representacao = json.dumps(
        {"organizacao": organizacao, "proposta": proposta},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(representacao.encode("utf8")).hexdigest()


def conferir_versao(proposta, registro_atual):
    return (proposta["chamado_id"] == registro_atual["id"]
            and proposta["revisao_observada"] == registro_atual["revisao"])
# fim:proposta


# trecho:orcamento
def reservar(limite, gasto, pedido):
    if any(type(n) is not int or n < 0 for n in (limite, gasto, pedido)):
        raise ValueError("contagem_invalida")
    if gasto + pedido > limite:
        return None
    return gasto + pedido
# fim:orcamento


# trecho:recuperacao
def recall_ids(recuperados, relevantes):
    relevantes = set(relevantes)
    if not relevantes:
        return None
    return len(set(recuperados) & relevantes) / len(relevantes)


def cobertura_alegacoes(alegacoes, sustentadas):
    if not alegacoes:
        return None
    return sum(a in sustentadas for a in alegacoes) / len(alegacoes)
# fim:recuperacao
