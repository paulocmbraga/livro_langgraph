"""Testes de comportamento, regressão e soluções da nova Parte I."""
import copy
import itertools
import threading
import unittest
from exemplos import cap01, cap02, cap03, cap04, solucoes
from exemplos import cap04_distribuicao as distribuicao
from exemplos.cap04_experimentos import comparar_juncao
from exemplos.laboratorios import LABORATORIOS, chamado


class TestTriagem(unittest.TestCase):
    def test_fronteiras_e_filas(self):
        grafo = cap01.criar_grafo()
        for n, prioridade in ((0,"P3"),(1,"P2"),(49,"P2"),(50,"P1"),(51,"P1")):
            for tipo, fila in (("falha","suporte"),("orientacao","conhecimento"),("mudanca","planejamento")):
                with self.subTest(n=n,tipo=tipo):
                    entrada = {"id":"X","tipo":tipo,"usuarios":n}
                    esperado = {"id":"X","prioridade":prioridade,"fila":fila}
                    self.assertEqual(cap01.por_funcao(entrada), esperado)
                    self.assertEqual(grafo.invoke(entrada)["resultado"], esperado)

    def test_nova_invocacao_recebe_nova_entrada(self):
        grafo = cap01.criar_grafo()
        grafo.invoke({"id":"X","tipo":"falha","usuarios":80})
        self.assertEqual(grafo.invoke({"id":"Y","tipo":"mudanca","usuarios":0})["resultado"],
                         {"id":"Y","prioridade":"P3","fila":"planejamento"})

    def test_solucoes_categoria_e_prazo(self):
        grafo = solucoes.grafo_com_prazo()
        for n, prioridade, prazo in ((0,"P3",480),(20,"P2",120),(50,"P1",15)):
            self.assertEqual(solucoes.classificar_pedido({"id":"X","tipo":"pedido","usuarios":n}),
                             {"id":"X","prioridade":prioridade,"fila":"cadastro"})
            self.assertEqual(grafo.invoke({"id":"X","tipo":"falha","usuarios":n})["prazo_minutos"],prazo)
        self.assertNotIn("pedido",cap01.FILAS)


class TestContratos(unittest.TestCase):
    def test_recusa_antes_de_trabalho(self):
        class NaoDeveExecutar:
            def invoke(self, *args, **kwargs):
                raise AssertionError("Trabalho iniciado com entrada invalida")
        for numero in (True,False,-1,"80",None,1.5):
            with self.subTest(numero=numero), self.assertRaises(cap02.ErroContrato):
                cap02.executar(chamado(usuarios=numero),cap02.Contexto(),NaoDeveExecutar())

    def test_formas_invalidas(self):
        for entrada in (None,[],{},chamado(tipo="outro"),chamado(descricao=" "),chamado(id=" X ")):
            with self.subTest(entrada=entrada),self.assertRaises(cap02.ErroContrato):
                cap02.validar_entrada(entrada)

    def test_normalizacao_preserva_original(self):
        original = chamado(descricao="  texto  ")
        self.assertEqual(cap02.validar_entrada(original)["descricao"],"texto")
        self.assertEqual(original["descricao"],"  texto  ")

    def test_contextos_independentes_no_mesmo_grafo(self):
        grafo = cap02.criar_grafo()
        for limite, esperado in ((50,"P1"),(100,"P2"),(50,"P1")):
            self.assertEqual(cap02.executar(chamado(),cap02.Contexto(limite),grafo)["prioridade"],esperado)

    def test_contexto_recusa_configuracao_invalida(self):
        for valor in (True,0,-1,"50"):
            with self.subTest(valor=valor),self.assertRaises(ValueError):cap02.Contexto(valor)

    def test_saida_confere_identidade_fila_e_politica(self):
        correta = {"id":"A-17","prioridade":"P1","fila":"suporte"}
        for campo, valor in (("id","X"),("fila","conhecimento"),("prioridade","P2")):
            with self.subTest(campo=campo),self.assertRaises(cap02.ErroContrato):
                cap02.validar_saida({**correta,campo:valor},chamado(),cap02.Contexto())

    def test_saida_errada_de_no_e_recusada(self):
        chamadas = []
        def errado(estado):
            chamadas.append(estado["id"])
            return {"prioridade":"P0","fila":"suporte"}
        with self.assertRaisesRegex(cap02.ErroContrato,"saida:prioridade"):
            cap02.executar(chamado(),cap02.Contexto(),cap02.criar_grafo(errado))
        self.assertEqual(chamadas,["A-17"])

    def test_projecao_e_stream(self):
        grafo = cap02.criar_grafo()
        self.assertNotIn("diagnostico",cap02.executar(chamado(),cap02.Contexto(),grafo))
        self.assertIn("diagnostico",list(grafo.stream(chamado(),context=cap02.Contexto(),stream_mode="values"))[-1])

    def test_solucao_adaptador(self):
        for valor, esperado in ((0,0),(80,80),(" 80 ",80),("000",0)):
            self.assertEqual(solucoes.normalizar_usuarios(valor),esperado)
        for valor in (True,-1,"-1","1.5","","oitenta","８０",None):
            with self.subTest(valor=valor),self.assertRaises(cap02.ErroContrato):
                solucoes.normalizar_usuarios(valor)
        entrada = chamado(usuarios="80")
        self.assertEqual(solucoes.adaptar_legado(entrada)["usuarios"],80)
        self.assertEqual(entrada["usuarios"],"80")

    def test_solucao_limite_descricao(self):
        self.assertEqual(len(solucoes.validar_descricao_limitada(chamado(descricao="a"*200))["descricao"]),200)
        with self.assertRaisesRegex(cap02.ErroContrato,"descricao_longa"):
            solucoes.validar_descricao_limitada(chamado(descricao="a"*201))


