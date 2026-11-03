"""Auditoria offline de uma captura, independente do executor das trajetórias."""
from collections import Counter
from pathlib import Path
import json
import sys
from .destino import digest


def ler(pasta, arquivo):
    return json.loads((pasta / arquivo).read_text(encoding="utf8"))


def conferir(pasta):
    execucao = ler(pasta, "execucao.json")
    n = execucao["repeticoes"]
    linhas = [json.loads(x) for x in (pasta / "trajetorias.jsonl").read_text(encoding="utf8").splitlines()]
    ids = {f"{i}-{j}-{v}" for i in range(1, n + 1) for j in ("antes", "commit", "resposta")
           for v in ("estavel", "mutante")}
    if len(linhas) != len(ids) or {l["id"] for l in linhas} != ids:
        raise ValueError("matriz incompleta ou repetida")
    grupos = Counter()
    for row in linhas:
        antes, fim = row["antes_da_morte"], row["final"]
        ident, var, janela = row["id"], row["variante"], row["janela"]
        e = antes["estado"]
        esperado = 2 if var == "mutante" and janela != "antes" else 1
        originais, efeitos = row["efeitos_antes"], row["efeitos_finais"]
        if (ident != f"{ident.split('-')[0]}-{janela}-{var}" or
                row["marco_observado"] != janela or row["apos_a_morte"] != antes or
                antes["proximos"] != ["despachar"] or fim["proximos"] or
                row["revisao"]["proximos"] != ["revisar"] or
                row["revisao"]["interrupcoes"][0]["digest"] != e["digest"] or
                e["voto"] != {"autorizar": True, "chave": e["chave"], "digest": digest(e["pedido"])} or
                row["decisao_roteirizada"] != e["voto"] or row["worker"]["saida"] in (0, None) or
                len(originais) != int(janela != "antes") or len(efeitos) != esperado or
                not all(r in efeitos for r in originais) or
                len({r["chave"] for r in efeitos}) != esperado or
                any((r["digest"], r["intencao"], r["minutos"]) != (e["digest"], ident, 30) for r in efeitos) or
                fim["estado"]["recibo"] not in {r["recibo"] for r in efeitos} or
                fim["estado"]["fase"] != "confirmada"):
            raise ValueError("trilha inconsistente: " + ident)
        if var == "estavel" and (efeitos[0]["chave"] != e["chave"] or
                                fim["estado"]["origem"] != ("resposta" if janela == "antes" else "consulta")):
            raise ValueError("reconciliação não comprovada: " + ident)
        grupos[(var, janela, len(efeitos))] += 1
    c = ler(pasta, "controles.json")
    for k in ("negada", "voto_obsoleto"):
        if c[k]["efeitos"] or c[k]["primeiro"]["estado"]["fase"] != "recusada":
            raise ValueError("autorização inválida admitida")
    t = c["timeout"]
    if (t["primeiro"]["estado"]["fase"] != "desconhecida" or
            t["consulta_503"]["proximos"] != ["triagem"] or
            t["restabelecida"]["estado"]["origem"] != "consulta" or
            t["restabelecida"]["estado"]["recibo"] != t["efeitos"][0]["recibo"] or
            len(c["normal"]["efeitos"]) != 1 or c["colisao"]["status"] != 409 or
            len(c["colisao"]["efeitos"]) != 1 or
            sorted(r[0] for r in c["concorrencia"]["respostas"]) != [200, 201]):
        raise ValueError("controles auxiliares inconsistentes")
    return grupos


if __name__ == "__main__":
    for caso, quantidade in sorted(conferir(Path(sys.argv[1])).items()):
        print(*caso, quantidade)
