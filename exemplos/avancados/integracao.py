"""Extensões dos projetos 23/24; a autoridade continua no domínio local."""
import json
from typing import Literal, TypedDict
from pydantic import BaseModel, ConfigDict, Field
from langgraph.graph import END, START, StateGraph
from . import guardrails as gr
from .coordenacao import digest
from .mcp_local import Cliente as MCP
from .a2a_local import Cliente as A2A, servidor
from exemplos.parte6.ensaios import bancada


def classificar_documento(texto):
    conhecidos = {"Use Aurora Connect para acessar a VPN corporativa.",
                  "Use Aurora Secure para acessar a VPN corporativa.",
                  "O prazo de atendimento é de dois dias úteis."}
    return {"risco": .05 if texto in conhecidos else .5,
            "motivo": "adequado" if texto in conhecidos else "incerto"}


class Estado(TypedDict, total=False):
    pergunta: str
    limpa: str
    fontes: list[str]
    versao: str
    resposta: dict
    publicacao: str
    decisao: str
    eventos: list[dict]


def criar_conhecimento(app, token, chave, classificar=classificar_documento):
    def admitir(s):
        d = gr.entrada(s["pergunta"])
        return {"pergunta": "", "limpa": d.texto, "decisao": d.acao,
                "eventos": [d.evento("entrada")]}

    def inspecionar(s):
        pessoa = app.dominio.autenticar(token)
        app.dominio.autorizar(pessoa, "ler", pessoa.org)
        versao, docs = app.conhecimento.recuperar(pessoa, s["limpa"])
        decisoes = [gr.julgar_contexto(d["texto"], classificar) for d in docs]
        if not docs:
            decisoes = [gr.Decisao("revisar", "sem_evidencia")]
        acao = next((d.acao for d in decisoes if d.acao != "permitir"), "permitir")
        return {"versao": versao, "fontes": [d["id"] for d in docs],
                "decisao": acao, "eventos": s["eventos"] +
                [d.evento("contexto") for d in decisoes]}

    def executar(s):
        id = app.criar(token, chave, {"tipo": "conhecimento", "texto": s["limpa"]})["id"]
        app.processar_um()
        resposta = app.consultar(token, id)["resultado"]
        return {"resposta": resposta or {}}

    # trecho:publicacao
    def publicar(s):
        r = s["resposta"]
        if r.get("corpus") != s["versao"]:
            d = gr.Decisao("revisar", "corpus_alterado")
        else:
            fontes = [f["id"] for f in r.get("fontes", [])]
            d = gr.saida(r.get("resposta"), fontes, s["fontes"])
        return {"resposta": {}, "publicacao": d.texto, "decisao": d.acao,
                "eventos": s["eventos"] + [d.evento("saida")]}

    g = StateGraph(Estado)
    for nome, funcao in [("admitir", admitir), ("contexto", inspecionar),
                         ("executar", executar), ("publicar", publicar)]:
        g.add_node(nome, funcao)
    g.add_edge(START, "admitir")
    for origem, destino in [("admitir", "contexto"), ("contexto", "executar")]:
        g.add_conditional_edges(origem, lambda s, d=destino:
            d if s["decisao"] in {"permitir", "mascarar"} else END)
    g.add_edge("executar", "publicar"); g.add_edge("publicar", END)
    return g.compile()
    # fim:publicacao


class Recomendacao(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    prioridade: Literal["alta", "normal"]
    fonte: Literal["D1"]
    revisao: int = Field(strict=True, ge=1, le=1)
    texto: str


# trecho:proposta
def propor_operacao(app, token, chave, mcp, a2a, prioridade):
    if prioridade not in {"alta", "normal"}:
        raise ValueError("Objetivo fora do contrato")
    observacao = mcp.consultar("A-17")
    tarefa = a2a.enviar(prioridade, chave)
    if tarefa["status"]["state"] != "TASK_STATE_COMPLETED":
        raise ValueError("Especialista ainda não concluiu")
    raw = tarefa["artifacts"][0]["parts"][0]["text"]
    recomendacao = Recomendacao.model_validate(json.loads(raw))
    d = gr.saida(recomendacao.texto, [recomendacao.fonte], {"D1"})
    if d.acao not in {"permitir", "mascarar"}:
        raise ValueError("Artefato retido")
    if recomendacao.prioridade != prioridade:
        raise ValueError("Divergência requer revisão antes da proposta")
    id = app.criar(token, chave, {"tipo": "operacao",
        "texto": "A-17 " + recomendacao.prioridade})["id"]
    app.processar_um()
    pausa = app.consultar(token, id)
    if pausa["status"] != "revisao":
        raise ValueError("Proposta local indisponível")
    dossie = {"id": id, "digest_local": pausa["digest"],
              "observacao_mcp": observacao, "tarefa_a2a": tarefa["id"],
              "recomendacao": {**recomendacao.model_dump(), "texto": d.texto}}
    return {"dossie": dossie, "digest": digest(dossie)}
# fim:proposta


def aprovar_operacao(app, revisor, pacote, digest_aprovado):
    d = pacote["dossie"]
    if digest(d) != digest_aprovado or pacote["digest"] != digest_aprovado:
        raise ValueError("Dossiê divergente")
    app.decidir(revisor, d["id"], {"aceitar": True, "digest": d["digest_local"]})
    app.processar_um()
    return app.consultar(revisor, d["id"])


def demonstrar():
    with bancada() as (app, tokens), servidor() as (url, agente), MCP() as m:
        a = A2A(url, next(iter(agente.tokens)))
        m.inicializar(); a.descobrir()
        conhecimento = criar_conhecimento(app, tokens["ana"], "consulta").invoke(
            {"pergunta": "VPN para ana@example.org"})
        pacote = propor_operacao(app, tokens["ana"], "operacao", m, a, "alta")
        antes = app.dominio.efeitos()
        final = aprovar_operacao(app, tokens["bia"], pacote, pacote["digest"])
        return {"conhecimento": {k: conhecimento[k] for k in
                    ("publicacao", "decisao", "eventos")},
                "antes_da_revisao": antes, "depois_da_revisao": app.dominio.efeitos(),
                "situacao": final["status"], "modelo_real": False}
