"""Implementações de referência dos exercícios práticos da Parte I."""
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from exemplos import cap01, cap02, cap03


# trecho:categoria
def classificar_pedido(chamado: dict) -> dict:
    filas = {**cap01.FILAS, "pedido": "cadastro"}
    return {"id": chamado["id"], "prioridade": cap01.prioridade(chamado["usuarios"]),
            "fila": filas[chamado["tipo"]]}
# fim:categoria


# trecho:prazo
class EstadoComPrazo(cap01.Estado, total=False):
    prazo_minutos: int


def definir_prazo(estado: EstadoComPrazo) -> dict:
    prazos = {"P1": 15, "P2": 120, "P3": 480}
    return {"prazo_minutos": prazos[estado["prioridade"]]}


def grafo_com_prazo():
    construtor = StateGraph(EstadoComPrazo)
    construtor.add_node("avaliar", cap01.avaliar)
    construtor.add_node("encaminhar", cap01.encaminhar)
    construtor.add_node("prazo", definir_prazo)
    construtor.add_edge(START, "avaliar")
    construtor.add_edge("avaliar", "encaminhar")
    construtor.add_edge("encaminhar", "prazo")
    construtor.add_edge("prazo", END)
    return construtor.compile()
# fim:prazo


# trecho:normalizacao
def normalizar_usuarios(valor: object) -> int:
    if type(valor) is int and valor >= 0:
        return valor
    if type(valor) is str:
        texto = valor.strip()
        if texto and texto.isascii() and texto.isdecimal():
            return int(texto)
    raise cap02.ErroContrato("usuarios", "adaptador")


def adaptar_legado(entrada: dict) -> cap02.Entrada:
    copia = dict(entrada)
    if "usuarios" not in copia:
        raise cap02.ErroContrato("campos")
    copia["usuarios"] = normalizar_usuarios(copia["usuarios"])
    return cap02.validar_entrada(copia)
# fim:normalizacao


# trecho:descricao
def validar_descricao_limitada(entrada: object) -> cap02.Entrada:
    validada = cap02.validar_entrada(entrada)
    if len(validada["descricao"]) > 200:
        raise cap02.ErroContrato("descricao_longa")
    return validada
# fim:descricao


# trecho:encerramento
def recusar_com_codigo(estado: cap03.Atendimento) -> dict:
    return {"situacao":"recusado", "motivo":"PROPOSTA_DESABILITADA"}


def grafo_com_recusa_identificada():
    construtor = StateGraph(cap03.Atendimento, context_schema=cap03.Politica)
    construtor.add_node("decidir", cap03.decidir)
    construtor.add_node("recusar", recusar_com_codigo)
    construtor.add_edge(START, "decidir")
    construtor.add_conditional_edges("decidir", lambda e:e["rota"], {"recusar":"recusar"})
    construtor.add_edge("recusar", END)
    return construtor.compile()
# fim:encerramento


# trecho:fontes_unicas
def fontes_unicas(fontes: list[str]) -> list[str]:
    return list(dict.fromkeys(fontes))
# fim:fontes_unicas


# trecho:primeiro_vence
def primeiro_vence(atual: list[dict], novos: list[dict]) -> list[dict]:
    indice = {}
    for item in [*atual, *novos]:
        chave = (item["documento"], item["revisao"])
        if chave not in indice:
            indice[chave] = dict(item)
    return [indice[chave] for chave in sorted(indice)]
# fim:primeiro_vence
