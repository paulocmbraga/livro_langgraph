"""L13-L16: expectativas fixas, casos adversos e relatórios locais."""
import argparse
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from exemplos.parte4 import cap13 as c13, cap14 as c14, cap15 as c15, cap16 as c16


def caso(nome, observado, esperado):
    return {"nome": nome, "observado": observado, "esperado": esperado,
            "confere": observado == esperado}


def recusa(funcao, erro=ValueError):
    try:
        funcao()
    except erro:
        return True
    return False


def l13():
    h = c13.conversa()
    original = c13.hash_historico(h)
    pergunta = "Qual o prazo do caso A-17?"
    def avaliar(hist, politica, resumo=None, limite=240):
        r = c13.criar_grafo(limite).invoke({
            "historico": hist, "pergunta": pergunta,
            "politica": politica, "resumo": resumo})
        return {"resposta": r["resposta"], "motivo": r["motivo"],
                "fato_no_contexto": c13.responder_controlado(r["pacote"]["mensagens"]),
                "estimativa": r["pacote"]["estimativa_entrada"]}
    bom = c13.resumo_preparado(h, "prazo_dias=5")
    ruim = c13.resumo_preparado(h, "prazo_dias=9")
    completo = avaliar(h, "completo")
    janela = avaliar(h, "janela")
    resumo = avaliar(h, "resumo", bom)
    inventado = avaliar(h, "resumo", ruim)
    hc = c13.conversa(True)
    desatualizado = c13.resumo_preparado(hc, "prazo_dias=5")
    mensagens = [
        HumanMessage(content="Consulte o prazo.", id="u"),
        AIMessage(content="", tool_calls=[
            {"name": "consultar", "args": {}, "id": "c"}]),
        ToolMessage(content="prazo_dias=5", tool_call_id="c")]
    selecionado = c13.montar(mensagens, pergunta, "janela")
    casos = [
        caso("completo_excede", completo["motivo"], "contexto_excedido"),
        caso("completo_cabe_em_outro_limite", avaliar(h, "completo", limite=1000)["resposta"], 5),
        caso("janela_perde_decisao", janela["resposta"], None),
        caso("resumo_preserva_decisao", resumo["resposta"], 5),
        caso("resumo_inventa_com_hash_valido", inventado["resposta"], 9),
        caso("hash_antigo_recusado", recusa(lambda: avaliar(hc, "resumo", bom)), True),
        caso("correcao_recente_na_janela", avaliar(hc, "janela")["resposta"], 2),
        caso("resumo_omite_correcao", avaliar(hc, "resumo", desatualizado)["resposta"], 5),
        caso("episodio_de_ferramenta_inteiro",
             [type(m).__name__ for m in selecionado["mensagens"]],
             ["SystemMessage", "HumanMessage", "AIMessage", "ToolMessage", "HumanMessage"]),
        caso("resultado_orfao_recusado", recusa(lambda: c13.episodios(mensagens[2:])), True),
        caso("orcamento_invalido", recusa(lambda: c13.montar(h, pergunta, "janela", 40, 40)), True),
        caso("historico_preservado", c13.hash_historico(h) == original, True),
    ]
    comparacao = []
    for nome, r in (("completo", completo), ("janela", janela),
                    ("resumo", resumo), ("resumo_ruim", inventado)):
        comparacao.append({"politica": nome, **r, "esperado": 5,
                           "correta": r["resposta"] == 5,
                           "fato_preservado": r["fato_no_contexto"] == 5,
                           "estimativa_preparacao": bom.custo_estimado_producao
                           if nome.startswith("resumo") else 0,
                           "uso_real": None})
    return casos, {"comparacao": comparacao, "contador": "aproximacao_4_caracteres",
                   "inferencias_reais": 0}