class TestRotas(unittest.TestCase):
    def test_estilos_e_politicas(self):
        for estilo in ("condicional","command"):
            grafo=cap03.montar_grafo(estilo).compile()
            for tipo, permite, status in (("falha",False,"concluido"),("orientacao",True,"concluido"),
                                          ("mudanca",False,"recusado"),("mudanca",True,"proposto")):
                with self.subTest(estilo=estilo,tipo=tipo,permite=permite):
                    self.assertEqual(cap03.atender(chamado(tipo=tipo),cap03.Politica(permite),grafo)["situacao"],status)

    # trecho:teste_terminal
    def test_concluido_exige_resposta(self):
        entrada = chamado(tipo="orientacao")
        for resposta in (None, "", "  ", 42):
            estado = {**entrada, "rota":"orientar", "situacao":"concluido"}
            if resposta is not None:
                estado["resposta"] = resposta
            with self.subTest(resposta=resposta), self.assertRaises(cap02.ErroContrato):
                cap03.validar_fim(estado, entrada, cap03.Politica())
    # fim:teste_terminal

    def test_proposta_exige_vinculo_e_conteudo(self):
        entrada = chamado(tipo="mudanca")
        for proposta in (None,{}, {"chamado_id":"OUTRO","acao":"agendar_analise"},
                         {"chamado_id":"A-17","acao":"executar_agora"}):
            estado={**entrada,"rota":"propor","situacao":"proposto","proposta":proposta}
            with self.subTest(proposta=proposta),self.assertRaises(cap02.ErroContrato):
                cap03.validar_fim(estado,entrada,cap03.Politica(True))

    def test_recusa_exige_motivo_e_nao_admite_proposta(self):
        entrada=chamado(tipo="mudanca")
        for detalhe in ({},{"motivo":" "},{"motivo":"negado","proposta":{}}):
            with self.subTest(detalhe=detalhe),self.assertRaises(cap02.ErroContrato):
                cap03.validar_fim({**entrada,"rota":"recusar","situacao":"recusado",**detalhe},entrada,cap03.Politica())

    def test_rota_nao_pode_contrariar_politica(self):
        entrada=chamado(tipo="mudanca")
        estado={**entrada,"rota":"propor","situacao":"proposto","proposta":{"chamado_id":"A-17","acao":"agendar_analise"}}
        with self.assertRaisesRegex(cap02.ErroContrato,"final:vinculo"):
            cap03.validar_fim(estado,entrada,cap03.Politica(False))

    def test_solucao_motivo_identificavel(self):
        resultado=cap03.atender(chamado(tipo="mudanca"),cap03.Politica(),solucoes.grafo_com_recusa_identificada())
        self.assertEqual(resultado["motivo"],"PROPOSTA_DESABILITADA")


