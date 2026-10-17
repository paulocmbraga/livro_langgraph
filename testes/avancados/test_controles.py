import copy
import json
import unittest
from unittest.mock import Mock
from langgraph.types import Command
from exemplos.avancados import guardrails as g, planejamento as p, coordenacao as c
from exemplos.avancados import mcp_local as m, a2a_local as a, integracao as i
from exemplos.parte6.ensaios import bancada


class Guardrails(unittest.TestCase):
    def test_minimizacao(self):
        d = g.entrada("VPN ana@example.org")
        self.assertEqual(d.texto, "VPN [EMAIL]")
        self.assertNotIn("ana@", json.dumps(d.evento("entrada")))

    def test_limites_entrada(self):
        for x in (None, True, "", "x" * 2001):
            with self.subTest(x=str(x)[:10]):
                self.assertEqual(g.entrada(x).acao, "bloquear")

    def test_segredo(self):
        self.assertEqual(g.entrada("SEGREDO_X").acao, "bloquear")
        self.assertEqual(g.saida("SEGREDO_X", ["D1"], {"D1"}).texto, "")

    def test_julgador_falha_fechado(self):
        for f in (Mock(side_effect=TimeoutError), lambda _: {},
                  lambda _: {"risco": float("nan"), "motivo": "adequado"}):
            self.assertEqual(g.julgar_contexto("x", f).acao, "revisar")

    def test_incerteza(self):
        self.assertEqual(g.julgar_contexto("novo", g.classificador_preparado).acao, "revisar")

    def test_limiares(self):
        for score, esperado in [(.39, "permitir"), (.4, "revisar"), (.79, "revisar"), (.8, "bloquear")]:
            self.assertEqual(g.julgar_contexto("x", lambda _: {
                "risco": score, "motivo": "adequado"}).acao, esperado)

    def test_fontes(self):
        for fontes in ([], ["D2"], ["D1", "D2"]):
            self.assertEqual(g.saida("resposta", fontes, {"D1"}).acao, "revisar")
        self.assertEqual(g.saida("a@example.org", ["D1"], {"D1"}).texto, "[EMAIL]")

    def test_confusao(self):
        r = g.avaliar_rotulos(g.corpus_avaliacao(), .8)
        self.assertEqual([r[k] for k in ("tp", "fp", "tn", "fn")], [1, 1, 1, 2])
        self.assertEqual(g.avaliar_rotulos(g.corpus_avaliacao(), .4)["fn"], 1)

    def test_amostras_invalidas(self):
        for limiar in (float("nan"), -1, 2, True):
            with self.assertRaises(ValueError):
                g.avaliar_rotulos(g.corpus_avaliacao(), limiar)
        with self.assertRaises(ValueError):
            g.avaliar_rotulos(g.corpus_avaliacao() * 2, .8)


class Planejamento(unittest.TestCase):
    def test_bfs_e_alternativa(self):
        self.assertEqual(p.buscar("novo")["acoes"], ["diagnosticar", "corrigir", "testar"])
        self.assertIn("contornar", p.buscar("novo", {"corrigir"})["acoes"])

    def test_sem_caminho_e_limite(self):
        self.assertEqual(p.buscar("novo", {"diagnosticar"})["motivo"], "sem_caminho")
        self.assertEqual(p.buscar("novo", limite=0)["motivo"], "busca_limitada")

    def test_replaneja(self):
        ambiente = p.Ambiente(indisponiveis=frozenset({"corrigir"}))
        r = p.executar(ambiente)
        self.assertEqual(r["motivo"], "concluida")
        self.assertEqual(ambiente.efeitos, ["diagnosticar", "contornar", "testar"])

    def test_orcamento_zero(self):
        for opcoes in ({"max_chamadas": 0}, {"max_planos": 0}):
            ambiente = p.Ambiente()
            p.executar(ambiente, **opcoes)
            self.assertEqual(ambiente.efeitos, [])

    def test_observacao_obsoleta(self):
        ambiente = p.Ambiente(revisao=2)
        self.assertEqual(ambiente.executar("diagnosticar", 1)["situacao"], "obsoleto")
        self.assertEqual(ambiente.efeitos, [])

    def test_retorno_perdido_nao_repete(self):
        ambiente = p.Ambiente(perder_retorno=True)
        r = p.executar(ambiente)
        self.assertEqual(r["motivo"], "desconhecida")
        self.assertEqual(len(ambiente.efeitos), 1)

    def test_plano_hostil(self):
        ambiente = p.Ambiente()
        p.executar(ambiente, planejador=lambda *_: {"motivo": "plano", "acoes": ["apagar"]})
        self.assertEqual(ambiente.efeitos, [])


