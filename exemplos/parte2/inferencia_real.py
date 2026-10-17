"""Campanha pequena e explícita contra um modelo já instalado no Ollama local."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import httpx
from exemplos.parte2.cap05 import executar
from exemplos.parte2.modelos import OllamaLocal
from exemplos.parte2.solucoes import metricas_propostas


CASOS = [
    ("A-501", "O portal deixou de funcionar para 80 pessoas.", "falha", 80),
    ("A-502", "Como configurar a VPN? A dúvida é de 3 pessoas.", "orientacao", 3),
    ("A-503", "Solicito mudar a configuração para 20 pessoas.", "mudanca", 20),
]


def campanha(modelo, destino, repeticoes):
    if not 1 <= repeticoes <= 10:
        raise ValueError("repeticoes_entre_1_e_10")
    destino.mkdir(parents=True, exist_ok=False)
    estado = destino/"estado.json"
    estado.write_text('{"completo":false}', encoding="utf8")
    with httpx.Client(timeout=5, trust_env=False) as cliente:
        versao = cliente.get("http://127.0.0.1:11434/api/version")
        versao.raise_for_status()
        inventario = cliente.get("http://127.0.0.1:11434/api/tags")
        inventario.raise_for_status()
    correspondentes = [m for m in inventario.json().get("models", [])
                       if modelo in (m.get("name"), m.get("model"))]
    if len(correspondentes) != 1:
        raise ValueError("use_nome_exato_de_um_modelo_ja_instalado")
    resultados = []
    for repeticao in range(repeticoes):
        for id, texto, tipo, usuarios in CASOS:
            inicio = time.monotonic()
            r = executar({"id": id, "descricao": texto}, OllamaLocal(modelo))
            valida = r["motivo"] == "proposta_valida"
            correta = valida and r["proposta"]["tipo"] == tipo and r["proposta"]["usuarios"] == usuarios
            resultados.append({
                "id": id, "entrada": texto, "repeticao": repeticao,
                "valida": valida, "correta": correta, "motivo": r["motivo"],
                "proposta": r.get("proposta"), "registro": r.get("registro"),
                "duracao_s": time.monotonic() - inicio,
                "esperado": {"tipo": tipo, "usuarios": usuarios}})
    dados = {"inferencia_real": True, "instante_utc": datetime.now(timezone.utc).isoformat(),
             "modelo": correspondentes[0], "servidor": versao.json(),
             "configuracao": {"temperatura": 0, "num_predict": 512, "timeout_s": 60},
             "schema": "Proposta do capítulo 5", "resultados": resultados,
             "metricas": metricas_propostas(resultados)}
    dados["fontes"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in Path(__file__).parent.glob("*.py")}
    (destino/"resultado.json").write_text(
        json.dumps(dados, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf8")
    estado.write_text('{"completo":true}', encoding="utf8")
    return dados


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", required=True)
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--repeticoes", type=int, default=1)
    args = parser.parse_args()
    r = campanha(args.modelo, args.saida, args.repeticoes)
    print(json.dumps(r["metricas"], ensure_ascii=False, indent=2))
