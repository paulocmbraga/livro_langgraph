"""L21–L24: HTTP, reinício, restauração e aceitação dos projetos."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from .base import conexao
from .cap21 import Aplicacao, servir, chamar, aguardar
from .cap22 import backup, restaurar, medir_carga
from .cap23 import avaliar
from .ensaios import (aprovar, bancada, caso, desconectar, eventos_http,
                     processo_http, queda_apos_efeito, recusado, solicitar)
from .servico import preparar, carregar


def l21():
    with bancada(atraso=.15) as (app, t), servir(app) as url:
        pedido = {"tipo": "revisao", "texto": "Conferir proposta"}
        status, r = chamar(url, t["ana"], "POST", "/execucoes", pedido, "primeira")
        id = r["id"]
        primeiro = desconectar(url, t["ana"], id)
        cursor = int(re.search(r"id: (\d+)", primeiro)[1])
        pausa = aguardar(url, t["ana"], id, {"revisao"})
        repetida = chamar(url, t["ana"], "POST", "/execucoes", pedido, "primeira")
        conflito = chamar(url, t["ana"], "POST", "/execucoes",
                           {**pedido, "texto": "outro"}, "primeira")[0]
        cruzado = chamar(url, t["caio"], "GET", "/execucoes/"+id)[0]
        invalida = chamar(url, "ana", "GET", "/execucoes/"+id)[0]
        digest_errado = chamar(url, t["bia"], "POST", f"/execucoes/{id}/decisao",
                               {"aceitar": True, "digest": "0"*64})[0]
        sem_papel = chamar(url, t["ana"], "POST", f"/execucoes/{id}/decisao",
                           {"aceitar": True, "digest": pausa["digest"]})[0]
        aprovar(url, t, id, pausa)
        fim = aguardar(url, t["ana"], id, {"concluida"})
        retomados = eventos_http(url, t["ana"], id, cursor)
        ids = [int(n) for n in re.findall(r"^id: (\d+)$", retomados, re.M)]
        outro, _ = solicitar(url, t, "cancelar", "revisao", "Segunda proposta")
        cancelada = chamar(url, t["ana"], "POST", f"/execucoes/{outro}/cancelar", {})[1]
        casos = [caso("admissao_http", status, 202),
            caso("repeticao_mesma_intencao", [repetida[0], repetida[1]["id"] == id], [200, True]),
            caso("chave_com_outro_conteudo", conflito, 409),
            caso("acesso_cruzado", cruzado, 404),
            caso("nome_nao_e_credencial", invalida, 401),
            caso("primeiro_evento_recebido", "event: admitida" in primeiro, True),
            caso("desconexao_nao_cancela", pausa["status"], "revisao"),
            caso("digest_divergente", digest_errado, 409),
            caso("leitor_nao_aprova", sem_papel, 403),
            caso("revisao_concluida", [fim["status"], app.dominio.efeitos()], ["concluida", 0]),
            caso("cancelamento_pendente", cancelada["status"], "cancelada"),
            caso("reconexao_projetada", [bool(ids) and min(ids)>cursor,
                 all(x not in retomados for x in [pedido["texto"], *t.values()])], [True, True])]
        return {"capitulo": 21, "casos": casos,
                "politica_desconexao": "worker_independente", "http_real": True}


def l22():
    with TemporaryDirectory() as raiz:
        pasta = Path(raiz)/"servico"; preparar(pasta)
        tokens = json.loads((pasta/"credenciais-locais.json").read_text())
        with processo_http(pasta) as url:
            id, pausa = solicitar(url, tokens, "reinicio", "revisao", "Trabalho pendente")
            bloqueio = recusado(lambda: backup(pasta, Path(raiz)/"proibida"))
        m = backup(pasta, Path(raiz)/"copia")
        rest = restaurar(Path(raiz)/"copia", Path(raiz)/"restaurada")
        with processo_http(pasta) as url:
            retomada = chamar(url, tokens["ana"], "GET", "/execucoes/"+id)[1]
            aprovar(url, tokens, id, retomada)
            final = aguardar(url, tokens["ana"], id, {"concluida"})
            carga = medir_carga(url, tokens["ana"])
        copia = Aplicacao(Path(raiz)/"restaurada", executor_token=tokens["bot"])
        with servir(copia) as url:
            restaurada = chamar(url, tokens["ana"], "GET", "/execucoes/"+id)[1]
            aprovar(url, tokens, id, restaurada)
            final_copia = aguardar(url, tokens["ana"], id, {"concluida"})
        with bancada(limite=1) as (limitada, t), servir(limitada, worker=False) as url:
            p = {"tipo": "eco", "texto": "um"}
            chamar(url, t["ana"], "POST", "/execucoes", p, "um")
            excesso = chamar(url, t["ana"], "POST", "/execucoes", p, "dois")[0]
            repetida = chamar(url, t["ana"], "POST", "/execucoes", p, "um")[0]
        antiga = carregar(pasta)
        novo = antiga.criar(tokens["ana"], "versao", {"tipo":"eco", "texto":"antigo"})["id"]
        with conexao(antiga.fila.arquivo, True) as db:
            db.execute("UPDATE execucoes SET versao='v0' WHERE id=?", (novo,))
        antiga.processar_um()
        alterado = Path(raiz)/"copia"/"servico.sqlite"
        with alterado.open("ab") as f: f.write(b"alteracao")
        hash_negado = recusado(lambda: restaurar(Path(raiz)/"copia", Path(raiz)/"outra"))
        casos = [caso("reinicio_conserva_revisao", [retomada["status"], retomada["digest"]==pausa["digest"]], ["revisao", True]),
            caso("retomada_apos_reinicio", final["status"], "concluida"),
            caso("backup_quatro_bancos", len(m["arquivos"]), 4),
            caso("restauracao_isolada", rest["isolado"], True),
            caso("copia_conserva_pendencia", restaurada["status"], "revisao"),
            caso("copia_retoma_grafo", final_copia["status"], "concluida"),
            caso("carga_cardinalidade", [carga["oferecidas"],carga["concluidas"],carga["rejeitadas"]], [12,12,0]),
            caso("medidas_observadas_finitas", all(math.isfinite(carga[k]) and carga[k]>0 for k in ("duracao_s","vazao_por_s","p95_concluidas_ms")), True),
            caso("backpressure_sem_nova_intencao", [excesso,repetida], [429,200]),
            caso("backup_recusa_servico_ativo", bloqueio, "diretorio_em_uso"),
            caso("versao_antiga_bloqueada", antiga.fila.obter(novo)["status"], "bloqueada"),
            caso("copia_alterada_recusada", hash_negado, "backup_alterado")]
        return {"capitulo":22,"casos":casos,"carga":carga,
                "postgres":{"executado":False,"motivo":"adaptador ausente e daemon Docker indisponível na entrega"}}


def l23():
    with bancada() as (app, t), servir(app) as url:
        avaliacao = avaliar(url, t)
        casos = [caso("aceitacao_"+r["caso"], r["correta"], True) for r in avaliacao["casos"]]
        def consulta(chave, conta="ana"):
            _, r = chamar(url,t[conta],"POST","/execucoes",{"tipo":"conhecimento","texto":"Qual cliente VPN devo usar?"},chave)
            return r["id"], aguardar(url,t[conta],r["id"],{"concluida"})["resultado"]
        _, hit = consulta("cache")
        app.conhecimento.publicar("corpus-2")
        _, nova = consulta("nova")
        chamar(url,t["ana"],"PUT","/preferencias",{"formato":"detalhado","ttl":60})
        _, formato = consulta("preferencia")
        _, outra = consulta("outra-conta", "bia")
        app.conhecimento.limite = 1
        id, pequena = consulta("pequena")
        sem_canario = all("CANARIO_BOREAL_23" not in json.dumps(r["saida"])
                          for r in avaliacao["casos"] if r["caso"] != "T5")
        app.dominio.revogar("ana")
        negado = chamar(url,t["ana"],"GET","/execucoes/"+id)[0]
        casos.extend([caso("cache_mesma_base", hit["cache"], True),
            caso("base_atualizada", [nova["corpus"],nova["cache"],nova["fontes"][0]["revisao"]], ["corpus-2",False,2]),
            caso("memoria_com_escopo", [formato["formato"],outra["formato"]], ["detalhado","curto"]),
            caso("contexto_insuficiente", pequena["absteve"], True),
            caso("fonte_de_outra_org_ausente", sem_canario, True),
            caso("revogacao_impede_consulta", negado, 403)])
        return {"capitulo":23,"casos":casos,"avaliacao":avaliacao}


def l24():
    casos=[]
    with bancada() as (app,t), servir(app) as url:
        id, pausa = solicitar(url,t)
        aprovar(url,t,id,pausa)
        final = aguardar(url,t["ana"],id,{"concluida"})
        _, repetida = chamar(url,t["ana"],"POST","/execucoes",{"tipo":"operacao","texto":"A-17 alta"},"pedido")
        casos.extend([caso("efeito_confirmado",[final["status"],app.dominio.efeitos()],["concluida",1]),
                      caso("repeticao_mesma_operacao",repetida["id"]==id,True)])
        outro,p = solicitar(url,t,"rejeitar")
        aprovar(url,t,outro,p,False)
        rejeitada = aguardar(url,t["ana"],outro,{"rejeitada"})
        casos.append(caso("rejeicao_sem_novo_efeito",[rejeitada["status"],app.dominio.efeitos()],["rejeitada",1]))
    with bancada() as (app,t):
        r=app.dominio.ler_recurso("ana","A-17")
        p={"execucao":"concorrente","versao":"aurora-6-v1","acao":{"recurso":"A-17","prioridade":"alta","revisao":r["revisao"]}}
        revisao=app.dominio.aprovar(t["bia"],"ana",p)
        import threading
        barreira=threading.Barrier(2)
        def aplicar(_):
            barreira.wait(timeout=5)
            return app.dominio.aplicar(t["bot"],"ana",p,revisao)
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados=list(pool.map(aplicar,range(2)))
        casos.append(caso("concorrencia_no_destino",[resultados[0]==resultados[1],app.dominio.efeitos()],[True,1]))
    for falha in ("conteudo","vencida","revogada","papel"):
        with bancada() as (app,t):
            p={"execucao":"negada","versao":"aurora-6-v1","acao":{"recurso":"A-17","prioridade":"alta","revisao":3}}
            rev=app.dominio.aprovar(t["bia"],"ana",p)
            if falha=="conteudo": p["acao"]["prioridade"]="baixa"
            if falha=="vencida":
                with conexao(app.dominio.arquivo,True) as db: db.execute("UPDATE revisoes SET vence=0")
            if falha=="revogada": app.dominio.revogar("bia")
            token=t["ana"] if falha=="papel" else t["bot"]
            erro=recusado(lambda:app.dominio.aplicar(token,"ana",p,rev))
            casos.append(caso("recusa_"+falha,[erro!="aceito",app.dominio.efeitos()],[True,0]))
    with bancada(falha_destino="perder_resposta",consulta_disponivel=False) as (app,t), servir(app) as url:
        id,p=solicitar(url,t);aprovar(url,t,id,p)
        u=aguardar(url,t["ana"],id,{"desconhecida"})
        _,lista=chamar(url,t["bia"],"GET","/pendencias")
        _,continua=chamar(url,t["bia"],"POST",f"/execucoes/{id}/conciliar",{})
        casos.append(caso("confirmacao_ausente_encaminhada",[u["status"],len(lista["execucoes"]),continua["status"]],["desconhecida",1,"desconhecida"]))
        app.consulta_disponivel=True
        _,fim=chamar(url,t["bia"],"POST",f"/execucoes/{id}/conciliar",{})
        casos.append(caso("conciliar_sem_reaplicar",[fim["status"],app.dominio.efeitos()],["concluida",1]))
        tipos=[e["tipo"] for e in app.fila.eventos(id)]
        casos.append(caso("historico_preserva_incerteza",["desconhecida" in tipos,tipos[-1]],[True,"concluida"]))
    queda=queda_apos_efeito()
    casos.append(caso("reinicio_apos_commit",queda,{"retorno":24,"status_antes":"executando","efeitos_antes":1,"status_final":"concluida","efeitos_depois":1}))
    return {"capitulo":24,"casos":casos}


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--capitulo",type=int,required=True,choices=range(21,25))
    a=p.parse_args();r={21:l21,22:l22,23:l23,24:l24}[a.capitulo]()
    print(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False))
    if not all(c["confere"] for c in r["casos"]): raise SystemExit(1)