class Coordenacao(unittest.TestCase):
    def test_repeticao_e_conflito(self):
        k = c.Coordenador()
        e = c.entrega("impacto")
        self.assertEqual(k.receber(e), "aceita")
        self.assertEqual(k.receber(e), "duplicada")
        self.assertEqual(k.receber({**e, "prioridade": "normal"}), "conflito_integridade")
        self.assertEqual(k.concluir()["status"], "conflito_integridade")

    def test_atraso_e_fechamento(self):
        k = c.Coordenador(); k.reatribuir("impacto")
        self.assertEqual(k.receber(c.entrega("impacto")), "obsoleta_ou_alheia")
        k.concluir()
        self.assertEqual(k.receber(c.entrega("operacao")), "encerrado")

    def test_fonte_desconhecida(self):
        self.assertEqual(c.Coordenador().receber({**c.entrega("impacto"), "fonte": "inventada"}), "fonte_invalida")

    def test_origem_dependente(self):
        k = c.Coordenador(catalogo={"D1": (1, "raiz"), "D2": (1, "raiz")})
        k.receber(c.entrega("impacto")); k.receber(c.entrega("operacao"))
        self.assertEqual(k.concluir()["status"], "evidencia_dependente")

    def test_revisao_dossie(self):
        g = c.criar_equipe(); config = {"configurable": {"thread_id": "T"}}
        r = g.invoke({"tarefas": [c.entrega("impacto"), c.entrega("operacao", "normal")], "entregas": []}, config)
        self.assertIn("__interrupt__", r)
        with self.assertRaises(ValueError):
            g.invoke(Command(resume={"digest": "outro", "prioridade": "alta"}), config)


