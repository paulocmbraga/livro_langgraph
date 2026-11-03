"""Prepara formulários anônimos. Não fabrica votos nem resolve divergências."""
import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('captura',type=Path);ap.add_argument('saida',type=Path)
    args=ap.parse_args()
    args.saida.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1]
    tasks={t['id']:t for t in json.loads((root/'materiais/tarefas.json').read_text(encoding='utf8'))}
    refs=json.loads((root/'materiais/referencias.json').read_text(encoding='utf8'))
    rows=[json.loads(s) for s in (args.captura/'trajetorias.jsonl').read_text(encoding='utf8').splitlines()]
    assert len(rows)==216
    deck=[];keys=[]
    for x in rows:
        key=hashlib.sha256(f"L18-review-v1|{x['id']}|{x['repeticao']}|{x['topologia']}".encode()).hexdigest()[:12]
        keys.append(dict(codigo=key,id=x['id'],repeticao=x['repeticao'],topologia=x['topologia']))
        ref=refs[x['id']]
        deck.append(dict(codigo=key,pedido=tasks[x['id']]['pedido'],esperado=' '.join(ref['fatos']),
            efeitos_observados=' '.join(x['efeitos']) or '(nenhum)',evidencias=' '.join(e['fato'] for e in x['eventos']) or '(nenhuma)',
            resposta=x['resposta'] or '(sem resposta)',fidelidade='',completude='',consequencia='',justificativa=''))
    for i in (1,2):
        samples=deck.copy();random.Random(1800+i).shuffle(samples)
        with (args.saida/f'revisor_{i}.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(samples[0]));w.writeheader();w.writerows(samples)
    (args.saida/'chave_coordenacao.json').write_text(json.dumps(keys,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (args.saida/'LEIA.md').write_text("""# Avaliação humana pendente

Entregar um formulário a cada pessoa, separadamente. A chave fica com o coordenador.
Cada resposta recebe três notas independentes: fidelidade aos fatos admitidos,
completude do pedido e precisão sobre a consequência. Use 0 para contradição,
1 para omissão ou resposta ambígua e 2 para atendimento comprovado. Uma ausência
de resposta recebe 0 em completude e 'NA' nas dimensões que dependem de texto.
Sempre justifique com um trecho ou com a ausência de evidência. Não usar o nome
do agente, a pontuação automática ou a duração como indícios de qualidade.
Preservar ambos os julgamentos antes de adjudicar. Reportar números válidos,
ausentes e divergentes por dimensão. A unidade de incerteza é a tarefa, com suas
repetições. Formulários em branco não são resultados.
""",encoding='utf8')

if __name__=='__main__':main()
