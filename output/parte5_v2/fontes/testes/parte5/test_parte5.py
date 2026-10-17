"""Casos adversos e propriedades que complementam as quatro matrizes."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
from threading import Barrier
import unittest
from unittest.mock import patch
from langgraph.types import Command
from pydantic import ValidationError
from exemplos.parte5 import cap17 as a, cap18 as b, cap19 as c, cap20 as d
from exemplos.parte5.laboratorios import executar, chave19


class ContratosTrajetoriasTests(unittest.TestCase):
    def test_matriz(self): self.assertEqual(len(executar(17)["casos"]),12)

    def test_contrato_rejeita_bool_e_campo_extra(self):
        for extra in ({"revisao":True},{"autorizar":True}):
            with self.assertRaises(ValidationError):
                a.Acao.model_validate({**a.entrada()["acao"],**extra})

    def test_no_isolado_nao_cria_checkpoint(self):
        g=a.criar_grafo();cfg={"configurable":{"thread_id":"isolado"}}
        antes=list(g.get_state_history(cfg))
        self.assertEqual(g.nodes["coletar"].invoke(a.entrada())["passos"],["coletar"])
        self.assertEqual(list(g.get_state_history(cfg)),antes)

    def test_nova_thread_nao_herda_aprovacao(self):
        g=a.criar_grafo()
        for nome in ("a","b"):
            r=g.invoke(a.entrada(),{"configurable":{"thread_id":nome}})
            self.assertIn("__interrupt__",r)
            self.assertNotIn("aprovado",r)

    def test_digest_errado_nao_produz_efeito(self):
        efeitos=[];g=a.criar_grafo(efeitos=efeitos)
        cfg={"configurable":{"thread_id":"errado"}}
        g.invoke(a.entrada(),cfg)
        r=g.invoke(Command(resume={"aceitar":True,"digest":"outro"}),cfg)
        self.assertEqual(r["situacao"],"recusada")
        self.assertEqual(efeitos,[])

    def test_mutacao_recusada_antes_do_efeito(self):
        r=a.rodar(trocar=True)
        self.assertEqual((r["erro"],r["efeitos"]),("acao_alterada",[]))

    def test_reducer_associativo_idempotente_sem_alias(self):
        x,y,z=([{ "id":str(n),"v":[n]}] for n in range(3))
        self.assertEqual(a.unir_por_id(a.unir_por_id(x,y),z),a.unir_por_id(x,a.unir_por_id(y,z)))
        self.assertEqual(a.unir_por_id(x,x),x)
        r=a.unir_por_id(x,y);r[0]["v"].append(8)
        self.assertEqual(x[0]["v"],[0])

    def test_reducer_recusa_colisao_em_qualquer_lado(self):
        um={"id":"a","v":1};dois={"id":"a","v":2}
        for x,y in (([um],[dois]),([um,dois],[])):
            with self.assertRaises(ValueError):a.unir_por_id(x,y)

    def test_oraculo_ordem_admite_instrumentacao(self):
        r=a.rodar();r["final"]["passos"].insert(1,"medir")
        self.assertTrue(a.verificar(r)["ordem"])


class AvaliacaoTests(unittest.TestCase):
    def test_matriz(self):self.assertEqual(len(executar(18)["casos"]),12)

    def test_delegacao_executa_dois_especialistas_e_uma_juncao(self):
        entrada=b.carregar()["teste"][2]["entrada"]
        eventos=list(b.criar_sistema("delegado").stream({"entrada":entrada},stream_mode="updates"))
        nomes=[k for evento in eventos for k in evento]
        self.assertEqual(nomes.count("especialista"),2)
        self.assertEqual(nomes.count("finalizar"),1)
        self.assertEqual(b.executar()["configuracoes_admitidas_pelo_criterio"],["delegado"])

    def test_referencia_nao_chega_ao_sistema(self):
        recebidas=[]
        class Sistema:
            def invoke(self,entrada):
                recebidas.append(deepcopy(entrada))
                return {"afirmacoes":[],"absteve":True,"falhou":False,"unidades":1}
        with patch.object(b,"criar_sistema",return_value=Sistema()):b.campanha(repeticoes=1)
        self.assertEqual(len(recebidas),16)
        self.assertTrue(all(set(r)=={"entrada"} and set(r["entrada"])=={"pedido","documentos"} for r in recebidas))

    def test_campanha_nao_muda_casos(self):
        dados=b.carregar();copia=deepcopy(dados)
        b.campanha(dados,1)
        self.assertEqual(dados,copia)

    def test_particoes_recusam_ids_e_perguntas(self):
        for tipo in ("id","pergunta"):
            dados=b.carregar()
            if tipo=="id":dados["teste"][0]["id"]=dados["desenvolvimento"][0]["id"]
            else:dados["teste"][0]["entrada"]["pedido"]="  COMO   REDEFINIR SENHA?  "
            with self.assertRaises(ValueError):b.conferir_particoes(dados)

    def test_cardinalidade_recusa_ausente_ou_duplicado(self):
        r=b.campanha(repeticoes=1)["resultados"]
        for variante in (r[:-1],r+[r[0]]):
            with self.assertRaises(ValueError):b.conferir_resultados(variante,b.carregar(),1)

    def test_rubrica_separa_correcao_e_fonte(self):
        caso=b.carregar()["teste"][0]
        saida={"afirmacoes":[{"fato":"cliente_vpn","valor":"Aurora Connect","fonte":"inventada"}],"absteve":False,"falhou":False}
        nota=b.avaliar(caso["entrada"],caso["referencia"],saida)
        self.assertTrue(nota["correta"]);self.assertFalse(nota["sustentada"])

    def test_saida_malformada_vira_falha(self):
        caso=b.carregar()["teste"][0]
        for saida in ({},{"afirmacoes":[],"absteve":1,"falhou":False},
                      {"afirmacoes":[],"absteve":False,"falhou":False}):
            nota=b.avaliar(caso["entrada"],caso["referencia"],saida)
            self.assertFalse(nota["correta"]);self.assertTrue(nota["falhou"])

    def test_afirmacao_duplicada_nao_e_correta(self):
        caso=b.carregar()["teste"][0]
        x={"fato":"cliente_vpn","valor":"Aurora Connect","fonte":"VPN-r2"}
        nota=b.avaliar(caso["entrada"],caso["referencia"],{"afirmacoes":[x,x],"absteve":False,"falhou":False})
        self.assertFalse(nota["correta"])

    def test_bootstrap_pareado_preserva_unidade(self):
        r=b.campanha()["resultados"];dif=b.diferencas_por_caso(r)
        self.assertEqual(len(dif),8)
        self.assertEqual(b.bootstrap_pareado(dif),b.bootstrap_pareado(dif))
        self.assertEqual(b.bootstrap_pareado(dif)["diferenca_media"],.25)

    def test_julgador_de_palavra_erra_negacao_e_parafrase(self):
        r=b.calibrar_julgador()
        self.assertEqual((r["falsos_positivos"],r["falsos_negativos"]),(1,1))


class ObservabilidadeTests(unittest.TestCase):
    def test_matriz(self):self.assertEqual(len(executar(19)["casos"]),12)

    def test_span_fecha_na_excecao(self):
        rel=c.Relogio();coletor=c.Coletor(rel)
        with self.assertRaises(RuntimeError):
            with coletor.medir("falha"):
                rel.avancar(3);raise RuntimeError("CANARIO_PRIVADO")
        self.assertEqual(coletor.pilha,[])
        self.assertEqual(coletor.spans[0]["duracao_ms"],3)
        self.assertNotIn("CANARIO_PRIVADO",str(coletor.spans))

    def test_custo_zero_diferente_de_desconhecido(self):
        self.assertEqual(c.custo([{"entrada":0,"saida":0}])["total"],"0")
        self.assertIsNone(c.custo([{"entrada":None,"saida":0}])["total"])
        self.assertEqual(c.custo([{"entrada":10,"saida":None}])["parcial_conhecido"],"0.00002")

    def test_custo_recusa_valor_invalido(self):
        for valor in (-1,True,1.5):
            with self.assertRaises(ValueError):c.custo([{"entrada":valor,"saida":0}])
        for preco in ("-1","NaN","Infinity"):
            with self.assertRaises(ValueError):c.custo([],preco)

    def test_chave_invalida_em_todas_as_dimensoes(self):
        chave=chave19()
        for campo,valor in (("organizacao","boreal"),("escopo_acesso","outro"),
                            ("revisao_permissao",2),("revisao_corpus","r3"),
                            ("revisao_prompt","r2"),("modelo","v2"),("pergunta","outra")):
            self.assertNotEqual(chave.digest(),replace(chave,**{campo:valor}).digest())

    def test_cache_copia_e_reconsulta_permissao(self):
        cache=c.Cache();original={"itens":[1]};autorizacoes=[]
        validar=lambda:autorizacoes.append(1)
        r,_=cache.consultar(chave19(),0,5,validar,lambda:original)
        r["itens"].append(2);original["itens"].append(3)
        segundo,hit=cache.consultar(chave19(),1,5,validar,lambda:{})
        self.assertEqual(segundo,{"itens":[1]});self.assertTrue(hit)
        self.assertEqual(len(autorizacoes),2)

    def test_cache_nao_grava_excecao(self):
        cache=c.Cache()
        def falhar():raise RuntimeError("falha")
        with self.assertRaises(RuntimeError):cache.consultar(chave19(),0,5,lambda:None,falhar)
        self.assertEqual(cache.itens,{})

    def test_exportacao_sem_textos_e_com_interface_sdk(self):
        from langsmith import Client
        with patch.object(Client,"create_run",autospec=True) as enviar:
            cliente=object.__new__(Client)
            r=c.ensaio();r["resultado"]["resposta"]="CANARIO_NAO_EXPORTAR"
            c.exportar_langsmith(r,cliente,"teste-contrato")
            self.assertEqual(enviar.call_count,1)
            self.assertNotIn("CANARIO_NAO_EXPORTAR",str(enviar.call_args.kwargs))

    def test_relogio_observado_tem_unidade_propria(self):
        r=c.medir_chamada_real(lambda:42)
        self.assertEqual(r["resultado"],42)
        self.assertGreaterEqual(r["duracao_observada_ns"],0)

    def test_contexto_nao_inventa_latencia(self):
        self.assertEqual(c.ensaio(contexto=20)["spans"][0]["duracao_ms"],65)


class AutorizacaoTests(unittest.TestCase):
    def setUp(self):self.ids,self.dest,self.t=d.bancada()
    def aprovar(self):return self.dest.aprovar(self.t["bia"],"bot",d.proposta(),1)
    def test_matriz(self):self.assertEqual(len(executar(20)["casos"]),12)

    def test_revogacao_invalida_sessao(self):
        self.ids.revogar("ana")
        with self.assertRaises(d.Negado):self.dest.ler(self.t["ana"],"A-17",2)

    def test_leitor_nao_aprova(self):
        with self.assertRaises(d.Negado):self.dest.aprovar(self.t["ana"],"bot",d.proposta(),1)

    def test_aprovacao_vinculada_ao_executor(self):
        aprovacao=self.aprovar()
        self.ids.pessoas["bot2"]=replace(self.ids.pessoas["bot"],sujeito="bot2")
        token=self.ids.emitir("bot2",1)
        with self.assertRaises(d.Negado):self.dest.executar(token,d.proposta(),aprovacao,2)
        self.assertEqual(self.dest.efeitos,0)

    def test_revisao_do_recurso_muda_antes_do_commit(self):
        aprovacao=self.aprovar();self.dest.recursos["A-17"]["revisao"]=4
        with self.assertRaises(d.Negado):self.dest.executar(self.t["bot"],d.proposta(),aprovacao,2)
        self.assertEqual(self.dest.efeitos,0)

    def test_revogacao_entre_aplicacao_e_destino(self):
        aprovacao=self.aprovar();original=self.dest.executar
        def revogar(*args):
            self.ids.revogar("bot")
            return original(*args)
        with patch.object(self.dest,"executar",side_effect=revogar):
            with self.assertRaises(d.Negado):d.Aplicacao(self.dest).solicitar(self.t["bot"],d.proposta(),aprovacao,2)
        self.assertEqual(self.dest.efeitos,0)
        self.assertEqual(self.dest.auditoria[-1]["fronteira"],"destino")

    def test_reenvios_concorrentes_um_efeito(self):
        aprovacao=self.aprovar();barreira=Barrier(2)
        def chamar(_):
            barreira.wait(timeout=5)
            return self.dest.executar(self.t["bot"],d.proposta(),aprovacao,2)
        with ThreadPoolExecutor(max_workers=2) as pool:r=list(pool.map(chamar,range(2)))
        self.assertEqual(r[0],r[1]);self.assertEqual(self.dest.efeitos,1)

    def test_mesma_operacao_outro_conteudo_recusado(self):
        self.dest.executar(self.t["bot"],d.proposta(),self.aprovar(),2)
        nova={**d.proposta(),"revisao":4,"prioridade":"baixa"}
        aprovacao=self.dest.aprovar(self.t["bia"],"bot",nova,3)
        with self.assertRaises(d.Negado):self.dest.executar(self.t["bot"],nova,aprovacao,4)
        self.assertEqual(self.dest.efeitos,1)

    def test_outro_id_nao_reutiliza_aprovacao(self):
        aprovacao=self.aprovar();nova={**d.proposta(),"operacao":"outro-id"}
        with self.assertRaises(d.Negado):self.dest.executar(self.t["bot"],nova,aprovacao,2)

    def test_copia_leitura_nao_altera_destino(self):
        r=self.dest.ler(self.t["ana"],"A-17",1);r["documento"]="modificado"
        self.assertNotEqual(self.dest.ler(self.t["ana"],"A-17",2)["documento"],"modificado")

    def test_proposta_nao_transporta_identidade(self):
        with self.assertRaises(ValidationError):d.Acao.model_validate({**d.proposta(),"organizacao":"boreal"})

    def test_auditoria_nao_recebe_credencial(self):
        with self.assertRaises(d.Negado):d.Aplicacao(self.dest).solicitar(self.t["ana"],d.proposta(),self.aprovar(),2)
        texto=json.dumps(self.dest.auditoria)
        self.assertTrue(all(token not in texto for token in self.t.values()))
        self.assertEqual(self.dest.auditoria[-1],{"fronteira":"aplicacao","situacao":"negado"})

    def test_acesso_direto_negado_e_auditado(self):
        with self.assertRaises(d.Negado):self.dest.ler(self.t["ana"],"B-29",2)
        self.assertEqual(self.dest.auditoria[-1],{"fronteira":"destino","operacao":"ler","situacao":"negado"})


if __name__=="__main__":unittest.main()
