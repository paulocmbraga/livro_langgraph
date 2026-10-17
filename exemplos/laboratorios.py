"""Matrizes da nova redação. Cada caso declara observado e esperado."""
import argparse
import copy
import json
import threading
from langgraph.graph import END, START, StateGraph
from exemplos import cap01, cap02, cap03, cap04, cap04_distribuicao as distribuicao
from exemplos.cap04_experimentos import comparar_atrasos, comparar_juncao


def chamado(**alteracoes):
    return {"id": "A-17", "tipo": "falha", "usuarios": 80,
            "descricao": "Portal indisponivel", **alteracoes}


def caso(nome, observado, esperado):
    if observado != esperado:
        raise AssertionError(f"{nome}: observado={observado!r}, esperado={esperado!r}")
    return {"caso": nome, "observado": observado, "esperado": esperado, "confere": True}


def recusa(operacao):
    try:
        operacao()
    except cap02.ErroContrato as erro:
        return str(erro)
    raise AssertionError("Era esperada uma recusa de contrato")


def laboratorio1():
    registros = []
    grafo = cap01.criar_grafo()
    for quantidade, esperado in ((0, "P3"), (1, "P2"), (49, "P2"), (50, "P1"), (80, "P1")):
        entrada = {"id": "A-17", "tipo": "falha", "usuarios": quantidade}
        correto = {"id": "A-17", "prioridade": esperado, "fila": "suporte"}
        observado = {"funcao": cap01.por_funcao(entrada), "grafo": grafo.invoke(entrada)["resultado"]}
        registros.append(caso(f"usuarios_{quantidade}", observado, {"funcao": correto, "grafo": correto}))
    for tipo, fila in (("orientacao", "conhecimento"), ("mudanca", "planejamento")):
        entrada = {"id": "A-18", "tipo": tipo, "usuarios": 0}
        registros.append(caso(tipo, grafo.invoke(entrada)["resultado"]["fila"], fila))
    eventos = list(grafo.stream({"id": "A-17", "tipo": "falha", "usuarios": 80}, stream_mode="updates"))
    registros.append(caso("caminho", [nome for evento in eventos for nome in evento], ["avaliar", "encaminhar"]))
    defeituoso = StateGraph(cap01.Estado)
    defeituoso.add_node("avaliar", lambda e: {"prioridade": "P1" if e["usuarios"] > 50 else "P2"})
    defeituoso.add_node("encaminhar", cap01.encaminhar)
    defeituoso.add_edge(START, "avaliar")
    defeituoso.add_edge("avaliar", "encaminhar")
    defeituoso.add_edge("encaminhar", END)
    errado = defeituoso.compile().invoke({"id":"A-17","tipo":"falha","usuarios":50})
    registros.append(caso("fronteira_50_detecta_maior_estrito", {
        "obtido":errado["resultado"]["prioridade"], "gabarito":"P1",
        "defeito_detectado":errado["resultado"]["prioridade"] != "P1",
    }, {"obtido":"P2","gabarito":"P1","defeito_detectado":True}))
    return registros


def laboratorio2():
    registros, contexto = [], cap02.Contexto()
    grafo = cap02.criar_grafo()
    for limiar, prioridade in ((50, "P1"), (100, "P2")):
        registros.append(caso(f"contexto_{limiar}", cap02.executar(chamado(), cap02.Contexto(limiar), grafo)["prioridade"], prioridade))
    variantes = [
        ("campo_ausente", {k:v for k,v in chamado().items() if k != "descricao"}, "campos"),
        ("campo_extra", chamado(aprovado=True), "campos"),
        ("numero_textual", chamado(usuarios="80"), "usuarios"),
        ("booleano", chamado(usuarios=True), "usuarios"),
        ("negativo", chamado(usuarios=-1), "usuarios"),
        ("tipo_desconhecido", chamado(tipo="outro"), "tipo"),
        ("descricao_vazia", chamado(descricao="  "), "descricao"),
    ]
    for nome, valor, campo in variantes:
        registros.append(caso(nome, recusa(lambda: cap02.executar(valor, contexto)), "entrada:"+campo))
    original = chamado(descricao="  Portal indisponivel  ")
    validado = cap02.validar_entrada(original)
    registros.append(caso("normalizacao", [validado["descricao"], original["descricao"]], ["Portal indisponivel", "  Portal indisponivel  "]))
    bruto = grafo.invoke(chamado(usuarios=True), context=contexto)
    registros.append(caso("anotacao_nao_recusa_booleano", bruto["prioridade"], "P2"))
    saida_errada = {"id": "A-99", "prioridade": "P1", "fila": "suporte"}
    registros.append(caso("saida_de_outro_chamado", recusa(lambda: cap02.validar_saida(saida_errada, chamado(), contexto)), "saida:id"))
    saida = cap02.executar(chamado(), contexto, grafo)
    estados = list(grafo.stream(chamado(), context=contexto, stream_mode="values"))
    registros.append(caso("projecao_e_stream", ["diagnostico" in saida, "diagnostico" in estados[-1]], [False, True]))
    return registros