def l14():
    m, i = c14.Memorias(), c14.Identidade("aurora", "ana")
    m.escrever(i, "idioma", c14.preferencia(), 0, 1)
    g = c14.criar_grafo(m, InMemorySaver())
    def ler_thread(t):
        return g.invoke({"chave": "idioma"},
            {"configurable": {"thread_id": t}}, context=c14.Contexto(i, m, 2))
    primeiro, segundo = ler_thread("t1"), ler_thread("t2")
    casos = [caso("duas_threads", [primeiro["memoria"]["dados"]["valor"],
                                  segundo["memoria"]["dados"]["valor"]], ["pt-BR", "pt-BR"])]
    novo = m.escrever(i, "idioma", c14.preferencia("en"), 1, 2)
    casos += [
        caso("correcao_versionada", [novo["versao"], m.ler(i, "idioma", 2)["dados"]["valor"]], [2, "en"]),
        caso("escrita_antiga_recusada", recusa(lambda: m.escrever(i, "idioma", c14.preferencia(), 1, 2)), True),
        caso("outro_usuario", m.ler(c14.Identidade("aurora", "bia"), "idioma", 2), None),
        caso("outra_organizacao", m.ler(c14.Identidade("outra", "ana"), "idioma", 2), None),
        caso("vencida_invisivel", m.ler(i, "idioma", 20), None),
        caso("vencida_ainda_armazenada", m.store.get(c14.namespace(i), "idioma").value["dados"] is not None, True),
        caso("expurgo_remove_conteudo", [m.expurgar_vencidas(i, 20),
             m.store.get(c14.namespace(i), "idioma").value["dados"]], [1, None]),
        caso("versao_zero_nao_ressuscita", recusa(lambda: m.escrever(i, "idioma", c14.preferencia(expira=30), 0, 20)), True),
        caso("checkpoint_ainda_tem_copia", g.get_state({"configurable": {"thread_id": "t1"}}).values["memoria"]["dados"]["valor"], "pt-BR"),
        caso("outra_instancia_nao_persiste", c14.Memorias().ler(i, "idioma", 2), None),
        caso("store_direto_nao_autentica", m.store.get(c14.namespace(i), "idioma") is not None, True),
    ]
    return casos, {"tombstone": m.store.get(c14.namespace(i), "idioma").value,
                   "persistencia_entre_processos": False}


def contexto15():
    return c15.Contexto("aurora", dict(entradas_pai=0, buscas=0, revisoes=0))


def l15():
    casos = []
    ctx = contexto15()
    direto = c15.criar_especialista(False).invoke(
        {"pergunta": "VPN", "organizacao": "aurora"}, context=ctx)
    casos.append(caso("saida_direta_projetada", sorted(direto),
                      ["fonte", "resposta", "situacao"]))
    with TemporaryDirectory() as pasta:
        arquivo = str(Path(pasta)/"checkpoints.sqlite")
        cfg = {"configurable": {"thread_id": "aninhada"}}
        ctx = contexto15()
        with SqliteSaver.from_conn_string(arquivo) as saver:
            g = c15.criar_pai(saver)
            r = g.invoke({"pergunta": "VPN", "segredo_sintetico": "restrito"}, cfg, context=ctx)
            pedido = r["__interrupt__"][0].value
            s = g.get_state(cfg, subgraphs=True)
            interno = s.tasks[0].state
            casos += [
                caso("pai_pendente", list(s.next), ["consultar"]),
                caso("filho_pendente", list(interno.next), ["revisar"]),
                caso("entrada_minima", "segredo_sintetico" in interno.values, False),
                caso("namespace_aninhado", bool(interno.config["configurable"]["checkpoint_ns"]), True)]
        with SqliteSaver.from_conn_string(arquivo) as saver:
            g = c15.criar_pai(saver)
            final = g.invoke(Command(resume={"aceitar": True, "digest": pedido["digest"]}), cfg, context=ctx)
            casos += [
                caso("retomada_apos_reabrir", final["publicado"], direto),
                caso("reentrada_sem_nova_busca", ctx.contadores,
                     {"entradas_pai": 2, "buscas": 1, "revisoes": 2}),
                caso("bruto_nao_sai_no_contrato", "bruto" in final, False)]
    g = c15.criar_pai(InMemorySaver())
    cfg = {"configurable": {"thread_id": "recusa"}}
    ctx = contexto15()
    g.invoke({"pergunta": "VPN"}, cfg, context=ctx)
    recusado = g.invoke(Command(resume={"aceitar": True, "digest": "outro"}), cfg, context=ctx)
    casos.append(caso("revisao_divergente", recusado["publicado"]["situacao"], "recusada"))
    ctx = contexto15()
    g = c15.criar_pai(InMemorySaver(), False)
    eventos = list(g.stream({"pergunta": "VPN", "segredo_sintetico": "restrito"},
        {"configurable": {"thread_id": "stream"}}, context=ctx,
        stream_mode="updates", subgraphs=True))
    publicos = list(c15.eventos_publicos(eventos))
    casos.append(caso("eventos_projetados",
        [any(ns and "recuperar" in d for ns, d in eventos), publicos],
        [True, [direto]]))
    for persistente, esperado in ((False, [1, 1]), (True, [1, 2])):
        g = c15.criar_contador(InMemorySaver(), persistente)
        cfg = {"configurable": {"thread_id": "contador"}}
        valores = [g.invoke({}, cfg)["resultado"] for _ in range(2)]
        casos.append(caso("contador_" + str(persistente), valores, esperado))
    return casos, {"eventos_brutos": len(eventos), "eventos_publicos": publicos,
                   "retomada": "mesmo processo, conexao SQLite reaberta"}