class MCP(unittest.TestCase):
    def test_ordem_inicializacao(self):
        s = m.Servidor()
        r = s.receber({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertIn("error", r)

    def test_correlacao(self):
        for r in ({"jsonrpc": "2.0", "id": 2, "result": {}},
                  {"jsonrpc": "2.0", "id": True, "result": {}},
                  {"jsonrpc": "2.0", "id": 1, "result": {}, "error": {}}):
            with self.assertRaises(m.ErroProtocolo):
                m.validar_resposta(r, 1)

    def test_subprocesso_escopo(self):
        with m.Cliente() as cliente:
            cliente.inicializar()
            self.assertEqual(cliente.consultar("A-17")["status"], "aberto")
            with self.assertRaises(ValueError):
                cliente.consultar("B-29")
            with self.assertRaises(m.ErroProtocolo):
                cliente.chamar("tools/call", {"name": "apagar", "arguments": {}})
        self.assertIsNotNone(cliente.processo.poll())

    def test_versao_recusada(self):
        with m.Cliente() as cliente:
            with self.assertRaises(m.ErroProtocolo):
                cliente.inicializar("1900-01-01")


class A2A(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = a.servidor(); cls.url, cls.agente = cls.ctx.__enter__()
        cls.tokens = list(cls.agente.tokens)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def cliente(self, qual=0):
        return a.Cliente(self.url, self.tokens[qual])

    def test_descoberta(self):
        card = self.cliente().descobrir()
        self.assertEqual(card["capabilities"]["streaming"], False)
        self.assertEqual(card["securitySchemes"]["bearer"],
                         {"httpAuthSecurityScheme": {"scheme": "Bearer"}})
        self.assertEqual(card["securityRequirements"],
                         [{"schemes": {"bearer": {"list": []}}}])

    def test_descoberta_sem_requisito_de_autenticacao(self):
        from unittest.mock import patch
        card = a.cartao(self.url)
        card.pop("securityRequirements")
        with patch.object(a, "cartao", return_value=card):
            with self.assertRaisesRegex(ValueError, "Autenticação anunciada"):
                self.cliente().descobrir()

    def test_ciclo(self):
        c = self.cliente(); t = c.enviar("priorizar?", "ciclo1")
        self.assertEqual(t["status"]["state"], "TASK_STATE_INPUT_REQUIRED")
        f = c.enviar("alta", "ciclo2", t)
        self.assertEqual(f["id"], t["id"])
        self.assertEqual(c.chamar("GetTask", {"id": t["id"]}), f)

    def test_contexto_divergente(self):
        c = self.cliente(); t = c.enviar("priorizar?", "ctx1")
        with self.assertRaises(m.ErroProtocolo):
            c.enviar("alta", "ctx2", {**t, "contextId": "outro"})

    def test_isolamento(self):
        t = self.cliente().enviar("priorizar?", "isolamento")
        for metodo in ("GetTask", "CancelTask"):
            with self.assertRaises(m.ErroProtocolo):
                self.cliente(1).chamar(metodo, {"id": t["id"]})
        with self.assertRaises(m.ErroProtocolo):
            self.cliente(1).enviar("alta", "intruso", t)

    def test_idempotencia_local(self):
        c = self.cliente(); t = c.enviar("alta", "duplicada")
        self.assertEqual(t, c.enviar("alta", "duplicada"))
        with self.assertRaises(m.ErroProtocolo):
            c.enviar("normal", "duplicada")

    def test_cancelamento(self):
        c = self.cliente(); t = c.enviar("priorizar?", "cancelar")
        self.assertEqual(c.chamar("CancelTask", {"id": t["id"]})["status"]["state"], "TASK_STATE_CANCELED")
        with self.assertRaises(m.ErroProtocolo):
            c.enviar("alta", "apos_cancelar", t)

    def test_versao_e_streaming(self):
        for metodo, versao in [("GetTask", "0.3"), ("SendStreamingMessage", "1.0")]:
            with self.assertRaises(m.ErroProtocolo):
                self.cliente().chamar(metodo, {}, versao)

    def test_credencial(self):
        import httpx
        with self.assertRaises(httpx.HTTPStatusError):
            a.Cliente(self.url, "invalida").chamar("GetTask", {"id": "x"})


class Integracao(unittest.TestCase):
    def test_publicacao_minima(self):
        with bancada() as (app, tokens):
            r = i.criar_conhecimento(app, tokens["ana"], "k").invoke({"pergunta": "VPN a@example.org"})
            self.assertEqual(r["decisao"], "permitir")
            self.assertIn("Aurora Connect", r["publicacao"])
            self.assertNotIn("a@example", json.dumps(r))

    def test_bloqueio_antes_da_fila(self):
        with bancada() as (app, tokens):
            app.criar = Mock(side_effect=AssertionError("Não deve admitir"))
            r = i.criar_conhecimento(app, tokens["ana"], "k").invoke({"pergunta": "VPN SEGREDO_X"})
            self.assertEqual(r["decisao"], "bloquear")
            app.criar.assert_not_called()

    def test_contexto_hostil(self):
        with bancada() as (app, tokens):
            app.criar = Mock()
            r = i.criar_conhecimento(app, tokens["ana"], "k", lambda _: {
                "risco": .99, "motivo": "instrucao_hostil"}).invoke({"pergunta": "VPN"})
            self.assertEqual(r["decisao"], "bloquear")
            app.criar.assert_not_called()

    def test_saida_contaminada(self):
        with bancada() as (app, tokens):
            original = app.conhecimento.responder
            def contaminada(*args):
                return {**original(*args), "resposta": "SEGREDO_X"}
            app.conhecimento.responder = contaminada
            r = i.criar_conhecimento(app, tokens["ana"], "k").invoke({"pergunta": "VPN"})
            self.assertEqual((r["decisao"], r["publicacao"]), ("bloquear", ""))

    def test_projeto_integrado_real(self):
        r = i.demonstrar()
        self.assertEqual((r["antes_da_revisao"], r["depois_da_revisao"]), (0, 1))
        self.assertEqual(r["situacao"], "concluida")

    def test_artefato_nao_autoriza(self):
        with bancada() as (app, tokens):
            remoto = Mock()
            remoto.enviar.return_value = {"status": {"state": "TASK_STATE_COMPLETED"},
                "artifacts": [{"parts": [{"text": json.dumps({"prioridade": "alta",
                "fonte": "D1", "revisao": 1, "texto": "SEGREDO_X"})}]}]}
            with self.assertRaises(ValueError):
                i.propor_operacao(app, tokens["ana"], "k", Mock(), remoto, "alta")
            self.assertEqual(app.dominio.efeitos(), 0)

    def test_corpus_muda_entre_etapas(self):
        with bancada() as (app, tokens):
            original = app.processar_um
            def processar():
                app.conhecimento.publicar("corpus-2")
                return original()
            app.processar_um = processar
            r = i.criar_conhecimento(app, tokens["ana"], "k").invoke({"pergunta": "VPN"})
            self.assertEqual(r["eventos"][-1]["regra"], "corpus_alterado")
            self.assertEqual(r["publicacao"], "")

    def test_sem_fonte_nao_admite(self):
        with bancada() as (app, tokens):
            app.criar = Mock()
            r = i.criar_conhecimento(app, tokens["ana"], "k").invoke({"pergunta": "assunto inexistente"})
            self.assertEqual(r["decisao"], "revisar")
            app.criar.assert_not_called()

    def test_artefatos_invalidos_antes_da_admissao(self):
        for alteracao in ({"fonte": "D99"}, {"prioridade": "normal"},
                          {"revisao": 2}, {"revisao": True}, {"revisao": 1.0}):
            with bancada() as (app, tokens):
                app.criar = Mock()
                dado = {"prioridade": "alta", "fonte": "D1", "revisao": 1, "texto": "Proposta"}
                remoto = Mock()
                remoto.enviar.return_value = {"status": {"state": "TASK_STATE_COMPLETED"},
                    "artifacts": [{"parts": [{"text": json.dumps({**dado, **alteracao})}]}]}
                with self.assertRaises(ValueError):
                    i.propor_operacao(app, tokens["ana"], "k", Mock(), remoto, "alta")
                app.criar.assert_not_called()

    def test_dossie_e_papel_revisor(self):
        from exemplos.parte6.base import Problema
        with bancada() as (app, tokens), a.servidor() as (url, agente), m.Cliente() as cliente:
            cliente.inicializar()
            remoto = a.Cliente(url, next(iter(agente.tokens)))
            pacote = i.propor_operacao(app, tokens["ana"], "k", cliente, remoto, "alta")
            adulterado = copy.deepcopy(pacote)
            adulterado["dossie"]["recomendacao"]["prioridade"] = "normal"
            with self.assertRaises(ValueError):
                i.aprovar_operacao(app, tokens["bia"], adulterado, pacote["digest"])
            with self.assertRaises(Problema):
                i.aprovar_operacao(app, tokens["ana"], pacote, pacote["digest"])
            self.assertEqual(app.dominio.efeitos(), 0)
