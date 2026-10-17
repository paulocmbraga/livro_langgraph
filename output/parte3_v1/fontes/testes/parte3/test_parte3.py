from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from pydantic import ValidationError
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from exemplos.parte3 import cap09, cap10, cap11, cap12, laboratorios, solucoes
from exemplos.parte3.destino import (
    Destino, Diario, digest, RespostaPerdida, Colisao, RevisaoDivergente)


class TestContratos(unittest.TestCase):
    def test_operacao_nao_e_espaco(self):
        with self.assertRaises(ValidationError):
            cap10.Proposta.model_validate({**cap10.proposta_padrao(), "operacao":" "})

    def test_proposta_nao_muda_organizacao(self):
        with self.assertRaises(ValidationError):
            cap10.Proposta.model_validate({**cap10.proposta_padrao(), "organizacao":"outra"})

    def test_aprovacao_booleana_estrita(self):
        with self.assertRaises(ValidationError):
            cap10.Decisao.model_validate({"aceitar":"sim","operacao":"a","digest":"x"})

    def test_id_estavel_e_escopado(self):
        chave = solucoes.identidade_operacao("aurora","A-17","pedido-1")
        self.assertEqual(chave, solucoes.identidade_operacao("aurora","A-17","pedido-1"))
        self.assertNotEqual(chave, solucoes.identidade_operacao("outra","A-17","pedido-1"))
        self.assertNotEqual(chave, solucoes.identidade_operacao("aurora","A-17","pedido-2"))

    def test_digest_independe_de_ordem_das_chaves(self):
        self.assertEqual(digest({"a":1,"b":2}),digest({"b":2,"a":1}))

    def test_revisao_strict(self):
        for valor in (True,"3",0,-1):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                cap12.PropostaV2.model_validate(
                    {**cap10.proposta_padrao(),"expected_revision":valor})

    def test_versao_booleana_nao_e_v1(self):
        e=cap12.fixture_v1()
        e["versao"]=True
        with self.assertRaises(cap12.Incompativel):
            cap12.validar_estado(e,1)

    def test_v2_nao_inventa_revisao(self):
        e=cap12.fixture_v1()
        e["versao"]=2
        with self.assertRaises(ValidationError):
            cap12.validar_estado(e,2)


