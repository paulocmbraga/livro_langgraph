"""Casos que distinguem o contrato estrito da conversão admitida."""
import unittest
from pydantic import ValidationError
from exemplos.cap02_validacao import Quantidade


class TestValidacaoComparada(unittest.TestCase):
    def test_matriz_do_capitulo(self):
        casos = ((80, 80, 80), ("80", 80, None), (True, 1, None), (-1, None, None))
        for entrada, convertido, estrito in casos:
            for modo, esperado in ((False, convertido), (True, estrito)):
                with self.subTest(entrada=entrada, estrito=modo):
                    if esperado is None:
                        with self.assertRaises(ValidationError):
                            Quantidade.model_validate({"usuarios": entrada}, strict=modo)
                    else:
                        resultado = Quantidade.model_validate({"usuarios": entrada}, strict=modo)
                        self.assertEqual(resultado.usuarios, esperado)
                        self.assertIs(type(resultado.usuarios), int)
