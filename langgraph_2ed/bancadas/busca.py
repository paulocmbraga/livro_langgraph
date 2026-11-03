"""L14. Comparação pareada lexical/densa com filtragem antes do ranking."""
import argparse
from importlib.metadata import version
from pathlib import Path
import json
import re
from sentence_transformers import SentenceTransformer
import numpy as np

REV="e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
DOCS=[("D1","Norte",2,"Para recuperar a senha, use o portal de identidade."),
      ("D2","Norte",2,"Para corrigir falhas da rede privada, reinstale o cliente VPN."),
      ("D3","Sul",2,"Para restaurar a senha, use o código reservado do Sul."),
      ("D4","Norte",1,"Senha temporária distribuída por telefone."),
      ("D5","Norte",2,"Para ajustar o turno da noite, contate a escala.")]
PERGUNTAS=[("Como restaurar minha credencial?","D1"),("Como corrijo a conexão remota?","D2"),
           ("Posso alterar meu horário?","D5"),("Preciso reinstalar o cliente VPN","D2")]


def executar(modelo,saida):
    saida.mkdir(parents=True,exist_ok=False)
    encoder=SentenceTransformer(str(modelo),device="cpu",local_files_only=True)
    elegiveis=[d for d in DOCS if d[1:3]==("Norte",2)]
    matriz=encoder.encode([d[3] for d in elegiveis],normalize_embeddings=True)
    def termos(t):
        return set(re.findall(r"\w+",t.lower()))
    linhas=[]
    for pergunta,gold in PERGUNTAS:
        v=encoder.encode([pergunta],normalize_embeddings=True)[0]
        escores={"lexical":[len(termos(pergunta)&termos(d[3])) for d in elegiveis],
                 "densa":[float(y) for y in matriz@v]}
        for metodo,s in escores.items():
            ordem=sorted(range(len(s)),key=lambda i:(-s[i],elegiveis[i][0]))
            ranking=[elegiveis[i][0] for i in ordem]
            linhas.append({"pergunta":pergunta,"metodo":metodo,"ouro":gold,"ranking":ranking,
                           "escores":[round(s[i],5) for i in ordem],"hit1":ranking[0]==gold})
    registro={"modelo":"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2","revisao":REV,
              "sentence_transformers":version("sentence-transformers"),"torch":version("torch"),
              "dimensoes":int(matriz.shape[1]),"documentos":DOCS,"linhas":linhas}
    (saida/"resultado.json").write_text(json.dumps(registro,indent=2,ensure_ascii=False),encoding="utf8")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("modelo",type=Path);p.add_argument("saida",type=Path)
    a=p.parse_args()
    if a.modelo.name!=REV:
        raise ValueError("usar snapshot da revisão fixada")
    executar(a.modelo,a.saida)
