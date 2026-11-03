"""Executar: python -m l11.campanha DIRETORIO_NOVO [--repeticoes 2]."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from importlib.metadata import version
import json
import multiprocessing as mp
from pathlib import Path
import platform
import tempfile
import time

from .destino import digest, requisicao, servir
from .grafo import abrir, config, executar

CTX = mp.get_context("spawn")
JANELAS = ("antes", "commit", "resposta")
VARIANTES = ("estavel", "mutante")


def exigir(condicao, mensagem):
    if not condicao:
        raise AssertionError(mensagem)


@contextmanager
def servico(pasta):
    rx, tx = CTX.Pipe(duplex=False)
    commit, liberar, ocultar = (CTX.Event() for _ in range(3))
    p = CTX.Process(target=servir, args=(pasta / "destino.sqlite", tx, commit, liberar, ocultar))
    p.start()
    tx.close()
    try:
        exigir(rx.poll(30), "serviço não informou porta")
        yield f"http://127.0.0.1:{rx.recv()}", commit, liberar, ocultar
    finally:
        rx.close()
        liberar.set()
        if p.is_alive():
            p.terminate()
        p.join(10)


def ler_grafo(pasta, url, ident):
    with abrir(pasta, url) as g:
        s = g.get_state(config(ident))
        return {"checkpoint": s.config["configurable"]["checkpoint_id"],
                "proximos": list(s.next), "estado": s.values,
                "interrupcoes": [i.value for t in s.tasks for i in t.interrupts]}


def auditar(url, ident):
    status, rows = requisicao(url, "/auditoria/" + ident)
    exigir(status == 200, "auditoria do destino indisponível")
    return rows


def preparar(pasta, url, ident):
    pedido = {"intencao": ident, "chamado": "VPN-42", "minutos": 30}
    with abrir(pasta, url) as g:
        g.invoke({"pedido": pedido}, config(ident), durability="sync")
    pausado = ler_grafo(pasta, url, ident)
    exigir(pausado["proximos"] == ["revisar"] and len(pausado["interrupcoes"]) == 1,
           "revisão não persistida")
    s = pausado["estado"]
    return pausado, {"autorizar": True, "chave": s["chave"], "digest": s["digest"]}


@contextmanager
def worker(pasta, url, ident, variante, janela, replay, voto):
    marco = CTX.Event()
    p = CTX.Process(target=executar, args=(pasta, url, ident, variante, janela, replay, voto, marco))
    p.start()
    try:
        yield p, marco
    finally:
        if p.is_alive():
            p.kill()
        p.join(10)


def concluir(p):
    p.join(45)
    exigir(p.exitcode == 0, f"worker não concluiu normalmente: {p.exitcode}")


def trajetoria(pasta, url, commit, liberar, ident, variante, janela):
    pasta.mkdir()
    commit.clear()
    liberar.clear()
    revisao, voto = preparar(pasta, url, ident)
    with worker(pasta, url, ident, variante, janela, False, voto) as (p, marco):
        observado = commit if janela == "commit" else marco
        exigir(observado.wait(40) and p.is_alive(), f"janela {janela} não alcançada por {ident}")
        antes = ler_grafo(pasta, url, ident)
        efeitos_antes = auditar(url, ident)
        exigir(antes["proximos"] == ["despachar"] and antes["estado"]["fase"] == "autorizada",
               "o checkpoint não está na fronteira esperada")
        exigir(len(efeitos_antes) == int(janela != "antes"), "janela sem prova de efeito")
        p.kill()
        p.join(10)
        exigir(p.exitcode not in (None, 0), "morte do worker não confirmada")
        processo = {"pid": p.pid, "saida": p.exitcode}
    liberar.set()
    depois_da_queda = ler_grafo(pasta, url, ident)
    exigir(depois_da_queda == antes, "checkpoint mudou durante a morte")
    with worker(pasta, url, ident, variante, "", True, None) as (novo, _):
        concluir(novo)
        processo["novo_pid"] = novo.pid
    final = ler_grafo(pasta, url, ident)
    efeitos = auditar(url, ident)
    esperado = 2 if variante == "mutante" and janela != "antes" else 1
    exigir(len(efeitos) == esperado and not final["proximos"] and
           final["estado"]["recibo"] in {r["recibo"] for r in efeitos}, "resultado inesperado")
    return {"id": ident, "variante": variante, "janela": janela, "revisao": revisao,
            "decisao_roteirizada": voto, "marco_observado": janela, "worker": processo,
            "antes_da_morte": antes, "apos_a_morte": depois_da_queda, "efeitos_antes": efeitos_antes,
            "final": final, "efeitos_finais": efeitos}


def controles(pasta, url, commit, liberar, ocultar):
    casos = {}
    for ident in ("normal", "negada", "voto_obsoleto", "timeout"):
        d = pasta / ident
        d.mkdir()
        _, voto = preparar(d, url, ident)
        if ident == "negada":
            voto["autorizar"] = False
        if ident == "voto_obsoleto":
            voto["digest"] = "outra-revisao"
        janela = "timeout" if ident == "timeout" else ""
        commit.clear()
        liberar.clear()
        with worker(d, url, ident, "estavel", janela, False, voto) as (p, _):
            if janela:
                exigir(commit.wait(30), "timeout não alcançou o commit")
                ocultar.set()
            concluir(p)
        s = ler_grafo(d, url, ident)
        efeitos = auditar(url, ident)
        casos[ident] = {"voto": voto, "primeiro": s, "efeitos": efeitos}
        if janela:
            exigir(s["proximos"] == ["triagem"] and s["estado"]["fase"] == "desconhecida"
                   and len(efeitos) == 1, "timeout não preservou incerteza")
            liberar.set()
            with worker(d, url, ident, "estavel", "", True, "reconciliar") as (p, _):
                concluir(p)
            sem_consulta = ler_grafo(d, url, ident)
            exigir(sem_consulta["proximos"] == ["triagem"] and
                   sem_consulta["estado"]["fase"] == "desconhecida", "503 encerrou a triagem")
            casos[ident]["consulta_503"] = sem_consulta
            ocultar.clear()
            with worker(d, url, ident, "estavel", "", True, "reconciliar") as (p, _):
                concluir(p)
            final = ler_grafo(d, url, ident)
            exigir(final["estado"]["recibo"] == efeitos[0]["recibo"] and
                   auditar(url, ident) == efeitos, "reconciliação após timeout falhou")
            casos[ident]["restabelecida"] = final
        else:
            normal = ident == "normal"
            exigir(len(efeitos) == int(normal) and
                   s["estado"]["fase"] == ("confirmada" if normal else "recusada"),
                   "falha no controle " + ident)

    pedido = {"intencao": "corrida", "chamado": "VPN-42", "minutos": 30}
    corpo = {"chave": "aurora-corrida", "pedido": pedido}
    def postar(_):
        return requisicao(url, "/creditos", corpo)
    with ThreadPoolExecutor(max_workers=2) as pool:
        respostas = list(pool.map(postar, range(2)))
    exigir(sorted(r[0] for r in respostas) == [200, 201] and
           respostas[0][1] == respostas[1][1], "repetições não convergiram")
    status, erro = requisicao(url, "/creditos",
                              {**corpo, "pedido": {**pedido, "minutos": 60}})
    efeitos = auditar(url, "corrida")
    exigir(status == 409 and len(efeitos) == 1 and efeitos[0]["digest"] == digest(pedido),
           "conflito alterou crédito")
    casos["concorrencia"] = {"respostas": respostas, "efeitos": efeitos}
    casos["colisao"] = {"status": status, "resposta": erro, "efeitos": efeitos}
    return casos


def campanha(saida, repeticoes):
    if repeticoes < 1:
        raise ValueError("use pelo menos uma repetição")
    saida.mkdir(parents=True, exist_ok=False)
    inicio = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="aurora-l11-") as tmp:
        base = Path(tmp)
        with servico(base) as (url, commit, liberar, ocultar):
            with (saida / "trajetorias.jsonl").open("x", encoding="utf8") as log:
                for rep in range(1, repeticoes + 1):
                    for janela in JANELAS:
                        for var in VARIANTES:
                            ident = f"{rep}-{janela}-{var}"
                            row = trajetoria(base / ident, url, commit, liberar, ident, var, janela)
                            log.write(json.dumps(row, ensure_ascii=False) + "\n")
                            log.flush()
            extras = controles(base, url, commit, liberar, ocultar)
    (saida / "controles.json").write_text(json.dumps(extras, ensure_ascii=False, indent=2), encoding="utf8")
    metadados = {"python": platform.python_version(), "sistema": platform.system(),
                 "dependencias": {n: version(n) for n in ("langgraph", "langgraph-checkpoint",
                                                          "langgraph-checkpoint-sqlite")},
                 "repeticoes": repeticoes, "trajetorias_com_queda": 6 * repeticoes,
                 "segundos": round(time.monotonic() - inicio, 2), "controles": list(extras)}
    (saida / "execucao.json").write_text(json.dumps(metadados, indent=2), encoding="utf8")
    print(json.dumps(metadados, indent=2))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("saida", type=Path)
    cli.add_argument("--repeticoes", type=int, default=2)
    args = cli.parse_args()
    campanha(args.saida, args.repeticoes)
