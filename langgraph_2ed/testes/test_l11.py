import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from l11.destino import aplicar, digest
from l11.grafo import finalizar, revisar
from l11.conferir import conferir


class Contrato(unittest.TestCase):
    def test_ordem_das_chaves_nao_cria_nova_revisao(self):
        self.assertEqual(digest({"a": 1, "b": 0}), digest({"b": 0, "a": 1}))

    def test_mudanca_de_minutos_altera_revisao(self):
        self.assertNotEqual(digest({"minutos": 30}), digest({"minutos": 60}))

    def test_recibo_so_confirma_a_chave_e_o_digest_esperados(self):
        for errado in ({"chave": "y"}, {"digest": "outro"}, {"recibo": ""}):
            res = {**{"chave": "x", "digest": "d", "recibo": "r"}, **errado}
            self.assertEqual(finalizar({"digest": "d"}, "x", res, "consulta"), {"fase":"conflito"})

    def test_receber_o_recibo_correspondente(self):
        res = finalizar({"digest": "d"}, "x", {"chave":"x", "digest":"d", "recibo":"r"}, "consulta")
        self.assertEqual(res, {"fase":"confirmada", "recibo":"r", "origem":"consulta"})

    def test_voto_de_outra_operacao_ou_outra_revisao(self):
        s = {"pedido": {}, "chave": "x", "digest": "d"}
        for voto in ({"autorizar":True, "chave":"y", "digest":"d"},
                     {"autorizar":True, "chave":"x", "digest":"d2"},
                     {"autorizar":1, "chave":"x", "digest":"d"},
                     {"autorizar":False, "chave":"x", "digest":"d"}):
            with patch("l11.grafo.interrupt", return_value=voto):
                self.assertEqual(revisar(s)["fase"], "recusada")

    def test_falha_de_insercao_desfaz_transacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "livro.sqlite"
            with closing(sqlite3.connect(db)) as con:
                con.execute("CREATE TABLE creditos (chave PRIMARY KEY, intencao, digest, minutos CHECK(minutos>0), recibo)")
            pedido = {"intencao":"i", "minutos":-1}
            with self.assertRaises(sqlite3.IntegrityError):
                aplicar(db, "x", pedido)
            self.assertEqual(aplicar(db, "x", {**pedido,"minutos":1})[0], 201)


class Trilha(unittest.TestCase):
    def test_matriz_completa(self):
        captura = Path(__file__).resolve().parents[1] / "output/l11_principal_v01"
        self.assertEqual(sum(conferir(captura).values()), 12)

    def test_captura_truncada_nao_passa(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            (pasta/"execucao.json").write_text(json.dumps({"repeticoes":2}))
            (pasta/"trajetorias.jsonl").write_text("")
            with self.assertRaisesRegex(ValueError, "matriz"):
                conferir(pasta)