def laboratorio3():
    registros = []
    grafo = cap03.montar_grafo().compile()
    for tipo, permite, rota, situacao in (
        ("falha", False, "diagnosticar", "concluido"),
        ("orientacao", False, "orientar", "concluido"),
        ("mudanca", False, "recusar", "recusado"),
        ("mudanca", True, "propor", "proposto"),
    ):
        politica = cap03.Politica(permite)
        entrada = chamado(tipo=tipo)
        resultado = cap03.atender(entrada, politica, grafo)
        trilha = [nome for evento in grafo.stream(entrada, context=politica, stream_mode="updates") for nome in evento]
        esperado = ["decidir", rota] + (["finalizar"] if situacao == "concluido" else [])
        registros.append(caso(f"{tipo}_{permite}", {"situacao": resultado["situacao"], "trilha": trilha}, {"situacao": situacao, "trilha": esperado}))
    entrada, politica = chamado(tipo="orientacao"), cap03.Politica()
    por_command = cap03.montar_grafo("command").compile()
    registros.append(caso("command_equivalente", cap03.atender(entrada, politica, por_command), cap03.atender(entrada, politica, grafo)))
    builder = cap03.montar_grafo("command")
    builder.add_node("lateral", lambda e: {})
    builder.add_edge("decidir", "lateral")
    builder.add_edge("lateral", END)
    nomes = [n for e in builder.compile().stream(entrada, context=politica, stream_mode="updates") for n in e]
    registros.append(caso("command_com_aresta_extra", sorted(nomes), sorted(["decidir", "orientar", "lateral", "finalizar"])))
    for nome, no in (
        ("fim_prematuro", cap03.decidir),
        ("concluido_sem_resposta", lambda e: {"rota":"orientar","situacao":"concluido"}),
    ):
        curto = StateGraph(cap03.Atendimento, context_schema=cap03.Politica)
        curto.add_node("decidir", no)
        curto.add_edge(START, "decidir")
        curto.add_edge("decidir", END)
        estado = curto.compile().invoke(entrada, context=politica)
        registros.append(caso(nome, recusa(lambda: cap03.validar_fim(estado, entrada, politica)), "final:resposta"))
    builder = StateGraph(cap03.Atendimento)
    builder.add_node("decidir", lambda e: {"rota": "inexistente"})
    builder.add_node("orientar", cap03.orientar)
    builder.add_edge(START, "decidir")
    builder.add_conditional_edges("decidir", lambda e:e["rota"], {"orientar":"orientar"})
    builder.add_edge("orientar", END)
    try:
        builder.compile().invoke(entrada)
    except KeyError:
        registros.append(caso("rota_inexistente", "KeyError", "KeyError"))
    else:
        raise AssertionError("Rota desconhecida foi aceita")
    return registros


def laboratorio4():
    registros = []
    for nome, atrasos in (("manual_atrasado", {"manual":0.03,"status":0}),
                          ("status_atrasado", {"manual":0,"status":0.03})):
        observacao = comparar_atrasos(atrasos)
        registro = caso(nome, sorted(d["documento"] for d in observacao["documentos"]), ["D-10", "D-20"])
        registro["eventos"] = observacao["eventos"]
        registro["ordem_agregada"] = [d["documento"] for d in observacao["documentos"]]
        registros.append(registro)
    sem_reducer = comparar_atrasos({"manual":0,"status":0}, agregar=False)
    registro = caso("sem_reducer", sem_reducer["erro"], "InvalidUpdateError")
    registro["eventos"] = sem_reducer["eventos"]
    registros.append(registro)
    chamadas, trava = [], threading.Lock()
    def contar(pacote):
        with trava:
            chamadas.append(pacote["fonte"])
        return distribuicao.buscar(pacote)
    grafo = distribuicao.criar_grafo(contar)
    resultado = grafo.invoke({"fontes":["manual","status","manual"],"documentos":[]})
    registros.append(caso("lote_repetido", {"chamadas":len(chamadas),"documentos":len(resultado["documentos"])}, {"chamadas":3,"documentos":2}))
    chamadas.clear()
    resultado = grafo.invoke({"fontes":[],"documentos":[]})
    registros.append(caso("lote_vazio", [len(chamadas),len(resultado["documentos"])], [0,0]))
    a = dict(cap04.FONTES["manual"])
    try:
        distribuicao.unir_documentos([a], [{**a,"texto":"Outro conteudo"}])
    except ValueError as erro:
        registros.append(caso("revisao_conflitante", str(erro), "mesma revisao com conteudos diferentes"))
    else:
        raise AssertionError("Conflito nao detectado")
    for espera, esperado in ((True,[2]),(False,[1,2])):
        resultado = comparar_juncao(espera)
        registros.append(caso(f"juncao_{espera}", resultado["leituras"], esperado))
    registros.append(caso("concat_vazia", [1,2]+[], [1,2]))
    return registros


LABORATORIOS = {1:laboratorio1, 2:laboratorio2, 3:laboratorio3, 4:laboratorio4}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capitulo", type=int, choices=LABORATORIOS, required=True)
    args = parser.parse_args()
    print(json.dumps({"capitulo":args.capitulo,"casos":LABORATORIOS[args.capitulo]()}, ensure_ascii=False, indent=2, allow_nan=False))
