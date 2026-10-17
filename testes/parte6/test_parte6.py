"""Propriedades das fronteiras HTTP, persistência e efeito."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from exemplos.parte6.base import Problema, conexao, digest
from exemplos.parte6.cap21 import servir, chamar
from exemplos.parte6.cap22 import backup, restaurar
from exemplos.parte6.cap23 import julgar
from exemplos.parte6.ensaios import bancada, eventos_http, recusado
from exemplos.parte6 import laboratorios
from exemplos.parte6.servico import preparar, carregar


def pendente(app, t, tipo="operacao", chave="op"):
    id = app.criar(t["ana"], chave, {"tipo": tipo, "texto": "A-17 alta"})["id"]
    app.processar_um()
    return id, app.consultar(t["ana"], id)


class ApiTests(unittest.TestCase):
    def test_l21(self):
        r = laboratorios.l21()
        self.assertEqual(len(r["casos"]), 12)
        self.assertTrue(all(c["confere"] for c in r["casos"]))

    def test_validacao_na_fronteira_http(self):
        with bancada() as (app,t), servir(app, worker=False) as url:
            for corpo in ({"tipo":"eco","texto":True},
                          {"tipo":"eco","texto":"x","dono":"bia"},
                          {"tipo":"outro","texto":"x"}):
                self.assertEqual(chamar(url,t["ana"],"POST","/execucoes",corpo,"x")[0],422)
            self.assertEqual(chamar(url,t["ana"],"POST","/execucoes",{"tipo":"eco","texto":"x"})[0],422)

    def test_admissao_concorrente_preserva_id(self):
        with bancada() as (app,t):
            def enviar(_): return app.criar(t["ana"],"mesma",{"tipo":"eco","texto":"x"})
            with ThreadPoolExecutor(4) as pool: rows=list(pool.map(enviar,range(8)))
            self.assertEqual(len({r["id"] for r in rows}),1)
            self.assertEqual(sum(r["nova"] for r in rows),1)

    def test_mesma_chave_outro_usuario_e_outra_intencao(self):
        with bancada() as (app,t):
            r=[app.criar(t[n],"x",{"tipo":"eco","texto":"x"}) for n in ("ana","bia")]
            self.assertNotEqual(r[0]["id"],r[1]["id"])

    def test_decisoes_concorrentes_so_uma_e_admitida(self):
        with bancada() as (app,t):
            id,p=pendente(app,t,"revisao")
            def decidir(_): return recusado(lambda:app.decidir(t["bia"],id,{"aceitar":True,"digest":p["digest"]}))
            with ThreadPoolExecutor(2) as pool: r=list(pool.map(decidir,range(2)))
            self.assertCountEqual(r,["aceito","revisao_nao_pendente"])
            app.processar_um()
            self.assertEqual(app.fila.obter(id)["status"],"concluida")

    def test_cancelamento_nao_cancela_trabalho_reservado(self):
        with bancada() as (app,t):
            id=app.criar(t["ana"],"x",{"tipo":"eco","texto":"x"})["id"]
            app.fila.reservar()
            self.assertEqual(recusado(lambda:app.cancelar(t["ana"],id)),"cancelamento_nao_admitido")

    def test_expiracao_credencial_e_revogacao(self):
        with bancada() as (app,t):
            agora=app.dominio.relogio()
            curto=app.dominio.emitir("ana",ttl=1)
            app.dominio.relogio=lambda:agora+2
            self.assertEqual(recusado(lambda:app.dominio.autenticar(curto)),"credencial_invalida")
            app.dominio.revogar("bia")
            self.assertEqual(recusado(lambda:app.dominio.autenticar(t["bia"])),"negado")

    def test_sse_pagina_mais_de_cem_eventos_sem_perda(self):
        with bancada() as (app,t):
            id=app.criar(t["ana"],"x",{"tipo":"eco","texto":"segredo"})["id"]
            app.processar_um()
            with conexao(app.fila.arquivo,True) as db:
                for _ in range(205):app.fila.evento_em(db,id,"etapa",{"nome":"teste"})
                esperado=db.execute("SELECT count(*) FROM eventos WHERE execucao=?",(id,)).fetchone()[0]
            with servir(app,worker=False) as url:r=eventos_http(url,t["ana"],id)
            self.assertEqual(r.count("id: "),esperado)
            self.assertNotIn("segredo",r)

    def test_saude_nao_equivale_prontidao(self):
        with bancada() as (app,t), servir(app,worker=False) as url:
            self.assertEqual(chamar(url,"","GET","/saude")[0],200)
            self.assertEqual(chamar(url,"","GET","/pronto")[0],503)


class OperacaoTests(unittest.TestCase):
    def test_l24(self):
        r=laboratorios.l24()
        self.assertEqual(len(r["casos"]),12)
        self.assertTrue(all(c["confere"] for c in r["casos"]))

    def test_excecao_apos_commit_exige_conciliacao(self):
        with bancada() as (app,t):
            id,p=pendente(app,t)
            app.decidir(t["bia"],id,{"aceitar":True,"digest":p["digest"]})
            aplicar=app.dominio.aplicar
            def perder(*a):
                aplicar(*a)
                raise TimeoutError("resposta perdida")
            with patch.object(app.dominio,"aplicar",side_effect=perder):app.processar_um()
            self.assertEqual(app.fila.obter(id)["status"],"desconhecida")
            self.assertEqual(app.dominio.efeitos(),1)
            self.assertEqual(app.conciliar(t["bia"],id)["status"],"concluida")

    def test_marco_sem_efeito_nao_autoriza_reenvio(self):
        with bancada() as (app,t):
            id,p=pendente(app,t)
            app.decidir(t["bia"],id,{"aceitar":True,"digest":p["digest"]})
            app.fila.enviado(id,p["proposta"])
            app.processar_um()
            self.assertEqual(app.fila.obter(id)["status"],"desconhecida")
            self.assertEqual(app.dominio.efeitos(),0)

    def test_recurso_alterado_recusa_efeito(self):
        with bancada() as (app,t):
            id,p=pendente(app,t)
            revisao=app.dominio.aprovar(t["bia"],"ana",p["proposta"])
            with conexao(app.dominio.arquivo,True) as db:db.execute("UPDATE recursos SET revisao=99 WHERE id='A-17'")
            self.assertEqual(recusado(lambda:app.dominio.aplicar(t["bot"],"ana",p["proposta"],revisao)),"recurso_alterado")
            self.assertEqual(app.dominio.efeitos(),0)

    def test_executor_revogado_recusa_efeito(self):
        with bancada() as (app,t):
            id,p=pendente(app,t)
            rev=app.dominio.aprovar(t["bia"],"ana",p["proposta"])
            app.dominio.revogar("bot")
            self.assertEqual(recusado(lambda:app.dominio.aplicar(t["bot"],"ana",p["proposta"],rev)),"negado")
            self.assertEqual(app.dominio.efeitos(),0)

    def test_recibo_historico_nao_depende_de_revisao_ainda_valida(self):
        with bancada() as (app,t):
            id,p=pendente(app,t)
            rev=app.dominio.aprovar(t["bia"],"ana",p["proposta"],ttl=1)
            r=app.dominio.aplicar(t["bot"],"ana",p["proposta"],rev)
            agora=app.dominio.relogio();app.dominio.relogio=lambda:agora+2
            self.assertEqual(app.dominio.consultar_recibo(t["bot"],"ana",p["proposta"]),r)
            self.assertEqual(recusado(lambda:app.dominio.aplicar(t["bot"],"ana",p["proposta"],rev)),"revisao_invalida")

    def test_prazo_da_revisao_estrito(self):
        with bancada() as (app,t):
            for ttl in (True,0,-1,86401):
                self.assertEqual(recusado(lambda:app.dominio.aprovar(t["bia"],"ana",{},ttl)),"prazo_invalido")


class PersistenciaTests(unittest.TestCase):
    def test_l22(self):
        r=laboratorios.l22()
        self.assertEqual(len(r["casos"]),12)
        self.assertTrue(all(c["confere"] for c in r["casos"]))

    def test_copia_isolada_bloqueia_operacao(self):
        with TemporaryDirectory() as raiz:
            pasta=Path(raiz)/"origem";preparar(pasta);app=carregar(pasta)
            t=json.loads((pasta/"credenciais-locais.json").read_text())
            id,p=pendente(app,t)
            copia,rest=Path(raiz)/"copia",Path(raiz)/"rest"
            backup(pasta,copia);restaurar(copia,rest)
            nova=carregar(rest,pasta/"credenciais-locais.json")
            nova.decidir(t["bia"],id,{"aceitar":True,"digest":p["digest"]})
            nova.processar_um()
            self.assertEqual(nova.fila.obter(id)["status"],"falhou")
            self.assertEqual(nova.dominio.efeitos(),0)
            self.assertFalse((copia/"credenciais-locais.json").exists())

    def test_backup_incompleto_recusado(self):
        with bancada() as (app,t):
            self.assertEqual(recusado(lambda:backup(app.pasta,app.pasta/"copia")),"bancos_incompletos")

    def test_restauracao_versao_divergente(self):
        with TemporaryDirectory() as raiz:
            pasta=Path(raiz);(pasta/"manifesto.json").write_text(json.dumps({"versao":"v0","arquivos":{}}))
            self.assertEqual(recusado(lambda:restaurar(pasta,pasta/"nova")),"backup_incompativel")
            self.assertFalse((pasta/"nova").exists())


class ConhecimentoTests(unittest.TestCase):
    def test_l23(self):
        r=laboratorios.l23()
        self.assertEqual(len(r["casos"]),12)
        self.assertTrue(all(c["confere"] for c in r["casos"]))

    def test_preferencia_expira_sem_apagar_registro(self):
        with bancada() as (app,t):
            p=app.dominio.autenticar(t["ana"]);c=app.conhecimento
            c.relogio=lambda:100;c.preferir(p,{"formato":"detalhado","ttl":1})
            self.assertEqual(c.formato(p),"detalhado")
            c.relogio=lambda:101;self.assertEqual(c.formato(p),"curto")
            with conexao(c.arquivo) as db:self.assertEqual(db.execute("SELECT count(*) FROM preferencias").fetchone()[0],1)

    def test_cache_separado_por_usuario(self):
        with bancada() as (app,t):
            saidas=[]
            for nome in ("ana","ana","bia","caio"):
                p=app.dominio.autenticar(t[nome]);c=app.conhecimento
                v,d=c.recuperar(p,"VPN");saidas.append(c.responder(p,"VPN",v,d,"curto"))
            self.assertEqual([s["cache"] for s in saidas],[False,True,False,False])
            self.assertNotIn("CANARIO_BOREAL",saidas[0]["resposta"])
            self.assertIn("CANARIO_BOREAL",saidas[-1]["resposta"])

    def test_corpus_id_nao_pode_mudar_de_conteudo(self):
        with bancada() as (app,t):
            with conexao(app.conhecimento.arquivo,True) as db:db.execute("UPDATE corpus SET digest='alterado'")
            with self.assertRaisesRegex(ValueError,"versao_imutavel"):app.conhecimento.publicar("corpus-1")

    def test_contexto_preserva_documento_inteiro(self):
        with bancada() as (app,t):
            p=app.dominio.autenticar(t["ana"]);c=app.conhecimento
            _,d=c.recuperar(p,"VPN");c.limite=len(d[0]["texto"])-1
            self.assertEqual(c.recuperar(p,"VPN")[1],[])

    def test_oraculo_detecta_texto_revisao_e_trecho_alterados(self):
        caminho=Path("exemplos/parte6/fixtures/aceitacao.json")
        c=json.loads(caminho.read_text(encoding="utf8"))["aceitacao"][0]
        r={"situacao":"concluida","corpus":"corpus-1","absteve":False,
           "resposta":c["resposta"],"fontes":[{"id":"A-VPN","revisao":1,"trecho":c["resposta"]}]}
        self.assertTrue(julgar(r,c))
        for campo in ("resposta","revisao","trecho"):
            m=deepcopy(r)
            if campo=="resposta":m[campo]="conteúdo errado"
            else:m["fontes"][0][campo]="alterado"
            self.assertFalse(julgar(m,c))


if __name__ == "__main__":unittest.main()