class TestAgregacao(unittest.TestCase):
    def test_sintese_recebe_duas_fontes(self):
        resultado=cap04.criar_grafo().invoke({"documentos":[]})
        self.assertEqual(resultado["resumo"],"Documentos consultados: D-10, D-20")

    def test_leis_no_dominio_compativel(self):
        a,b=[cap04.FONTES["manual"]],[cap04.FONTES["status"]]
        unir=distribuicao.unir_documentos
        for x,y,z in itertools.product([[],a,b,a+b],repeat=3):
            self.assertEqual(unir(unir(x,y),z),unir(x,unir(y,z)))
            self.assertEqual(unir(x,y),unir(y,x))
            self.assertEqual(unir(x,x),unir([],x))

    def test_revisoes_distintas_e_conflito(self):
        a=cap04.FONTES["manual"]
        self.assertEqual(len(distribuicao.unir_documentos([a],[{**a,"revisao":3,"texto":"Revisto"}])),2)
        with self.assertRaisesRegex(ValueError,"conteudos diferentes"):
            distribuicao.unir_documentos([a],[{**a,"texto":"Divergente"}])

    def test_reducer_nao_altera_operandos(self):
        a=[dict(cap04.FONTES["manual"])]
        original=copy.deepcopy(a)
        resultado=distribuicao.unir_documentos([],a)
        resultado[0]["texto"]="alterado"
        self.assertEqual(a,original)

    def test_reducer_recusa_formato(self):
        for item in ({},{**cap04.FONTES["manual"],"revisao":True}, {**cap04.FONTES["manual"],"texto":" "}):
            with self.subTest(item=item),self.assertRaises(ValueError):distribuicao.unir_documentos([],[item])

    def test_juncao_observa_consumidor(self):
        self.assertEqual(comparar_juncao(True)["leituras"],[2])
        self.assertEqual(comparar_juncao(False)["leituras"],[1,2])

    def test_lote_recusa_fonte_e_volume(self):
        grafo=distribuicao.criar_grafo()
        for fontes in (["outra"],["manual"]*11,"manual",[None]):
            with self.subTest(fontes=fontes),self.assertRaises(ValueError):
                grafo.invoke({"fontes":fontes,"documentos":[]})

    def test_solucao_deduplica_antes_da_busca(self):
        fontes=["manual","status","manual"]
        self.assertEqual(solucoes.fontes_unicas(fontes),["manual","status"])
        self.assertEqual(fontes,["manual","status","manual"])
        chamadas,trava=[],threading.Lock()
        def contar(pacote):
            with trava: chamadas.append(pacote["fonte"])
            return distribuicao.buscar(pacote)
        resultado=distribuicao.criar_grafo(contar).invoke({"fontes":solucoes.fontes_unicas(fontes),"documentos":[]})
        self.assertEqual(len(chamadas),2)
        self.assertEqual(len(resultado["documentos"]),2)

    def test_solucao_primeiro_vence_depende_da_ordem(self):
        a=cap04.FONTES["manual"]
        b={**a,"texto":"Versao conflitante"}
        self.assertNotEqual(solucoes.primeiro_vence([a],[b]),solucoes.primeiro_vence([b],[a]))


class TestLaboratorios(unittest.TestCase):
    def test_matrizes_completas(self):
        for numero, tamanho in ((1,9),(2,13),(3,9),(4,9)):
            registros=LABORATORIOS[numero]()
            self.assertEqual(len(registros),tamanho)
            self.assertTrue(all(r["confere"] for r in registros))


if __name__ == "__main__":
    unittest.main()
