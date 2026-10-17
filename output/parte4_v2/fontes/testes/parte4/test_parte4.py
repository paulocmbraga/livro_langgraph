"""Propriedades e contraexemplos adicionais às matrizes da Parte IV."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
import unittest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError
from exemplos.parte4 import cap13 as a, cap14 as b, cap15 as c, cap16 as d
from exemplos.parte4.laboratorios import executar, contexto15


class ContextoTests(unittest.TestCase):
    def test_matriz13(self): self.assertEqual(len(executar(13)["casos"]), 12)

    def test_ferramenta_incompleta(self):
        h = [HumanMessage("Consultar"), AIMessage("", tool_calls=[
            {"name": "ler", "args": {}, "id": "1"}])]
        with self.assertRaises(ValueError): a.episodios(h)

    def test_ids_duplicados(self):
        call = {"name": "ler", "args": {}, "id": "1"}
        with self.assertRaises(ValueError):
            a.episodios([HumanMessage("Consultar"), AIMessage("", tool_calls=[call, call])])

    def test_janela_nao_parte_ferramentas(self):
        h = [HumanMessage("Consultar"), AIMessage("", tool_calls=[
            {"name": "ler", "args": {}, "id": "1"}]),
            ToolMessage("resultado " * 200, tool_call_id="1")]
        r = a.montar(h, "E agora?", "janela")
        self.assertFalse(any(isinstance(m, ToolMessage) for m in r["mensagens"]))
        self.assertTrue(r["admitido"])

    def test_orcamento_booleano(self):
        with self.assertRaises(ValueError): a.montar([], "p", "janela", True, 0)

    def test_base_maior_que_limite(self):
        with self.assertRaises(ValueError): a.montar([], "p" * 1000, "janela", 100, 20)

    def test_revisao_resumo(self):
        h = a.conversa()
        resumo = a.resumo_preparado(h, "prazo_dias=5", 2)
        with self.assertRaises(ValueError): a.montar(h, "p", "resumo", resumo=resumo)

    def test_contexto_nao_e_resposta(self):
        r = executar(13)["evidencias"]["comparacao"][0]
        self.assertTrue(r["fato_preservado"])
        self.assertFalse(r["correta"])

    def test_resumo_errado_com_origem_valida(self):
        h = a.conversa()
        r = a.montar(h, "p", "resumo", resumo=a.resumo_preparado(h, "prazo_dias=9"))
        self.assertEqual(a.responder_controlado(r["mensagens"]), 9)


class MemoriaTests(unittest.TestCase):
    def setUp(self):
        self.m, self.i = b.Memorias(), b.Identidade("aurora", "ana")

    def test_matriz14(self): self.assertEqual(len(executar(14)["casos"]), 12)

    def test_contrato_estrito(self):
        dados = b.preferencia()
        dados["expira_em"] = "20"
        with self.assertRaises(ValidationError): self.m.escrever(self.i, "k", dados, 0, 1)

    def test_instante_futuro(self):
        with self.assertRaises(ValueError):
            self.m.escrever(self.i, "k", b.preferencia(), 0, 0)

    def test_leitura_booleano(self):
        with self.assertRaises(ValueError): self.m.ler(self.i, "k", True)

    def test_copia_isolada(self):
        dados = b.preferencia()
        self.m.escrever(self.i, "k", dados, 0, 1)
        dados["valor"] = "outro"
        lido = self.m.ler(self.i, "k", 2)
        lido["dados"]["valor"] = "mutado"
        self.assertEqual(self.m.ler(self.i, "k", 2)["dados"]["valor"], "pt-BR")

    def test_correcao_simultanea(self):
        self.m.escrever(self.i, "k", b.preferencia(), 0, 1)
        barreira = Barrier(2)
        def gravar(valor):
            barreira.wait()
            try:
                self.m.escrever(self.i, "k", b.preferencia(valor), 1, 2)
                return True
            except b.Conflito:
                return False
        with ThreadPoolExecutor(2) as pool:
            resultados = list(pool.map(gravar, ["en", "es"]))
        self.assertEqual(sum(resultados), 1)
        self.assertEqual(self.m.ler(self.i, "k", 2)["versao"], 2)

    def test_expurgo_paginado(self):
        for n in range(61):
            self.m.escrever(self.i, str(n), b.preferencia(expira=3), 0, 1)
        self.assertEqual(self.m.expurgar_vencidas(self.i, 3), 61)
        self.assertEqual(self.m.expurgar_vencidas(self.i, 3), 0)

    def test_esquecimento_requer_versao(self):
        self.m.escrever(self.i, "k", b.preferencia(), 0, 1)
        with self.assertRaises(b.Conflito): self.m.esquecer(self.i, "k", True)

    def test_nova_coleta_explicita_apos_tombstone(self):
        self.m.escrever(self.i, "k", b.preferencia(), 0, 1)
        self.m.esquecer(self.i, "k", 1)
        r = self.m.escrever(self.i, "k", b.preferencia("es"), 2, 2)
        self.assertEqual(r["versao"], 3)


class SubgrafoTests(unittest.TestCase):
    def test_matriz15(self): self.assertEqual(len(executar(15)["casos"]), 12)

    def test_escopo_divergente(self):
        with self.assertRaises(ValueError):
            c.criar_especialista(False).invoke(
                {"pergunta": "VPN", "organizacao": "outra"}, context=contexto15())

    def test_entrada_nao_coerciva(self):
        with self.assertRaises(ValidationError):
            c.criar_especialista(False).invoke(
                {"pergunta": 1, "organizacao": "aurora"}, context=contexto15())

    def test_sem_documento_nao_interrompe(self):
        r = c.criar_pai(InMemorySaver()).invoke(
            {"pergunta": "impressora"},
            {"configurable": {"thread_id": "vazia"}}, context=contexto15())
        self.assertNotIn("__interrupt__", r)
        self.assertEqual(r["publicado"]["situacao"], "insuficiente")

    def test_revisor_deve_enviar_booleano(self):
        from langgraph.types import Command
        ctx, cfg = contexto15(), {"configurable": {"thread_id": "r"}}
        g = c.criar_pai(InMemorySaver())
        r = g.invoke({"pergunta": "VPN"}, cfg, context=ctx)
        digest = r["__interrupt__"][0].value["digest"]
        s = g.invoke(Command(resume={"aceitar": 1, "digest": digest}), cfg, context=ctx)
        self.assertEqual(s["publicado"]["situacao"], "recusada")

    def test_eventos_ignoram_dados_extras(self):
        eventos = [((), {"publicar": {"publicado": {
            "resposta": "r", "fonte": "f", "situacao": "resposta", "segredo": "x"}}}),
            (("filho:1",), {"recuperar": {"bruto": "interno"}})]
        self.assertEqual(list(c.eventos_publicos(eventos)),
                         [{"resposta": "r", "fonte": "f", "situacao": "resposta"}])


class DelegacaoTests(unittest.TestCase):
    def test_matriz16(self): self.assertEqual(len(executar(16)["casos"]), 12)

    def test_reserva_antes_de_gerar(self):
        chamadas = []
        with self.assertRaises(d.SemOrcamento):
            d.Orcamento(0).chamada("p", {}, lambda: chamadas.append("rodou"))
        self.assertEqual(chamadas, [])

    def test_orcamento_de_estimativa(self):
        with self.assertRaises(d.SemOrcamento):
            d.Orcamento(max_estimativa=10).chamada("p", {}, lambda: {})

    def test_orcamento_nao_aceita_booleano(self):
        with self.assertRaises(ValueError): d.Orcamento(True)

    def test_saida_excessiva_registrada(self):
        orc = d.Orcamento()
        with self.assertRaises(ValueError):
            orc.chamada("p", {}, lambda: {"texto": "x" * 2000})
        self.assertEqual(len(orc.registros), 1)

    def test_uso_desconhecido_nao_e_zero(self):
        r = d.executar_caso(d.CASOS[0], "delegado")
        self.assertTrue(all(i["uso_real"] is None for i in r["registros"]))

    def test_entrega_extra_recusada(self):
        e = d.produzir(d.CASOS[0], "conhecimento")
        e["executar_operacao"] = True
        with self.assertRaises(ValidationError): d.Entrega.model_validate(e)

    def test_reducao_conserva_duas_entregas(self):
        orc = d.Orcamento(max_chamadas=5)
        r = d.criar_delegado(d.CASOS[2], orc).invoke({"entregas": []})
        self.assertEqual(len(r["entregas"]), 2)
        self.assertEqual(r["resposta"], d.CASOS[2]["esperado"])


if __name__ == "__main__":
    unittest.main()
