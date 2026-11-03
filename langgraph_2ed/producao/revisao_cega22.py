"""Material de avaliação semântica separado da chave de coordenação."""
import argparse
import csv
import json
from pathlib import Path
from random import Random

BOOK=Path(__file__).resolve().parents[1]


def preparar(saida):
    saida.mkdir(parents=True,exist_ok=False)
    pasta=BOOK/"output/inferencia_volume_v01"
    protocolo=json.loads((pasta/"protocolo.json").read_text(encoding="utf8"))
    referencia={x[0]:x[1:3] for x in protocolo["reserva"]}
    dados=json.loads((pasta/"resultados.json").read_text(encoding="utf8"))["L15_L22"]
    linhas=list(dados);Random(411).shuffle(linhas);chave=[]
    for revisor in ("A","B"):
        with (saida/f"revisor_{revisor}.csv").open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.writer(f);w.writerow(["item","pergunta","evidencia_admissivel","resposta","sustentacao","utilidade","justificativa"])
            for i,x in enumerate(linhas,1):
                ident=f"R-{i:03}";pergunta,doc=referencia[x["id"]]
                w.writerow([ident,pergunta,doc,x["resposta"],"","",""])
                if revisor=="A":
                    chave.append({"item":ident,**{k:x[k] for k in ("id","arquitetura","seed","regra","juiz")}})
    (saida/"coordenacao").mkdir()
    (saida/"coordenacao/chave.json").write_text(json.dumps(chave,indent=2),encoding="utf8")
    (saida/"RUBRICA.md").write_text("""# Leitura independente

Entregue a cada pessoa apenas sua própria planilha e esta rubrica. Examine a resposta à luz da pergunta e da evidência admissível. Para sustentação, marque integral, parcial, ausente ou abstenção justificada. Para utilidade, marque atende, atende em parte ou falha. Registre a frase concreta que motivou cada decisão. A fonte admissível apresentada aqui é a referência da avaliação, independentemente do que a arquitetura recebeu. Não consulte a coordenação nem as notas do outro leitor. Conserve discordâncias antes de adjudicar. Coleta humana pendente.
""",encoding="utf8")


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("saida",type=Path);preparar(p.parse_args().saida)
