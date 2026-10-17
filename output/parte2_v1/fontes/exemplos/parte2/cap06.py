"""Catálogo fechado de consultas; propostas não alteram o destino."""
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Literal
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode


BANCO = {
    "A-17": {"organizacao": "aurora", "id": "A-17",
             "revisao": 3, "status": "aberto", "usuarios": 80},
    "A-99": {"organizacao": "outra", "id": "A-99",
             "revisao": 1, "status": "fechado", "usuarios": 4},
}


# trecho:contrato
class Consulta(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    chamado_id: str = Field(pattern=r"^A-\d+$")


@dataclass(frozen=True)
class Escopo:
    organizacao: str
    permissoes: frozenset[str]


class PropostaMudanca(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    chamado_id: str = Field(pattern=r"^A-\d+$")
    revisao_observada: int = Field(ge=1)
    novo_status: Literal["em_analise"]
# fim:contrato


# trecho:consulta
def consultar(chamado_id: str, escopo: Escopo, banco):
    if "chamados:ler" not in escopo.permissoes:
        return {"ok": False, "erro": "sem_permissao"}
    registro = banco.get(chamado_id)
    if registro is None or registro["organizacao"] != escopo.organizacao:
        return {"ok": False, "erro": "indisponivel"}
    dados = {k: deepcopy(v) for k, v in registro.items()
             if k != "organizacao"}
    return {"ok": True, "dados": dados}


def ferramenta(escopo: Escopo, banco=None):
    destino = BANCO if banco is None else banco

    def ler(chamado_id: str):
        return consultar(chamado_id, escopo, destino)

    return StructuredTool.from_function(
        ler, name="consultar_chamado",
        description="Consulta um chamado visível ao usuário atual.",
        args_schema=Consulta,
    )
# fim:consulta


# trecho:despacho
def despachar(chamada, escopo, banco=None):
    identidade = chamada.get("id")
    if not isinstance(identidade, str) or not identidade.strip():
        raise ValueError("id_de_chamada_ausente")
    nome = chamada.get("name")
    consultou = False
    if nome != "consultar_chamado":
        resultado = {"ok": False, "erro": "ferramenta_desconhecida"}
    else:
        try:
            argumentos = Consulta.model_validate(chamada.get("args"))
        except ValidationError:
            resultado = {"ok": False, "erro": "argumentos_invalidos"}
        else:
            consultou = "chamados:ler" in escopo.permissoes
            resultado = ferramenta(escopo, banco).invoke(
                argumentos.model_dump())
    mensagem = ToolMessage(
        content=json.dumps(resultado, ensure_ascii=False),
        tool_call_id=identidade,
        name=nome if isinstance(nome, str) else "desconhecida",
        status="success" if resultado["ok"] else "error",
    )
    registro = {"id": identidade, "nome": nome,
                "consultou": consultou, "resultado": resultado}
    return mensagem, registro


def executar_lote(mensagem: AIMessage, escopo, banco=None):
    chamadas = mensagem.tool_calls
    ids = [c.get("id") for c in chamadas]
    if (mensagem.invalid_tool_calls or not 1 <= len(chamadas) <= 4
            or any(not isinstance(i, str) or not i.strip() for i in ids)
            or len(ids) != len(set(ids))):
        raise ValueError("lote_invalido")
    pares = [despachar(c, escopo, banco) for c in chamadas]
    return [p[0] for p in pares], [p[1] for p in pares]
# fim:despacho


# trecho:proposta
def propor(resultado):
    if not resultado.get("ok"):
        raise ValueError("consulta_sem_dados")
    dados = resultado["dados"]
    return PropostaMudanca(
        chamado_id=dados["id"],
        revisao_observada=dados["revisao"],
        novo_status="em_analise",
    ).model_dump()
# fim:proposta


# trecho:grafo
class EstadoConsulta(MessagesState):
    registros: list[dict]


def criar_grafo(escopo):
    def executar_no(estado):
        mensagens, registros = executar_lote(estado["messages"][-1], escopo)
        return {"messages": mensagens, "registros": registros}

    grafo = StateGraph(EstadoConsulta)
    grafo.add_node("consultar", executar_no)
    grafo.add_edge(START, "consultar")
    grafo.add_edge("consultar", END)
    return grafo.compile()


def criar_atalho_toolnode(escopo):
    grafo = StateGraph(MessagesState)
    grafo.add_node("consultar", ToolNode([ferramenta(escopo)]))
    grafo.add_edge(START, "consultar")
    grafo.add_edge("consultar", END)
    return grafo.compile()
# fim:grafo


if __name__ == "__main__":
    escopo = Escopo("aurora", frozenset({"chamados:ler"}))
    mensagem = AIMessage(content="", tool_calls=[{
        "name": "consultar_chamado", "args": {"chamado_id": "A-17"},
        "id": "consulta-1", "type": "tool_call",
    }])
    respostas, registros = executar_lote(mensagem, escopo)
    print(json.dumps({"registro": registros[0],
                      "proposta": propor(registros[0]["resultado"]),
                      "status_no_destino": BANCO["A-17"]["status"]},
                     ensure_ascii=False, indent=2))
