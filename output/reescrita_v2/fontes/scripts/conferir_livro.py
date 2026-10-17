"""Sincroniza trechos e verifica os documentos ativos; não lê a edição arquivada."""
import argparse
import ast
from pathlib import Path
import re
import textwrap

ROOT=Path(__file__).resolve().parents[1]
PADRAO=re.compile(r"<!-- trecho:([^#\s]+)#([^\s]+) -->\n.*?\n<!-- /trecho -->",re.S)


def extrair(arquivo,nome):
    texto=(ROOT/arquivo).read_text(encoding="utf8")
    achado=re.search(r"(?ms)^\s*# trecho:"+re.escape(nome)+r"\n(.*?)^\s*# fim:"+re.escape(nome)+r"\s*$",texto)
    if achado is None:
        raise ValueError(f"Trecho ausente: {arquivo}#{nome}")
    return textwrap.dedent(achado[1]).rstrip()


def ancora(titulo):
    titulo=re.sub(r"[`*_]","",titulo).strip().lower()
    return re.sub(r"[^\w\- ]","",titulo).replace(" ","-")


def conferir_links(caminho):
    texto=caminho.read_text(encoding="utf8")
    for _, destino in re.findall(r"\[([^\]]+)\]\(([^)]+)\)",texto):
        if destino.startswith(("https://","http://","mailto:")):
            continue
        nome,_,fragmento=destino.partition("#")
        alvo=(caminho.parent/nome).resolve() if nome else caminho
        if not alvo.is_file():
            raise ValueError(f"Link sem arquivo: {caminho.name}: {destino}")
        if fragmento and alvo.suffix==".md":
            conteudo=alvo.read_text(encoding="utf8")
            ancoras={ancora(t) for t in re.findall(r"(?m)^#+ (.+)$",conteudo)}
            ancoras.update(re.findall(r'<a id="([^"]+)"',conteudo))
            if fragmento not in ancoras:
                raise ValueError(f"Âncora ausente: {destino}")


def main(atualizar=False):
    quantidade=0
    if len(list(ROOT.glob("livro/capitulos/*.md")))!=4 or len(list(ROOT.glob("livro/solucoes/*.md")))!=4:
        raise ValueError("Esta redação deve conter quatro capítulos e quatro cadernos de soluções")
    documentos=[ROOT/"README.md",*ROOT.glob("livro/**/*.md"),*ROOT.glob("editorial/*.md")]
    for caminho in documentos:
        texto=caminho.read_text(encoding="utf8")
        def substituir(match):
            nonlocal quantidade
            quantidade+=1
            return f"<!-- trecho:{match[1]}#{match[2]} -->\n```python\n{extrair(match[1],match[2])}\n```\n<!-- /trecho -->"
        novo=PADRAO.sub(substituir,texto)
        if atualizar and texto!=novo:
            caminho.write_text(novo,encoding="utf8",newline="\n")
        elif texto!=novo:
            raise ValueError("Trecho desatualizado: "+str(caminho))
        if caminho.parent.name=="capitulos":
            exercicios=novo.split('<a id="exercicios"></a>')[-1].split("## Referências")[0]
            numeros=re.findall(r"(?m)^(\d+)\. \*\*",exercicios)
            if numeros!=[str(i) for i in range(1,13)]:
                raise ValueError("Exercícios incompletos: "+caminho.name)
        if caminho.parent.name=="solucoes":
            numeros=re.findall(r"(?m)^## (\d+)\.",novo)
            if numeros!=[str(i) for i in range(1,13)]:
                raise ValueError("Soluções incompletas: "+caminho.name)
        conferir_links(caminho)
    for pasta in ("exemplos","scripts","testes"):
        for caminho in ROOT.glob(pasta+"/*.py"):
            ast.parse(caminho.read_text(encoding="utf8"))
    print(f"Conferência concluída: {len(documentos)} documentos; {quantidade} trechos; 48 exercícios e 48 soluções; links e âncoras.")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atualizar",action="store_true")
    main(parser.parse_args().atualizar)
