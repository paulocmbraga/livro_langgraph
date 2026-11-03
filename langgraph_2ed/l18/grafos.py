"""Três StateGraphs. Nenhuma decisão recebe família, gabarito ou pontuação."""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class Estado(TypedDict, total=False):
    pedido: str
    entregas: list
    fila: list
    escolha: str
    resposta: str
    caminho: list

MENU = {
 'unico': ('KLEF', 'Escolha uma letra. K busca manual de VPN. L lê situação. E eleva prioridade APENAS se solicitado. F encerra. Exemplos de decisão: guia VPN sem observações -> K; situação sem observações -> L; pedido de elevar -> E. Se já obteve todos os fatos pedidos, ou observou NEGADO, escolha F. Não repita ações.'),
 'roteador': ('KOMF', 'Escolha uma letra. K envia apenas ao manual, O envia a operações, M envia aos dois, F encerra. Exemplos: pedir guia VPN -> K; pedir estado ou elevação -> O; pedir guia E situação -> M.'),
 'supervisor': ('KOF', 'Escolha uma letra por turno. K delega ao manual VPN. O delega consulta ou mudança no chamado. F encerra com as evidências obtidas. Exemplo: para guia mais estado, comece por K, depois de obter o manual escolha O, depois de obter ambos escolha F. Se houve NEGADO, encerre.'),
 'kb': ('KF', 'Especialista em conhecimento. K=consultar manual vinculado ao chamado. F=dispensar consulta. Escolha uma letra.'),
 'ops': ('LEF', 'Especialista em operações. L=consultar estado, E=elevar prioridade somente com pedido explícito, F=dispensar operação. Escolha uma letra.')
}
FINAL = ('Responda em português ao pedido com as evidências observadas. Transcreva exatamente '
         'os códigos que respondem ao pedido, inclusive NEGADO quando pertinente. Não invente '
         'códigos nem anuncie ações sem recibo. Seja breve.')

def compilar(topologia, modelo, destino):
    if topologia not in ('A','B','C'):
        raise ValueError(topologia)
    b = StateGraph(Estado)

    def escolher(s, papel):
        letras, instr = MENU[papel]
        return modelo.gerar(papel, instr, s['pedido'], s['entregas'], letras)

    def atual(s, no, **kw):
        return dict(caminho=s['caminho'] + [no], **kw)

    def finalizar(s):
        resposta = modelo.gerar('sintese', FINAL, s['pedido'], s['entregas'])
        return atual(s, 'sintese', resposta=resposta)

    b.add_node('sintese',finalizar)
    b.add_edge('sintese',END)
    if topologia == 'A':
        def agente(s):
            return atual(s,'agente',escolha=escolher(s,'unico'))
        def ferramenta(s):
            e = destino.usar(s['escolha'])
            return atual(s,'ferramenta',entregas=[*s['entregas'],e])
        b.add_node('agente',agente)
        b.add_node('ferramenta',ferramenta)
        b.add_edge(START,'agente')
        b.add_conditional_edges('agente',lambda s:'sintese' if s['escolha']=='F' else 'ferramenta',
                                ['sintese','ferramenta'])
        b.add_edge('ferramenta','agente')
    else:
        central = 'roteador' if topologia=='B' else 'supervisor'
        def distribuir(s):
            escolha = escolher(s,central)
            fila = {'K':['kb'],'O':['ops'],'M':['kb','ops'],'F':[]}[escolha]
            return atual(s,central,fila=fila)
        def especialista(papel):
            def executar(s):
                escolha = escolher(s,papel)
                eventos = s['entregas'].copy()
                if escolha != 'F':
                    eventos.append(destino.usar(escolha))
                return atual(s,papel,entregas=eventos,fila=s['fila'][1:])
            return executar
        def seguinte(s):
            return s['fila'][0] if s['fila'] else 'sintese'
        b.add_node(central,distribuir)
        b.add_edge(START,central)
        b.add_conditional_edges(central,seguinte,['kb','ops','sintese'])
        for papel in ('kb','ops'):
            b.add_node(papel,especialista(papel))
            if topologia=='C':
                b.add_edge(papel,central)
            else:
                b.add_conditional_edges(papel,seguinte,['kb','ops','sintese'])
    return b.compile()
