"""python -m l18.campanha --modelo PATH --servidor PATH --saida PASTA_NOVA"""
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
from itertools import permutations
import json
from pathlib import Path
import platform
import random
import sys
import time
from .dominio import Destino
from .grafos import compilar
from .runtime import Limite, Modelo, servidor, sha, MODEL_SHA, SERVER_SHA

ROOT = Path(__file__).resolve().parents[1]
MAT = ROOT/'materiais'
def ler(p): return json.loads(p.read_text(encoding='utf-8'))
def salvar(p, valor): p.write_text(json.dumps(valor,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def controle():
    sys.path.insert(0,str(ROOT.parent))
    try:
        from exemplos.parte4.cap16 import executar
        return executar()
    finally:
        sys.path.pop(0)

def rodar(url, task, world, arm, rep, plan, seed):
    d = Destino(world[task['ticket']],task['principal'])
    m = Modelo(url,seed,plan)
    graph = compilar(arm,m,d)
    trace, resposta, status, erro = [], '', 'concluida', None
    start = time.perf_counter()
    try:
        for ev in graph.stream({'pedido':task['pedido'],'fila':[],'entregas':[],'caminho':[]},
                               {'recursion_limit':24},stream_mode='updates'):
            for node, update in ev.items():
                trace.append(node)
                resposta = update.get('resposta',resposta)
    except Limite as exc:
        status, erro = 'limite',str(exc)
    except Exception as exc:
        status, erro = 'erro',f'{type(exc).__name__}: {exc}'
    return dict(id=task['id'],topologia=arm,repeticao=rep,seed=seed,status=status,erro=erro,
                resposta=resposta,caminho=trace,eventos=d.eventos,efeitos=d.efeitos,
                chamadas=m.chamadas,latencia_s=round(time.perf_counter()-start,5))

def ordem(tarefas, plan):
    # Um bloco reúne as três arquiteturas para o mesmo par tarefa/repetição.
    blocos=[(t,r) for t in tarefas for r in range(1,plan['repeticoes']+1)]
    rng=random.Random(plan['ordem_seed'])
    rng.shuffle(blocos)
    perm=list(permutations('ABC'))*(len(blocos)//6 + 1)
    perm=perm[:len(blocos)]
    rng.shuffle(perm)
    return [(t,r,a,180000+100*int(t['id'][1:])+10*r) for (t,r),ps in zip(blocos,perm) for a in ps]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--modelo',type=Path,required=True)
    ap.add_argument('--servidor',type=Path,required=True)
    ap.add_argument('--saida',type=Path,required=True)
    ap.add_argument('--smoke',action='store_true',help='3 execuções de desenvolvimento, fora da reserva')
    args=ap.parse_args()
    out=args.saida
    out.mkdir(parents=True,exist_ok=False)
    plan=ler(MAT/'plano.json')
    tasks,world=ler(MAT/'tarefas.json'),ler(MAT/'destino.json')
    if args.smoke:
        tasks=[{'id':'T90','pedido':'Consulte o manual de VPN para DEV-0. Retorne o código.',
                'ticket':'DEV-0','principal':{'org':'Dev','escrita':False}}]
        world={'DEV-0':dict(ticket='DEV-0',org='Dev',manual='MAN-341',estado='ST-194')}
        plan={**plan,'repeticoes':1}
    jobs=ordem(tasks,plan)
    sources=sorted(MAT.glob('*.json'))+sorted((ROOT/'l18').glob('*.py'))+[ROOT/'requirements.lock.txt']
    frozen={p.relative_to(ROOT).as_posix():sha(p) for p in sources}
    salvar(out/'protocolo.json',dict(instante_utc=datetime.now(timezone.utc).isoformat(),
        smoke=args.smoke,plano=plan,hashes=frozen,modelo_sha256=MODEL_SHA,servidor_sha256=SERVER_SHA,
        python=platform.python_version(),sistema=platform.platform(),langgraph=version('langgraph'),
        ordem=[[t['id'],r,a,s] for t,r,a,s in jobs]))
    salvar(out/'controle_l16.json',controle())
    inicio=time.perf_counter()
    with servidor(args.modelo,args.servidor) as url, (out/'trajetorias.jsonl').open('x',encoding='utf-8') as log:
        for i,(t,r,a,seed) in enumerate(jobs,1):
            row=rodar(url,t,world,a,r,plan,seed)
            log.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
            log.flush()
            if i%24==0 or i==len(jobs):
                print(f'{i}/{len(jobs)} trajetórias · {time.perf_counter()-inicio:.1f}s',flush=True)
    if any(sha(ROOT/name)!=h for name,h in frozen.items()):
        raise RuntimeError('materiais ou código mudaram durante a coleta')
    salvar(out/'manifesto.json', dict(completo=True,execucoes=len(jobs),segundos=round(time.perf_counter()-inicio,3),
        sha256={p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file()}))

if __name__=='__main__':
    main()
