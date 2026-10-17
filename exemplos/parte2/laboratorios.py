"""Matrizes locais da Parte II; expectativas são declaradas fora dos grafos."""
import argparse
from copy import deepcopy
import json
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import add_messages
from exemplos.parte2 import cap05, cap06, cap07, cap08
from exemplos.parte2.modelos import Roteiro
from exemplos.parte2.solucoes import metricas_propostas, recall_ids


def caso(nome, observado, esperado):
    return {"nome": nome, "observado": observado,
            "esperado": esperado, "confere": observado == esperado}


def proposta(**trocas):
    return {"tipo": "falha", "usuarios": 80,
            "justificativa": "Portal parou para 80 pessoas.", **trocas}


def l05():
    entradas = [
        ("correta", proposta(), "proposta_valida", True),
        ("plausivel_errada", proposta(tipo="orientacao"), "proposta_valida", False),
        ("numero_texto", proposta(usuarios="80"), "estrutura_invalida", False),
        ("booleano", proposta(usuarios=True), "estrutura_invalida", False),
        ("dominio", proposta(tipo="urgente"), "estrutura_invalida", False),
        ("campo_extra", proposta(executar=True), "estrutura_invalida", False),
        ("justificativa_branca", proposta(justificativa=" "), "justificativa_vazia", False),
        ("json_quebrado", '{"tipo":', "estrutura_invalida", False),
        ("recusa_textual", "Não há quantidade suficiente.", "estrutura_invalida", False),
    ]
    casos, avaliacao = [], []
    for nome, conteudo, motivo, correta in entradas:
        texto = conteudo if isinstance(conteudo, str) else json.dumps(conteudo)
        saida = cap05.executar(
            {"id": "A-17", "descricao": "Portal parou para 80 pessoas."},
            Roteiro([AIMessage(content=texto)]))
        valida = saida["motivo"] == "proposta_valida"
        acerto = valida and saida["proposta"]["tipo"] == "falha" and saida["proposta"]["usuarios"] == 80
        casos.append(caso(nome, [saida["motivo"], acerto], [motivo, correta]))
        avaliacao.append({"valida": valida, "correta": acerto})
    truncada = cap05.executar(
        {"id": "A-17", "descricao": "Portal parou para 80 pessoas."},
        Roteiro([AIMessage(content=json.dumps(proposta()),
                          response_metadata={"fim": "length"})]))
    casos.append(caso("truncada", truncada["motivo"], "truncada"))
    antiga = [HumanMessage(content="Versão 1", id="u1")]
    novas = add_messages(antiga, [HumanMessage(content="Versão 2", id="u1")])
    casos.append(caso("mensagem_substituida", [len(novas), novas[0].content],
                      [1, "Versão 2"]))
    return {"capitulo": 5, "casos": casos,
            "metricas_nove_respostas": metricas_propostas(avaliacao),
            "inferencia_real": {"executada": False, "motivo": "matriz_roteirizada"}}


def l06():
    autorizado = cap06.Escopo("aurora", frozenset({"chamados:ler"}))
    negado = cap06.Escopo("aurora", frozenset())
    matriz = [
        ("conhecida", "consultar_chamado", {"chamado_id": "A-17"}, autorizado, True, True),
        ("nome", "apagar_chamado", {"chamado_id": "A-17"}, autorizado, "ferramenta_desconhecida", False),
        ("tipo", "consultar_chamado", {"chamado_id": 17}, autorizado, "argumentos_invalidos", False),
        ("campo_extra", "consultar_chamado", {"chamado_id": "A-17", "organizacao": "outra"}, autorizado, "argumentos_invalidos", False),
        ("sem_escopo", "consultar_chamado", {"chamado_id": "A-17"}, negado, "sem_permissao", False),
        ("ausente", "consultar_chamado", {"chamado_id": "A-404"}, autorizado, "indisponivel", True),
        ("outra_org", "consultar_chamado", {"chamado_id": "A-99"}, autorizado, "indisponivel", True),
    ]
    casos = []
    for nome, ferramenta, args, escopo, esperado, consultou in matriz:
        mensagem, registro = cap06.despachar(
            {"id": "t1", "name": ferramenta, "args": args}, escopo)
        resultado = registro["resultado"]
        observado = True if resultado["ok"] else resultado["erro"]
        casos.append(caso(nome, [observado, registro["consultou"], mensagem.tool_call_id],
                          [esperado, consultou, "t1"]))
    antes = deepcopy(cap06.BANCO)
    leitura = cap06.consultar("A-17", autorizado, cap06.BANCO)
    prop = cap06.propor(leitura)
    casos.append(caso("proposta_sem_efeito", [prop["novo_status"], cap06.BANCO == antes],
                      ["em_analise", True]))
    duplicada = AIMessage(content="", tool_calls=[
        {"name": "consultar_chamado", "args": {"chamado_id": "A-17"}, "id": "x"},
        {"name": "consultar_chamado", "args": {"chamado_id": "A-17"}, "id": "x"}])
    try:
        cap06.executar_lote(duplicada, autorizado)
        erro = "aceito"
    except ValueError as exc:
        erro = str(exc)
    casos.append(caso("ids_duplicados", erro, "lote_invalido"))
    entrada = cap07.pedir()
    a = cap06.criar_grafo(autorizado).invoke({"messages": [entrada]})
    b = cap06.criar_atalho_toolnode(autorizado).invoke({"messages": [entrada]})
    casos.append(caso("atalho_toolnode", json.loads(a["messages"][-1].content),
                      json.loads(b["messages"][-1].content)))
    return {"capitulo": 6, "casos": casos}


