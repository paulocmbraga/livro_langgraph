"""Matrizes L09-L12: expectativas fixas e evidências locais."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from . import cap09, cap10, cap11, cap12
from .destino import (
    Destino, Diario, digest, RespostaPerdida, Colisao, RevisaoDivergente)


def caso(nome, observado, esperado):
    return {"nome": nome, "observado": observado,
            "esperado": esperado, "confere": observado == esperado}


def filho(pasta, acao, codigo=0):
    p = subprocess.run(
        [sys.executable, "-m", "exemplos.parte3.processo", str(pasta), acao],
        capture_output=True, text=True, encoding="utf8", timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=dict(os.environ, PYTHONUTF8="1", LANGSMITH_TRACING="false",
                 LANGCHAIN_TRACING_V2="false"))
    if p.returncode != codigo:
        raise AssertionError((acao, p.returncode, p.stderr))
    return json.loads(p.stdout) if codigo == 0 else {"codigo_saida": p.returncode}


def l09():
    casos, evidencias = [], {}
    cfg = cap09.configuracao("aurora:l09")
    with TemporaryDirectory() as pasta:
        ctx = cap09.Contexto(Destino(pasta))
        saver = InMemorySaver()
        g = cap09.criar_grafo(saver, True)
        g.invoke({"chamado_id": "A-17"}, cfg, context=ctx, durability="sync")
        casos.append(caso("mesmo_saver", bool(g.get_state(cfg).values), True))
        outro = cap09.criar_grafo(InMemorySaver())
        casos.append(caso("novo_saver_perde_estado",
                           bool(outro.get_state(cfg).values), False))
        casos.append(caso("outro_thread",
                           bool(g.get_state(cap09.configuracao("outro")).values), False))
        h = list(g.get_state_history(cfg))
        casos.append(caso("historico_identificado",
            len(h) >= 3 and len({s.config["configurable"]["checkpoint_id"] for s in h}) == len(h),
            True))
        antes = ctx.destino.contadores()
        cap09.inspecionar(g, cfg)
        list(g.get_state_history(cfg))
        casos.append(caso("inspecao_sem_executar", ctx.destino.contadores(), antes))
        pre = next(s for s in h if s.next == ("consultar",))
        g.invoke(None, pre.config, context=ctx, durability="sync")
        casos.append(caso("replay_reexecuta_leitura",
                           ctx.destino.contadores()["consultas"], 2))
        pausa = g.get_state(cfg)
        ctx.destino.aplicar(cap10.proposta_padrao("externa"))
        _, ramo = cap09.ramificar(g, pausa, "simulado")
        casos.append(caso("ramo_nao_desfaz_destino",
            [ramo["observacao"]["status"], ctx.destino.ler()["status"],
             ctx.destino.contadores()["efeitos"]],
            ["simulado", "em_analise", 1]))
        casos.append(caso("snapshot_anterior_preservado",
            g.get_state(pausa.config).values["observacao"]["status"], "aberto"))
    with TemporaryDirectory() as pasta:
        inicio = filho(pasta, "leitura_iniciar")
        leitura = filho(pasta, "leitura_inspecionar")
        fim = filho(pasta, "leitura_continuar")
        evidencias["processos_sqlite"] = [inicio, leitura, fim]
        casos.append(caso("sqlite_outro_processo",
            [inicio["pid"] != leitura["pid"], leitura["existe"],
             leitura["proximos"], fim["proximos"]],
            [True, True, ["resumir"], []]))
    with TemporaryDirectory() as pasta:
        inicio = filho(pasta, "memoria_iniciar")
        fim = filho(pasta, "memoria_inspecionar")
        evidencias["processos_memoria"] = [inicio, fim]
        casos.append(caso("memoria_outro_processo",
            [inicio["existe"], fim["existe"]], [True, False]))
    for modo in ("sync", "async", "exit"):
        with TemporaryDirectory() as pasta:
            d = Destino(pasta)
            with SqliteSaver.from_conn_string(str(Path(pasta)/"g.sqlite")) as s:
                g = cap09.criar_grafo(s)
                g.invoke({"chamado_id": "A-17"}, cfg,
                         context=cap09.Contexto(d), durability=modo)
                casos.append(caso("modo_"+modo,
                    g.get_state(cfg).values["observacao"]["status"], "aberto"))
    return casos, evidencias


@contextmanager
def bancada10():
    with TemporaryDirectory() as pasta:
        ctx = cap10.Contexto(Destino(pasta), Diario(pasta))
        with SqliteSaver.from_conn_string(str(Path(pasta)/"g.sqlite")) as saver:
            yield ctx, cap10.criar_grafo(saver), cap09.configuracao("l10")


def revisar10(ctx, g, cfg, comando=None):
    proposta = cap10.proposta_padrao()
    g.invoke({"proposta": proposta}, cfg, context=ctx, durability="sync")
    return g.invoke(comando or cap10.aprovar(proposta), cfg,
                    context=ctx, durability="sync")


def l10():
    casos, evidencias = [], {}
    with bancada10() as (ctx, g, cfg):
        r = revisar10(ctx, g, cfg)
        casos.append(caso("01_confirmacao_e_reentrada",
            [r["situacao"], *ctx.destino.contadores().values()],
            ["confirmed", 2, 1, 0, 1]))
    with bancada10() as (ctx, g, cfg):
        r = revisar10(ctx, g, cfg, cap10.aprovar(cap10.proposta_padrao(), False))
        casos.append(caso("02_rejeicao",
            [r["situacao"], ctx.destino.contadores()["efeitos"]], ["rejeitada", 0]))
    with bancada10() as (ctx, g, cfg):
        r = revisar10(ctx, g, cfg, Command(resume={
            "aceitar": True, "operacao": "op-001", "digest": "outro"}))
        casos.append(caso("03_conteudo_divergente",
            [r["situacao"], ctx.destino.contadores()["despachos"]], ["recusada", 0]))
    with bancada10() as (ctx, g, cfg):
        ctx.pode_aprovar = False
        r = revisar10(ctx, g, cfg)
        casos.append(caso("04_revisor_sem_permissao",
            [r["situacao"], ctx.destino.contadores()["efeitos"]], ["recusada", 0]))
    for numero, falha, efeitos in ((5, "antes_commit", 0), (6, "depois_commit", 1)):
        with bancada10() as (ctx, g, cfg):
            ctx.falha = falha
            r = revisar10(ctx, g, cfg)
            antes = [r["situacao"], ctx.destino.contadores()["efeitos"]]
            conc = cap10.conciliar(ctx, cap10.proposta_padrao())
            casos.append(caso(f"{numero:02}_{falha}",
                [*antes, conc["situacao"]],
                ["unknown", efeitos, "confirmed" if efeitos else "unknown"]))
    for numero, dedup, efeitos in ((7, False, 2), (8, True, 1)):
        with TemporaryDirectory() as pasta:
            d = Destino(pasta)
            proposta = cap10.proposta_padrao()
            try:
                d.aplicar(proposta, deduplicar=dedup, falha="depois_commit")
            except RespostaPerdida:
                pass
            d.aplicar(proposta, deduplicar=dedup)
            casos.append(caso(f"{numero:02}_reenvio_deduplicar_{dedup}",
                [d.contadores()["despachos"], d.contadores()["efeitos"]], [2, efeitos]))
    with TemporaryDirectory() as pasta:
        inicio = filho(pasta, "operacao_iniciar")
        queda = filho(pasta, "operacao_cair", 23)
        final = filho(pasta, "operacao_recuperar")
        evidencias["queda_entre_compromissos"] = [inicio, queda, final]
        casos.append(caso("09_processo_encerrado_apos_efeito",
            [queda["codigo_saida"], final["situacao"], final["revisoes"],
             final["despachos"], final["consultas"], final["efeitos"]],
            [23, "confirmed", 2, 1, 1, 1]))
    with TemporaryDirectory() as pasta:
        d = Destino(pasta)
        proposta = cap10.proposta_padrao()
        d.aplicar(proposta)
        colisao = False
        try:
            d.aplicar({**proposta, "novo_status": "aberto"})
        except Colisao:
            colisao = True
        casos.append(caso("10_chave_com_outro_conteudo",
            [colisao, d.contadores()["efeitos"]], [True, 1]))
    with bancada10() as (ctx, g, cfg):
        ctx.falha = "depois_commit"
        r = revisar10(ctx, g, cfg)
        casos.append(caso("11_suspensao_sem_consulta",
            [r["situacao"], ctx.diario.ler("op-001")["situacao"],
             ctx.destino.contadores()["consultas"]], ["unknown", "unknown", 0]))
    with bancada10() as (ctx, g, cfg):
        ctx.falha, ctx.consulta_disponivel = "depois_commit", False
        revisar10(ctx, g, cfg)
        r = cap10.conciliar(ctx, cap10.proposta_padrao())
        casos.append(caso("12_conciliacao_indisponivel",
            [r["situacao"], ctx.destino.contadores()["despachos"],
             ctx.destino.contadores()["efeitos"]], ["unknown", 1, 1]))
    return casos, evidencias


def l11():
    casos, evidencias = [], {}
    contador = {"tentativas": 0}
    valor = cap11.criar_retry(contador).invoke({"valor": 0})["valor"]
    casos.append(caso("retry_transitorio", [valor, contador["tentativas"]], [17, 3]))
    for nome, definitiva, falhas, esperado in (
            ("definitiva_nao_repete", True, 0, 1), ("orcamento_esgotado", False, 9, 3)):
        contador = {"tentativas": 0}
        try:
            cap11.criar_retry(contador, falhas, definitiva).invoke({"valor": 0})
        except (cap11.Transitoria, cap11.Definitiva):
            pass
        casos.append(caso(nome, contador["tentativas"], esperado))
    with TemporaryDirectory() as pasta:
        contador, cfg = {"a": 0, "b": 0}, cap09.configuracao("paralelo")
        arquivo = str(Path(pasta)/"g.sqlite")
        with SqliteSaver.from_conn_string(arquivo) as s:
            g = cap11.criar_paralelo(s, contador, True)
            try:
                g.invoke({"evidencias": []}, cfg, durability="sync")
            except cap11.Transitoria:
                pass
        with SqliteSaver.from_conn_string(arquivo) as s:
            g = cap11.criar_paralelo(s, contador, False)
            final = g.invoke(None, cfg, durability="sync")
        casos.append(caso("pending_writes",
            [contador, sorted(final["evidencias"])], [{"a": 1, "b": 2}, ["A", "B"]]))
    with TemporaryDirectory() as pasta:
        f = cap11.Fila(Path(pasta)/"fila.sqlite")
        a = f.adquirir("op", "a", 0)
        b = f.adquirir("op", "b", 1)
        casos.append(caso("posse_ativa", [a, b], [1, None]))
        b = f.adquirir("op", "b", 11)
        casos.append(caso("posse_vencida", b, 2))
        casos.append(caso("worker_antigo_nao_conclui", f.concluir("op", "a", a, 12), False))
        casos.append(caso("worker_atual_conclui", f.concluir("op", "b", b, 12), True))
        casos.append(caso("concluido_nao_reabre", f.adquirir("op", "c", 30), None))
    casos.append(caso("posse_nao_deduplica_destino",
        {k:v for k,v in cap11.executar().items() if k in ("despachos","efeitos")},
        {"despachos": 2, "efeitos": 1}))
    with TemporaryDirectory() as pasta:
        d, proposta = Destino(pasta), cap10.proposta_padrao()
        recibo = d.aplicar(proposta)
        inversa = cap11.compensar(d, proposta, recibo)
        casos.append(caso("compensacao_novo_efeito",
            [inversa["operacao"], d.ler()["status"], d.contadores()["efeitos"]],
            ["op-001:compensar", "aberto", 2]))
    with TemporaryDirectory() as pasta:
        d, proposta = Destino(pasta), cap10.proposta_padrao()
        recibo = d.aplicar(proposta)
        d.aplicar(cap10.proposta_padrao("concorrente"))
        recusou = False
        try:
            cap11.compensar(d, proposta, recibo)
        except RevisaoDivergente:
            recusou = True
        casos.append(caso("compensacao_revisionada",
            [recusou, d.contadores()["efeitos"]], [True, 2]))
    return casos, evidencias


@contextmanager
def bancada12():
    with TemporaryDirectory() as pasta:
        d = Destino(pasta)
        c = cap12.Catalogo(Path(pasta)/"catalogo.sqlite")
        c.cadastrar("antiga", 1)
        ctx = cap12.Contexto(d)
        with SqliteSaver.from_conn_string(str(Path(pasta)/"g.sqlite")) as s:
            gs = {v: cap12.criar_grafo(s, v) for v in (1, 2)}
            cfg, e = cap09.configuracao("antiga"), cap12.fixture_v1()
            c.invocar(gs, e, cfg, ctx)
            c.invocar(gs, cap10.aprovar(e["proposta"]), cfg, ctx)
            yield pasta, d, c, ctx, gs, cfg


def l12():
    casos, evidencias = [], {}
    with bancada12() as (_, d, c, ctx, gs, cfg):
        snapshot = gs[1].get_state(cfg)
        casos.append(caso("fixture_aprovada_pendente",
            [snapshot.next, bool(snapshot.values["aprovacao"]), d.contadores()["efeitos"]],
            [("executar",), True, 0]))
        recusou = False
        try:
            gs[2].invoke(None, cfg, context=ctx, durability="sync")
        except cap12.Incompativel:
            recusou = True
        casos.append(caso("v2_recusa_v1", [recusou, d.contadores()["efeitos"]], [True, 0]))
    with bancada12() as (_, d, c, ctx, gs, cfg):
        final = c.invocar(gs, None, cfg, ctx)
        casos.append(caso("manter_runtime_v1",
            [final["situacao"], d.contadores()["efeitos"]], ["confirmed", 1]))
    with bancada12() as (pasta, d, c, ctx, gs, cfg):
        antiga = gs[1].get_state(cfg)
        nova = c.migrar(gs[1], cfg, d, "nova", "op-nova")
        casos.append(caso("migracao_invalida_aprovacao",
            [nova["versao"], nova["aprovacao"], nova["proposta"]["expected_revision"]],
            [2, None, 3]))
        casos.append(caso("trilha_migracao",
            [nova["migracao"]["origem"],
             nova["migracao"]["digest_anterior"] != nova["migracao"]["digest_novo"],
             nova["migracao"]["checkpoint_id"] == antiga.config["configurable"]["checkpoint_id"]],
            ["antiga", True, True]))
        reaberto = cap12.Catalogo(Path(pasta)/"catalogo.sqlite")
        casos.append(caso("entrada_migrada_duravel",
            reaberto.entrada_migrada("nova") == nova, True))
        recusou = False
        try:
            c.invocar(gs, None, cfg, ctx)
        except cap12.Incompativel:
            recusou = True
        casos.append(caso("origem_inativa", [recusou, d.contadores()["efeitos"]], [True, 0]))
        nc = cap09.configuracao("nova")
        r = c.invocar(gs, nova, nc, ctx)
        casos.append(caso("nova_revisao_obrigatoria",
            [bool(r.get("__interrupt__")), d.contadores()["efeitos"]], [True, 0]))
        c.invocar(gs, cap10.aprovar(nova["proposta"]), nc, ctx)
        final = c.invocar(gs, None, nc, ctx)
        casos.append(caso("v2_confirmada",
            [final["situacao"], d.ler()["revisao"], d.contadores()["efeitos"]],
            ["confirmed", 4, 1]))
    with bancada12() as (_, d, c, ctx, gs, cfg):
        nova = c.migrar(gs[1], cfg, d, "nova", "op-nova")
        nc = cap09.configuracao("nova")
        c.invocar(gs, nova, nc, ctx)
        c.invocar(gs, cap10.aprovar(nova["proposta"]), nc, ctx)
        d.aplicar(cap10.proposta_padrao("externa"))
        recusou = False
        try:
            c.invocar(gs, None, nc, ctx)
        except RevisaoDivergente:
            recusou = True
        casos.append(caso("revisao_mudou_apos_aprovacao",
            [recusou, d.contadores()["efeitos"]], [True, 1]))
    with bancada12() as (_, d, c, ctx, gs, cfg):
        d.aplicar(cap12.fixture_v1()["proposta"])
        recusou = False
        try:
            c.migrar(gs[1], cfg, d, "nova", "op-nova")
        except cap12.Incompativel:
            recusou = True
        casos.append(caso("efeito_preexistente_impede_migracao",
            [recusou, d.contadores()["efeitos"]], [True, 1]))
    with bancada12() as (_, d, c, ctx, gs, cfg):
        recusou = False
        try:
            c.migrar(gs[1], cfg, d, "nova", "op-legada")
        except cap12.Incompativel:
            recusou = True
        casos.append(caso("nao_reusar_identidade", recusou, True))
    # JSON é a fronteira de publicação dos resultados: tuplas viram listas.
    return json.loads(json.dumps(casos)), evidencias


def executar(capitulo):
    casos, evidencias = {9:l09, 10:l10, 11:l11, 12:l12}[capitulo]()
    if not all(c["confere"] for c in casos):
        raise AssertionError([c for c in casos if not c["confere"]])
    return {"capitulo": capitulo, "casos": casos, "evidencias": evidencias,
            "escopo": "SQLite local e falhas controladas; sem serviços externos"}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capitulo", type=int, choices=range(9,13), required=True)
    print(json.dumps(executar(p.parse_args().capitulo), ensure_ascii=False, indent=2))
