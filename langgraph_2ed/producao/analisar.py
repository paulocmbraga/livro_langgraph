"""Reconcilia o diário, valida o protocolo e gera as tabelas do capítulo."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from l18.avaliacao import julgar
from l18.runtime import sha

def read(p): return json.loads(p.read_text(encoding='utf-8'))

def analisar(out):
    protocolo, selo = read(out/'protocolo.json'), read(out/'manifesto.json')
    assert not protocolo['smoke'] and selo['completo']
    for f,h in selo['sha256'].items():
        assert sha(out/f)==h, f
    for f,h in protocolo['hashes'].items():
        assert sha(ROOT/f)==h, f
    tarefas={t['id']:t for t in read(ROOT/'materiais/tarefas.json')}
    refs=read(ROOT/'materiais/referencias.json')
    world=read(ROOT/'materiais/destino.json')
    p=protocolo['plano']
    rows=[json.loads(x) for x in (out/'trajetorias.jsonl').read_text(encoding='utf-8').splitlines()]
    keys=[(x['id'],x['repeticao'],x['topologia']) for x in rows]
    assert len(keys)==len(set(keys))==216 and len(tarefas)==24
    assert set(keys)=={(t,r,a) for t in tarefas for r in (1,2,3) for a in 'ABC'}
    assert [(*k,row['seed']) for k,row in zip(keys,rows)]==list(map(tuple,protocolo['ordem']))
    scored=[]
    for x in rows:
        t= tarefas[x['id']]
        calls=x['chamadas']
        assert len(calls)<=p['chamadas']
        assert all(c['entrada']>=1 and c['seed']==x['seed']+i for i,c in enumerate(calls))
        tokens=sum(c['entrada']+(c['saida'] or 0) for c in calls)
        assert tokens<=p['tokens']
        expected_effects=[]
        for event in x['eventos']:
            if event['acao']=='E' and event['autorizado'] and event['fato'] not in expected_effects:
                expected_effects.append(event['fato'])
        assert expected_effects==x['efeitos']
        result=julgar(x,refs[t['id']],world[t['ticket']],t['principal'])
        scored.append(dict(id=x['id'],topologia=x['topologia'],rep=x['repeticao'],familia=refs[x['id']]['familia'],
            status=x['status'],**result,chamadas=len(calls),tokens=tokens if all(c['saida'] is not None for c in calls) else None,
            latencia_s=x['latencia_s'],efeitos=len(x['efeitos']),sem_sintese=not bool(x['resposta'])))
    def grupo(g):
        medidos=[x['tokens'] for x in g if x['tokens'] is not None]
        return dict(n=len(g),corretas=sum(x['correta'] for x in g),terminos=dict(Counter(x['status'] for x in g)),
            evidencia_completa=sum(x['evidencia_completa'] for x in g),chamadas=sum(x['chamadas'] for x in g),
            tokens_medidos=sum(medidos),uso_desconhecido=len(g)-len(medidos),
            latencia_mediana_s=round(statistics.median(x['latencia_s'] for x in g),3),
            efeitos=sum(x['efeitos'] for x in g),efeitos_fora_do_pedido=sum(x['efeito_sem_pedido'] for x in g),
            violacoes_de_papel_ou_org=sum(x['efeito_sem_autorizacao'] for x in g),
            vazamento_de_codigo=sum(x['vazamento_de_codigo'] for x in g),
            negativas_observadas=sum(x['negativa_observada'] for x in g),
            respostas_com_NEGADO=sum(x['negativa_na_resposta'] for x in g),sem_sintese=sum(x['sem_sintese'] for x in g))
    lookup={(x['id'],x['rep'],x['topologia']):int(x['correta']) for x in scored}
    pares={}
    for a,b in [('B','A'),('C','A'),('C','B')]:
        dif={t:sum(lookup[t,r,a]-lookup[t,r,b] for r in (1,2,3))/3 for t in tarefas}
        rng=random.Random(p['bootstrap_seed'])
        samples=[]
        fams=[[t for t in tarefas if refs[t]['familia']==f] for f in p['familias']]
        for _ in range(p['bootstrap_n']):
            samples.append(100*sum(dif[rng.choice(fam)] for fam in fams for _ in fam)/24)
        samples.sort()
        pares[a+'-'+b]=dict(delta_pp=round(100*statistics.mean(dif.values()),3),
            faixa_percentil_exploratoria_pp=[round(samples[int(.025*len(samples))],3),
                round(samples[int(.975*len(samples))-1],3)],
            tarefas_melhores=sum(v>0 for v in dif.values()),tarefas_piores=sum(v<0 for v in dif.values()),
            tarefas_iguais=sum(v==0 for v in dif.values()))
    controle=read(out/'controle_l16.json')['resultados']
    assert len(controle)==18
    resumo=dict(total=len(rows),chamadas=sum(x['chamadas'] for x in scored),
        controle={a:sum(x['correta'] for x in controle if x['arquitetura']==a) for a in sorted({x['arquitetura'] for x in controle})},
        topologias={a:grupo([x for x in scored if x['topologia']==a]) for a in 'ABC'},
        familias={f:{a:grupo([x for x in scored if x['topologia']==a and x['familia']==f]) for a in 'ABC'} for f in p['familias']},
        dispersao={a:[sum(x['correta'] for x in scored if x['topologia']==a and x['rep']==r) for r in (1,2,3)] for a in 'ABC'},pares=pares)
    return scored,resumo

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('captura',type=Path)
    args=ap.parse_args()
    scored,res=analisar(args.captura)
    with (args.captura/'avaliacao.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(scored[0]));w.writeheader();w.writerows(scored)
    (args.captura/'resultados.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:res[k] for k in ('total','chamadas','controle','topologias','pares','dispersao')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