def l16():
    dados = c16.executar()
    r = dados["resultados"]
    por = {a: [x for x in r if x["arquitetura"] == a]
           for a in ("unico", "delegado", "delegado_ruim")}
    metricas = {}
    for a, itens in por.items():
        acertos = sum(x["correta"] for x in itens)
        consumo = sum(x["estimativa"] for x in itens)
        metricas[a] = {"tarefas": 6, "corretas": acertos,
                      "concluidas": sum(x["motivo"] == "concluido" for x in itens),
                      "indevidas": sum(x["indevidas"] for x in itens),
                      "chamadas": sum(x["chamadas"] for x in itens),
                      "estimativa_total": consumo,
                      "estimativa_por_tarefa_correta": consumo / acertos,
                      "uso_real": None}
    misto = c16.executar_caso(c16.CASOS[2], "delegado", 5)
    orc = c16.Orcamento()
    repetido = c16.criar_delegado(c16.CASOS[0], orc,
        ["conhecimento", "conhecimento"]).invoke({"entregas": []})
    casos = [
        caso("unico_mesmos_seis", metricas["unico"]["corretas"], 6),
        caso("delegado_mesmos_seis", metricas["delegado"]["corretas"], 5),
        caso("roteamento_ruim", metricas["delegado_ruim"]["corretas"], 4),
        caso("misto_exige_sintese", [por["delegado"][2]["motivo"], por["delegado"][2]["chamadas"]], ["orcamento", 4]),
        caso("misto_com_cinco", [misto["correta"], misto["chamadas"]], [True, 5]),
        caso("delegacao_indevida", metricas["delegado_ruim"]["indevidas"], 1),
        caso("tres_chamadas_para_vpn", por["delegado"][0]["chamadas"], 3),
        caso("mais_estimativa_para_vpn", por["delegado"][0]["estimativa"] > por["unico"][0]["estimativa"], True),
        caso("orcamento_zero", c16.executar_caso(c16.CASOS[0], "delegado", 0)["chamadas"], 0),
        caso("especialista_repetido", repetido["motivo"], "sem_progresso"),
        caso("destino_fora_do_catalogo", recusa(lambda: c16.Decisao.model_validate({"destino": "internet"})), True),
        caso("transferencia_ao_pai", c16.criar_transferencia().invoke({}),
             {"motivo": "exige_supervisao", "destino": "revisor"}),
    ]
    return casos, {"metricas": metricas, "execucoes": r, "inferencias_reais": 0}


def executar(numero):
    casos, evidencias = {13: l13, 14: l14, 15: l15, 16: l16}[numero]()
    if len(casos) != 12 or not all(c["confere"] for c in casos):
        raise AssertionError([c for c in casos if not c["confere"]])
    return {"capitulo": numero, "casos": casos, "evidencias": evidencias}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capitulo", type=int, choices=range(13, 17), required=True)
    print(json.dumps(executar(parser.parse_args().capitulo),
                     ensure_ascii=False, indent=2))
