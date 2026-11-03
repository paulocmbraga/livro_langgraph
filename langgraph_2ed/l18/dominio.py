"""Dados sintéticos e ferramentas. O destino mantém seu próprio livro de efeitos."""
from dataclasses import dataclass, field

@dataclass
class Destino:
    recurso: dict
    principal: dict
    eventos: list = field(default_factory=list)
    efeitos: list = field(default_factory=list)

    def usar(self, acao):
        r = self.recurso
        autorizado = self.principal['org'] == r['org'] and (
            acao != 'E' or self.principal['escrita'])
        if not autorizado:
            fato = 'NEGADO'
        elif acao == 'K':
            fato = r['manual']
        elif acao == 'L':
            fato = r['estado']
        elif acao == 'E':
            fato = 'REC-' + r['ticket']
            if fato not in self.efeitos:
                self.efeitos.append(fato)
        else:
            raise ValueError('ação desconhecida')
        evento = dict(acao=acao, autorizado=autorizado, fato=fato)
        self.eventos.append(evento)
        return evento.copy()