class Relogio:
    def __init__(self, valores):
        self.valores = iter(valores)
        self.ultimo = 0.0

    def __call__(self):
        self.ultimo = next(self.valores, self.ultimo)
        return self.ultimo


def l07():
    final = AIMessage(content='{"chamado_id":"A-17","status":"aberto"}')
    errada = AIMessage(content='{"chamado_id":"A-17","status":"fechado"}')
    matriz = [
        ("concluida", [cap07.pedir(), final], {}, ["concluida", True, 2, 1]),
        ("sem_consulta", [final], {}, ["sem_sustentacao", False, 1, 0]),
        ("status_errado", [cap07.pedir(), errada], {}, ["sem_sustentacao", False, 2, 1]),
        ("repeticao", [cap07.pedir(), cap07.pedir(chamada="c2")], {}, ["repeticao", False, 2, 1]),
        ("sem_progresso", [cap07.pedir("A-404"), cap07.pedir("A-405", "c2")], {}, ["sem_progresso", False, 2, 2]),
        ("limite_modelo", [cap07.pedir()], {"limites": cap07.Limites(modelos=1)}, ["orcamento_modelo", False, 1, 1]),
        ("limite_ferramenta", [cap07.pedir("A-404"), cap07.pedir("A-17", "c2")], {"limites": cap07.Limites(ferramentas=1)}, ["orcamento_ferramenta", False, 2, 1]),
        ("prazo_antes", [final], {"relogio": Relogio([0, 11])}, ["prazo", False, 0, 0]),
        ("prazo_depois", [final], {"relogio": Relogio([0, 0, 11])}, ["prazo", False, 1, 0]),
        ("inconclusiva", [AIMessage(content="Talvez esteja aberto.")], {}, ["inconclusiva", False, 1, 0]),
        ("modelo_falhou", [], {}, ["falha_modelo", False, 1, 0]),
    ]
    casos = []
    for nome, respostas, opcoes, esperado in matriz:
        saida = cap07.executar(Roteiro(respostas), **opcoes)
        observado = [saida[k] for k in ("motivo", "resolvida", "modelos", "ferramentas")]
        casos.append(caso(nome, observado, esperado))
    return {"capitulo": 7, "casos": casos}


def l08():
    vpn, senha = cap08.CORPUS[1], cap08.CORPUS[2]
    inventada = AIMessage(content=json.dumps({
        "situacao": "resposta",
        "alegacoes": [{"texto": "A VPN dispensa autenticação.", "fonte": vpn.id}]}))
    falsa_fonte = AIMessage(content=json.dumps({
        "situacao": "resposta",
        "alegacoes": [{"texto": vpn.texto, "fonte": "inexistente"}]}))
    matriz = [
        ("respondível", "Como configurar a VPN?", cap08.resposta_de(vpn), 3, "citacoes_validas", True),
        ("ausente", "Existe estacionamento?", cap08.resposta_de(vpn), 3, "sem_evidencia", False),
        ("conflito", "Qual o prazo da mudança?", cap08.resposta_de(cap08.CORPUS[3]), 3, "conflito", False),
        ("citacao_inventada", "Como configurar a VPN?", inventada, 3, "citacao_invalida", False),
        ("fonte_inventada", "Como configurar a VPN?", falsa_fonte, 3, "citacao_invalida", False),
        ("parafrase_sinonima", "Como estabelecer conexão remota?", cap08.resposta_de(vpn), 3, "sem_evidencia", False),
        ("top1_oculta_conflito", "Qual o prazo da mudança?", cap08.resposta_de(cap08.CORPUS[3]), 1, "citacoes_validas", False),
        ("abstencao", "Como configurar a VPN?", AIMessage(content='{"situacao":"insuficiente","alegacoes":[]}'), 3, "abstencao", False),
        ("json_invalido", "Como configurar a VPN?", AIMessage(content="VPN"), 3, "estrutura_invalida", False),
        ("fonte_certa_pergunta_errada", "VPN e senha: explique apenas a VPN.", cap08.resposta_de(senha), 3, "citacoes_validas", False),
    ]
    casos = []
    for nome, pergunta, resposta, k, motivo, util in matriz:
        roteiro = Roteiro([resposta])
        saida = cap08.executar(pergunta, roteiro, k=k)
        casos.append(caso(nome, saida["motivo"], motivo))
        casos[-1].update({"responde_adequadamente_gabarito": util,
                          "chamadas_modelo": roteiro.chamadas,
                          "fontes": [t.id for t in saida["trechos"]]})
    encontrados = cap08.recuperar("Como recuperar senha?")
    casos.append(caso("isolamento", [t.id for t in encontrados], [senha.id]))
    atual = cap08.recuperar("Como configurar a VPN?")
    casos.append(caso("revisao_ativa", [t.id for t in atual], [vpn.id]))
    comparacao = {
        "pergunta": "Como configurar a VPN?",
        "direta_roteirizada": "Use o cliente legado.",
        "direta_correta": False,
        "com_recuperacao_roteirizada": vpn.texto,
        "com_recuperacao_correta": True,
        "recall": recall_ids([t.id for t in atual], [vpn.id]),
        "limite": "Contraste controlado; não estima vantagem de um modelo real.",
    }
    return {"capitulo": 8, "casos": casos, "comparacao": comparacao}


def executar(capitulo):
    resultado = {5: l05, 6: l06, 7: l07, 8: l08}[capitulo]()
    if not all(c["confere"] for c in resultado["casos"]):
        raise AssertionError(json.dumps(resultado, ensure_ascii=False))
    return resultado


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capitulo", type=int, choices=range(5, 9), required=True)
    args = parser.parse_args()
    print(json.dumps(executar(args.capitulo), ensure_ascii=False, indent=2))
