"""Regressões para conferência do ambiente atual, inclusive transitivas."""
import importlib.metadata
import unittest
from unittest.mock import patch
from scripts import capturar


class TestAmbiente(unittest.TestCase):
    def test_ambiente_atual_corresponde_ao_lock(self):
        resultado=capturar.ambiente()
        self.assertEqual(resultado["pacotes"]["langgraph"],"1.2.15")

    def test_divergencia_transitiva_atual_e_recusada(self):
        versao_real=importlib.metadata.version
        def simular(nome):
            return "0.0.0" if nome=="langchain-core" else versao_real(nome)
        with patch.object(importlib.metadata,"version",side_effect=simular):
            with self.assertRaisesRegex(ValueError,"langchain-core"):
                capturar.ambiente()


if __name__=="__main__":
    unittest.main()
