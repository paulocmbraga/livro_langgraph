"""Contraprovas e vínculos editoriais do volume integral."""
from collections import Counter
import csv
import json
from pathlib import Path
import unittest

from bancadas.controles import MAPA
from bancadas.geradores import extrair
from bancadas.incidentes import conhecimento
from bancadas.fronteiras import visibilidade
from bancadas.planejar import montar

BOOK=Path(__file__).resolve().parents[1]


def ler(p):
    return json.loads((BOOK/"output"/p).read_text(encoding="utf8"))


class Producao(unittest.TestCase):
    def test_projecao_nao_publica_marcador(self):
        r=visibilidade()
        self.assertIn("MARCADOR",str(r["evento_bruto"]))
        self.assertNotIn("MARCADOR",str(r["projecao"]))

    def test_revisao_trocada_refuta_ultimo_rotulo(self):
        self.assertIn("8443",conhecimento(False)["resposta"])
        self.assertIn("r2",conhecimento(False)["resposta"])
        self.assertTrue(conhecimento(True)["resposta"].startswith("abster"))

    def test_busca_replaneja_depois_da_falha(self):
        x=montar("busca",None,False).invoke({"objetivo":"VPN"})
        self.assertEqual(x["passos"],["M: indisponível","C: chegou J47"])
        self.assertEqual(x["desfecho"],"resolvida")

    def test_extrativo_pode_errar_ordem_da_revisao(self):
        self.assertEqual(extrair(["Vigente F63. Antiga J47."]), "J47")

    def test_cobertura_dos_capitulos(self):
        self.assertEqual(set(MAPA)|{11,18},set(range(1,33)))
        for n in MAPA:
            d=ler(f"controles_volume_v01/L{n:02}.json")
            self.assertEqual(d["origem"],MAPA[n])
            self.assertTrue(all(c["confere"] for c in d["observacao"].get("casos",[])))

    def test_julgamento_humano_aberto_e_cego(self):
        pasta=BOOK/"output/revisao_cega22_v01"
        for f in ("revisor_A.csv","revisor_B.csv"):
            with (pasta/f).open(encoding="utf-8-sig") as src:
                linhas=list(csv.DictReader(src))
            self.assertEqual(len(linhas),32)
            self.assertTrue(all(not r["sustentacao"] and "arquitetura" not in r for r in linhas))

    def test_pares_da_reserva(self):
        x=ler("inferencia_volume_v01/resultados.json")["L15_L22"]
        pares=Counter((r["id"],r["arquitetura"]) for r in x)
        self.assertEqual(len(pares),16)
        self.assertEqual(set(pares.values()),{2})
        self.assertEqual(len(ler("geradores_volume_v01/L15.json")),16)

    def test_tarefa_e_efeito_sobrevivem_as_duas_quedas(self):
        r=ler("a2a_volume_v02/resultado.json")
        self.assertEqual(r["saida_primeiro"],73)
        t=r["queda_apos_credito"]
        self.assertEqual((t["saida"],len(t["efeitos"])),(74,1))
        self.assertEqual(t["antes"]["status"]["state"],"TASK_STATE_WORKING")
        self.assertEqual(t["depois"]["status"]["state"],"TASK_STATE_COMPLETED")

    def test_restauracao_nao_avanca_origem(self):
        pg=ler("postgres_volume_v02/resultado.json")
        self.assertEqual([pg["origem"],pg["copia"]],["pausada","aprovada"])
        inc=ler("incidentes_volume_v02/L32.json")
        self.assertEqual(inc["restauros"],{"regressao":[60],"v1":[30]})
        self.assertFalse(inc["efeitos_na_origem"])
