"""Diagnóstico posterior. Varia a instrução e a disponibilidade de fatos, fora da campanha principal."""
import argparse
from datetime import datetime, timezone
from itertools import product
import json
from pathlib import Path
import random
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from l18.runtime import Modelo, servidor, sha
from l18.grafos import FINAL
from l18.avaliacao import CODIGOS

NEUTRA='Responda ao pedido em português. Use somente as observações fornecidas. Copie os códigos relevantes exatamente. Quando não houver evidência, diga que faltam dados. Seja breve.'
CASOS=[
    ('D1','Qual o código do guia de VPN para AU-201?',[('K','MAN-731')]),
    ('D2','Consulte o estado do chamado AU-202.',[('L','ST-658')]),
    ('D3','Informe a referência da VPN e eleve a prioridade de AU-203.',[('K','MAN-412'),('E','REC-AU-203')]),
    ('D4','Priorize AU-204 de outra organização.',[('E','NEGADO')])]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--modelo',type=Path,required=True);ap.add_argument('--servidor',type=Path,required=True)
    ap.add_argument('--saida',type=Path,required=True);args=ap.parse_args()
    out=args.saida;out.mkdir(parents=True,exist_ok=False)
    p=json.loads((ROOT/'materiais/plano.json').read_text(encoding='utf8'))
    jobs=list(product(range(4),['original','neutra'],[False,True],[1,2,3]))
    random.Random(18083).shuffle(jobs)
    protocolo=dict(utc=datetime.now(timezone.utc).isoformat(),hipotese='Fornecer fatos à síntese altera a cópia de códigos e a recusa verbal. O efeito da redação é avaliado separadamente.',casos=CASOS,ordem=jobs,prompts={'original':FINAL,'neutra':NEUTRA},fonte_sha256=sha(Path(__file__)),principal_sha256=sha(ROOT/'output/l18_principal_v01/manifesto.json'))
    (out/'protocolo.json').write_text(json.dumps(protocolo,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    rows=[]
    with servidor(args.modelo,args.servidor) as url,(out/'chamadas.jsonl').open('x',encoding='utf8') as raw:
        for i,variant,fatos,rep in jobs:
            ident,pedido,expected=CASOS[i]
            obs=[dict(acao=a,autorizado=v!='NEGADO',fato=v) for a,v in expected] if fatos else []
            m=Modelo(url,88000+100*i+rep,p)
            answer=m.gerar('sintese',protocolo['prompts'][variant],pedido,obs)
            codes={x.upper() for x in CODIGOS.findall(answer)}
            row=dict(id=ident,redacao=variant,fatos=fatos,rep=rep,copia_exata=codes=={v for _,v in expected},
                     negativa='NEGADO' in codes,chamada=m.chamadas[0])
            rows.append(row);raw.write(json.dumps(row,ensure_ascii=False)+'\n');raw.flush()
    assert len(rows)==48
    summary={}
    for v,b in product(['original','neutra'],[False,True]):
        g=[x for x in rows if x['redacao']==v and x['fatos']==b]
        summary[f'{v}/{b}']=dict(n=len(g),codigos_da_referencia=sum(x['copia_exata'] for x in g),negativas=sum(x['negativa'] for x in g))
    (out/'resultados.json').write_text(json.dumps(dict(completo=True,grupos=summary,hashes={p.name:sha(p) for p in out.iterdir()}),indent=2)+'\n',encoding='utf8')
    print(summary)

if __name__=='__main__':main()