class TestDestino(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d=Destino(self.tmp.name)
        self.p=cap10.proposta_padrao()

    def test_rollback_remove_efeito_e_recibo(self):
        with self.assertRaises(RespostaPerdida):
            self.d.aplicar(self.p,falha="antes_commit")
        self.assertEqual(self.d.ler()["revisao"],3)
        self.assertEqual(self.d.contadores()["efeitos"],0)
        self.assertEqual(self.d.consultar(self.p["operacao"],digest(self.p))["situacao"],"ausente")

    def test_resposta_perdida_preserva_efeito_e_recibo(self):
        with self.assertRaises(RespostaPerdida):
            self.d.aplicar(self.p,falha="depois_commit")
        self.assertEqual(self.d.ler()["revisao"],4)
        self.assertEqual(self.d.consultar(self.p["operacao"],digest(self.p))["situacao"],"confirmed")

    def test_concorrencia_real_deduplica_na_transacao(self):
        barreira=Barrier(2)
        def worker(_):
            d=Destino(self.tmp.name)
            barreira.wait(timeout=5)
            return d.aplicar(self.p)
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados=list(pool.map(worker,range(2)))
        self.assertEqual(resultados[0],resultados[1])
        self.assertEqual(self.d.contadores()["efeitos"],1)
        self.assertEqual(self.d.contadores()["despachos"],2)

    def test_chave_colide_sem_segundo_efeito(self):
        self.d.aplicar(self.p)
        with self.assertRaises(Colisao):
            self.d.aplicar({**self.p,"novo_status":"aberto"})
        self.assertEqual(self.d.contadores()["efeitos"],1)

    def test_deduplicacao_antecede_precondicao(self):
        p={**self.p,"expected_revision":3}
        a=self.d.aplicar(p)
        b=self.d.aplicar(p)
        self.assertEqual(a,b)
        self.assertEqual(self.d.ler()["revisao"],4)

    def test_precondicao_nao_altera_recurso(self):
        with self.assertRaises(RevisaoDivergente):
            self.d.aplicar({**self.p,"expected_revision":2})
        self.assertEqual(self.d.ler()["revisao"],3)

    def test_consulta_nao_aceita_digest_de_outro_conteudo(self):
        self.d.aplicar(self.p)
        with self.assertRaises(Colisao):
            self.d.consultar("op-001","errado")

    def test_intencao_conflitante(self):
        diario=Diario(self.tmp.name)
        diario.registrar(self.p)
        with self.assertRaises(Colisao):
            diario.registrar({**self.p,"novo_status":"aberto"})

    def test_confirmado_nao_regride_por_indisponibilidade(self):
        diario=Diario(self.tmp.name)
        diario.registrar(self.p)
        recibo=self.d.aplicar(self.p)
        diario.marcar("op-001","confirmed",recibo)
        ctx=cap10.Contexto(self.d,diario,consulta_disponivel=False)
        self.assertEqual(cap10.conciliar(ctx,self.p)["recibo"],recibo)
        self.assertEqual(self.d.contadores()["consultas"],0)

    def test_compensacao_tem_identidade_propria_e_repete_com_segurança(self):
        recibo=self.d.aplicar(self.p)
        a=cap11.compensar(self.d,self.p,recibo)
        b=cap11.compensar(self.d,self.p,recibo)
        self.assertEqual(a,b)
        self.assertNotEqual(a["operacao"],recibo["operacao"])
        self.assertEqual(self.d.contadores()["efeitos"],2)


class TestGrafos(unittest.TestCase):
    def test_alterar_proposta_apos_aprovar_exige_novo_vinculo(self):
        with laboratorios.bancada12() as (_,d,c,ctx,gs,cfg):
            snapshot=gs[1].get_state(cfg)
            p={**snapshot.values["proposta"],"novo_status":"aberto"}
            gs[1].update_state(cfg,{"proposta":p},as_node="revisar")
            r=c.invocar(gs,None,cfg,ctx)
            self.assertEqual(r["situacao"],"sem_aprovacao")
            self.assertEqual(d.contadores()["efeitos"],0)

    def test_migracao_invalida_restaura_catalogo(self):
        with laboratorios.bancada12() as (_,d,c,ctx,gs,cfg):
            c.cadastrar("ocupada",2)
            with self.assertRaises(sqlite3.IntegrityError):
                c.migrar(gs[1],cfg,d,"ocupada","op-nova")
            self.assertEqual(c.invocar(gs,None,cfg,ctx)["situacao"],"confirmed")

    def test_aprovacao_antiga_nao_serve_na_nova_thread(self):
        with laboratorios.bancada12() as (_,d,c,ctx,gs,cfg):
            antiga=gs[1].get_state(cfg).values["proposta"]
            nova=c.migrar(gs[1],cfg,d,"nova","op-nova")
            nc=cap09.configuracao("nova")
            c.invocar(gs,nova,nc,ctx)
            c.invocar(gs,cap10.aprovar(antiga),nc,ctx)
            final=c.invocar(gs,None,nc,ctx)
            self.assertEqual(final["situacao"],"sem_aprovacao")
            self.assertEqual(d.contadores()["efeitos"],0)

    def test_catalogo_desconhecido_nao_invoca(self):
        with laboratorios.bancada12() as (_,d,c,ctx,gs,cfg):
            with self.assertRaises(cap12.Incompativel):
                c.invocar(gs,None,cap09.configuracao("ausente"),ctx)
            self.assertEqual(d.contadores()["efeitos"],0)

    def test_posse_expirada_nao_conclui_mesmo_sem_novo_worker(self):
        with TemporaryDirectory() as p:
            fila=cap11.Fila(Path(p)/"fila.sqlite")
            geracao=fila.adquirir("op","a",0,ttl=2)
            self.assertFalse(fila.concluir("op","a",geracao,2))

    def test_posses_concorrentes_tem_um_vencedor(self):
        with TemporaryDirectory() as p:
            arquivo=Path(p)/"fila.sqlite"
            cap11.Fila(arquivo)
            barreira=Barrier(2)
            def worker(nome):
                f=cap11.Fila(arquivo)
                barreira.wait(timeout=5)
                return f.adquirir("op",nome,0)
            with ThreadPoolExecutor(max_workers=2) as pool:
                resultados=list(pool.map(worker,["a","b"]))
            self.assertEqual(sum(r is not None for r in resultados),1)

    def test_historia_nao_autoriza_por_identificador(self):
        with TemporaryDirectory() as p:
            g=cap09.criar_grafo(InMemorySaver())
            cfg=cap09.configuracao("identificador-conhecido")
            g.invoke({"chamado_id":"A-17"},cfg,context=cap09.Contexto(Destino(p)))
            # Leitura direta do runtime não consulta identidade do chamador.
            self.assertEqual(g.get_state(cfg).values["chamado_id"],"A-17")


class TestSolucoes(unittest.TestCase):
    def test_unknown_nao_inventa_ausencia(self):
        self.assertEqual(solucoes.decidir_unknown("unknown",True,True,0,3),"consultar_depois")
        self.assertEqual(solucoes.decidir_unknown("ausente",True,False,0,3),"consultar_depois")

    def test_unknown_limita_trabalho_e_preserva_confirmado(self):
        self.assertEqual(solucoes.decidir_unknown("unknown",True,True,3,3),"encaminhar")
        self.assertEqual(solucoes.decidir_unknown("confirmed",True,True,3,3),"concluir")

    def test_reenvio_exige_contrato_e_identidade(self):
        self.assertEqual(solucoes.decidir_unknown("ausente",True,True,0,3),"reenviar_mesma_identidade")
        self.assertEqual(solucoes.decidir_unknown("ausente",False,True,0,3),"consultar_depois")

    def test_backoff_conta_intervalos_nao_tentativas(self):
        self.assertEqual(solucoes.atrasos(1),[])
        self.assertEqual(solucoes.atrasos(5,1,3),[1,2,3,3])
        with self.assertRaises(ValueError):
            solucoes.atrasos(True)

    def test_metadado_nao_reescreve_proposta(self):
        e=cap12.fixture_v1()
        e["aprovacao"]={"digest":digest(e["proposta"])}
        antes=deepcopy(e)
        novo=solucoes.acrescentar_rotulo(e,"Prioritário")
        self.assertEqual(e,antes)
        self.assertTrue(solucoes.aprovacao_vinculada(novo))
        novo["proposta"]["novo_status"]="aberto"
        self.assertFalse(solucoes.aprovacao_vinculada(novo))
        self.assertEqual(e,antes)


class TestMatrizes(unittest.TestCase):
    def test_l09(self):
        self.assertEqual(len(laboratorios.executar(9)["casos"]),13)

    def test_l10(self):
        self.assertEqual(len(laboratorios.executar(10)["casos"]),12)

    def test_l11(self):
        self.assertEqual(len(laboratorios.executar(11)["casos"]),12)

    def test_l12(self):
        self.assertEqual(len(laboratorios.executar(12)["casos"]),12)


if __name__=="__main__":
    unittest.main()
