import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from pydantic import ValidationError
from langgraph.errors import InvalidUpdateError, GraphRecursionError
from exemplos.apendices import composicao as b, contratos as c, diagnostico as d
from exemplos.apendices.ambiente import diagnostico


class Composicao(unittest.TestCase):
    def test_retomada_em_processos_novos(self):
        dados = b.comparar()
        self.assertEqual(dados["graph"], dados["functional"])
        for valor in dados.values():
            self.assertEqual(valor, {
                "inicio": {"status": "revisao", "proposta": "AURORA"},
                "fim": {"status": "concluida", "proposta": "AURORA", "aprovado": True},
                "preparos": 1, "reentradas_corpo": 2})

    def test_rejeicao(self):
        for valor in b.comparar(False).values():
            self.assertFalse(valor["fim"]["aprovado"])
            self.assertEqual(valor["preparos"], 1)

    def test_decisao_invalida(self):
        for estilo in ("graph", "functional"):
            with self.subTest(estilo=estilo), TemporaryDirectory() as tmp:
                b.passo(Path(tmp), estilo, "iniciar")
                with self.assertRaisesRegex(ValueError, "booleana"):
                    b.passo(Path(tmp), estilo, "retomar", "sim")

    def test_outra_thread_nao_tem_pendencia(self):
        for estilo in ("graph", "functional"):
            with self.subTest(estilo=estilo), TemporaryDirectory() as tmp:
                pasta = Path(tmp)
                b.passo(pasta, estilo, "iniciar")
                with b.SqliteSaver.from_conn_string(str(pasta/"estado.db")) as saver:
                    construir = b.construir_graph if estilo == "graph" else b.construir_functional
                    fluxo = construir(saver, pasta)
                    self.assertEqual(fluxo.get_state({"configurable": {"thread_id": "outra"}}).interrupts, ())


class Contratos(unittest.TestCase):
    def setUp(self):
        self.dados = dict(operacao="op-1", organizacao="aurora", recurso="A-17",
                          revisao=3, prioridade="alta")
        self.proposta = c.Proposta(**self.dados)

    def test_aprovacao_vincula_conteudo(self):
        h = c.digest(self.proposta)
        self.assertTrue(c.conferir_aprovacao(self.proposta, h, 20., 19.))
        alterada = c.Proposta(**dict(self.dados, prioridade="baixa"))
        with self.assertRaisesRegex(ValueError, "divergente"):
            c.conferir_aprovacao(alterada, h, 20., 19.)

    def test_expiracao_inclusiva(self):
        with self.assertRaisesRegex(ValueError, "expirada"):
            c.conferir_aprovacao(self.proposta, c.digest(self.proposta), 20., 20.)

    def test_sem_coercao_ou_campo_extra(self):
        for extras in ({"revisao": "3"}, {"revisao": True}, {"admin": True}):
            with self.subTest(extras=extras), self.assertRaises(ValidationError):
                c.Proposta(**dict(self.dados, **extras))

    def test_digest_independe_ordem_chaves(self):
        self.assertEqual(c.digest(self.proposta), c.digest(c.Proposta(**dict(reversed(list(self.dados.items()))))))

    def test_digest_muda_com_escopo_e_revisao(self):
        for alteracao in ({"organizacao": "outra"}, {"revisao": 4}, {"operacao": "op-2"}):
            self.assertNotEqual(c.digest(self.proposta), c.digest(c.Proposta(**dict(self.dados, **alteracao))))

    def test_nan_nao_aprova(self):
        with self.assertRaisesRegex(ValueError, "invalido"):
            c.conferir_aprovacao(self.proposta, c.digest(self.proposta), float("nan"), 1.)

    def test_denominadores(self):
        r = c.demonstrar()
        self.assertEqual((r["pedidos"], r["concluidas"], r["taxa_conclusao"]), (5, 2, .4))
        self.assertEqual((r["falhas"], r["desconhecidas"], r["recusadas"]), (1, 1, 1))
        self.assertEqual((r["p95_concluidas_ms"], r["conclusoes_por_s"]), (300., 1.))
        self.assertAlmostEqual(r["custo_por_conclusao_usd"], .05)

    def test_sem_conclusao_nao_e_zero(self):
        r = c.resumir([c.Amostra(pedido="a", status="falhou", latencia_ms=1., custo_usd=.01)], 1.)
        self.assertIsNone(r["p95_concluidas_ms"])
        self.assertIsNone(r["custo_por_conclusao_usd"])
        self.assertEqual(r["taxa_conclusao"], 0.)

    def test_coorte_vazia(self):
        self.assertIsNone(c.resumir([], 1.)["taxa_conclusao"])

    def test_duplicata_recusada(self):
        a = c.Amostra(pedido="a", status="falhou", latencia_ms=1., custo_usd=0.)
        with self.assertRaisesRegex(ValueError, "duplicado"):
            c.resumir([a, a], 1.)

    def test_janela_e_numeros_finitos(self):
        for janela in (0, -1, float("nan"), float("inf")):
            with self.subTest(janela=janela), self.assertRaises(ValueError):
                c.resumir([], janela)
        with self.assertRaises(ValidationError):
            c.Amostra(pedido="a", status="falhou", latencia_ms=float("nan"), custo_usd=0.)


class Diagnostico(unittest.TestCase):
    def test_conflito(self):
        with self.assertRaises(InvalidUpdateError):
            d.paralelo(False)

    def test_agregacao(self):
        self.assertEqual(sorted(d.paralelo(True)["valores"]), ["a", "b"])

    def test_limite(self):
        with self.assertRaises(GraphRecursionError):
            d.ciclo(False)

    def test_progresso(self):
        self.assertEqual(d.ciclo(True)["passos"], 3)

    def test_ambiente(self):
        r = diagnostico()
        self.assertTrue(r["na_raiz"])
        self.assertEqual(r["pacotes"]["langgraph"], "1.2.15")


if __name__ == "__main__":
    unittest.main()
