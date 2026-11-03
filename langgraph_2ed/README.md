# Engenharia de Agentes com LangGraph · 2ª edição

**Arquitetura, inferência e operação** · Paulo Cesar Braga

Comece com a triagem do capítulo 1. A mesma central de suporte reaparece nos capítulos 11 e 18, primeiro para investigar uma confirmação perdida e depois para comparar agente único, roteador e supervisor. O mapa ao final indica a captura que acompanha cada um dos 32 capítulos.

## Primeiro laboratório

Clone o repositório inteiro. A pasta `langgraph_2ed` usa os módulos históricos em `../exemplos`. Os comandos abaixo partem da raiz do clone e usam Windows PowerShell com Python 3.12.

```powershell
cd langgraph_2ed
py -3.12 -m venv .venv
$py = '.\.venv\Scripts\python.exe'
& $py -m pip install -r requirements.lock.txt
& $py -m pip check
$env:PYTHONPATH = (Resolve-Path '..').Path
& $py -m unittest discover -s testes -v
& $py -m bancadas.controles output/minha_triagem 1
```

Abra `output/minha_triagem/L01.json` e confronte a prioridade e a fila com a [captura do capítulo 1](output/controles_volume_v01/L01.json). Cada comando de coleta precisa de um destino novo. Para rodar os 30 controles que reaproveitam módulos da primeira edição, omita o número do capítulo e escolha outro diretório de saída.

## Percursos sem pesos

| Pergunta | Executar a partir desta pasta |
| --- | --- |
| O que fica visível após pausa, junção, revogação e descoberta MCP? | `& $py -m bancadas.fronteiras output/minhas_fronteiras` |
| Como distinguir bloqueio de ferramenta, expiração e consumo observado? | `& $py -m bancadas.operacao output/minha_operacao` |
| O que acontece nas quedas antes e depois de o destino aplicar o crédito? | `& $py -m l11.campanha output/minhas_quedas`, depois `& $py -m l11.conferir output/minhas_quedas` |
| Como retomar uma tarefa A2A após perder a confirmação? | `& $py -m bancadas.remoto output/minhas_tarefas` |
| O que muda com corpus concorrente, recibo incerto ou restauração isolada? | `& $py -m bancadas.incidentes output/meus_incidentes` |
| Como comparar dois geradores sobre os mesmos candidatos? | `& $py -m bancadas.geradores output/inferencia_volume_v01 output/meus_geradores` |

O capítulo 18 inclui uma campanha preservada com 216 trajetórias. Para recalcular os resultados sem rodar o modelo, copie a captura para um diretório novo e analise a cópia. O analisador confere as assinaturas do diário e do protocolo antes de gerar `resultados.json` e `avaliacao.csv`.

```powershell
Copy-Item output/l18_principal_v01 output/minha_analise18 -Recurse
& $py producao/analisar.py output/minha_analise18
```

## Inferência local, busca e PostgreSQL

Para geração em CPU, baixe o [GGUF Q4_K_M de Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf) e o [runtime Windows x64 b11669 de llama.cpp](https://github.com/ggml-org/llama.cpp/releases/download/b11669/llama-b11669-bin-win-cpu-x64.zip). Extraia o executável e as DLLs juntos. O laboratório verifica os hashes do GGUF e do executável. Comece por uma tarefa de desenvolvimento antes de repetir a campanha.

```powershell
$modelo = '.pesos\qwen2.5-0.5b-instruct-q4_k_m.gguf'
$exe = '.pesos\runtime_b11669\llama-server.exe'
& $py -m l18.campanha --modelo $modelo --servidor $exe --smoke --saida output/meu_smoke18
& $py -m l18.campanha --modelo $modelo --servidor $exe --saida output/minha_coleta18
& $py -m bancadas.inferencia $modelo $exe output/minha_inferencia
& $py -m bancadas.planejar $modelo $exe output/meus_planos
```

O capítulo 14 usa um ambiente separado para comparar busca lexical e densa. Use a [revisão do modelo de embeddings](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/tree/e8f8c211226b894fcb81acc59f3b34ba3efd5f42). O download requer rede. A execução seguinte usa os arquivos locais.

```powershell
py -3.12 -m venv .venv-busca
$busca = '.\.venv-busca\Scripts\python.exe'
& $busca -m pip install -r requirements.busca.txt
$rev = 'e8f8c211226b894fcb81acc59f3b34ba3efd5f42'
& $busca -c "from huggingface_hub import snapshot_download; snapshot_download('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', revision='$rev', local_dir='.pesos/$rev', allow_patterns=['*.json','model.safetensors','*.model','*.txt'], ignore_patterns=['onnx/*','openvino/*'])"
& $busca -m bancadas.busca ".pesos\$rev" output/minha_busca
```

O capítulo 27 exige Docker em execução e um terceiro ambiente. O laboratório usa a imagem PostgreSQL fixada no código, cria seu próprio contêiner, restaura em outro banco e remove o contêiner ao terminar.

```powershell
py -3.12 -m venv .venv-pg
$pg = '.\.venv-pg\Scripts\python.exe'
& $pg -m pip install -r requirements.postgres.txt
& $pg -m bancadas.capacidade output/minha_carga
```

## Interpretar os resultados

O diretório `output` contém registros históricos. Compare entradas, decisões e efeitos. Latência, hora, portas efêmeras e identificadores podem mudar entre execuções. Os formulários de [L18](output/l18_avaliacao_humana_v01/LEIA.md) e [L22](output/revisao_cega22_v01/RUBRICA.md) estão em branco para avaliação independente. As chaves de coordenação ficam com quem organiza a avaliação. Para uma coleta própria, os scripts `producao/preparar_revisao_humana.py` e `producao/revisao_cega22.py` geram os materiais de trabalho.

## Mapa dos capítulos

| Capítulo | Captura de referência |
| --- | --- |
| 1. Quando uma função é suficiente | [L01](output/controles_volume_v01/L01.json) |
| 2. Estado, entrada, saída e contexto | [L02](output/controles_volume_v01/L02.json) |
| 3. Nós, transições e decisões | [L03](output/controles_volume_v01/L03.json) |
| 4. Supersteps, reducers e junções | [L04](output/controles_volume_v01/L04.json) |
| 5. Da mensagem à proposta verificável | [L05](output/controles_volume_v01/L05.json) |
| 6. Ferramentas como fronteiras de execução | [L06](output/controles_volume_v01/L06.json) |
| 7. Ciclos, orçamento e parada | [L07](output/controles_volume_v01/L07.json) |
| 8. Planejar, executar, observar e corrigir | [L08](output/controles_volume_v01/L08.json) |
| 9. O que um checkpoint conserva | [L09](output/controles_volume_v01/L09.json) |
| 10. Interrupções e duas APIs de execução | [L10](output/controles_volume_v01/L10.json) |
| 11. A confirmação que se perde | [L11](output/l11_principal_v01) |
| 12. Concorrência, repetição e compensação | [L12](output/controles_volume_v01/L12.json) |
| 13. Construir o contexto de uma decisão | [L13](output/controles_volume_v01/L13.json) |
| 14. Recuperar o conjunto autorizado | [L14](output/controles_volume_v01/L14.json) |
| 15. Responder, citar ou abster-se | [L15](output/controles_volume_v01/L15.json) |
| 16. Memória entre threads | [L16](output/controles_volume_v01/L16.json) |
| 17. Subgrafos, escopo e duração do estado | [L17](output/controles_volume_v01/L17.json) |
| 18. Um agente, um roteador ou um supervisor? | [L18](output/l18_principal_v01) |
| 19. MCP no limite da ferramenta | [L19](output/controles_volume_v01/L19.json) |
| 20. A2A no limite da tarefa | [L20](output/controles_volume_v01/L20.json) |
| 21. Testar nós e trajetórias sem congelar o grafo | [L21](output/controles_volume_v01/L21.json) |
| 22. Avaliação de tarefas abertas | [L22](output/controles_volume_v01/L22.json) |
| 23. Guardrails ao longo da trajetória | [L23](output/controles_volume_v01/L23.json) |
| 24. Identidade, autorização e aprovação vinculada | [L24](output/controles_volume_v01/L24.json) |
| 25. API, streaming e supervisão | [L25](output/controles_volume_v01/L25.json) |
| 26. Medir espera, geração e consumo | [L26](output/controles_volume_v01/L26.json) |
| 27. Implantação, capacidade e persistência concorrente | [L27](output/controles_volume_v01/L27.json) |
| 28. Evoluir o esquema com trabalho em andamento | [L28](output/controles_volume_v01/L28.json) |
| 29. Assistente de conhecimento com atualização concorrente | [L29](output/controles_volume_v01/L29.json) |
| 30. Agente de operações supervisionado | [L30](output/controles_volume_v01/L30.json) |
| 31. Central com especialistas remotos | [L31](output/controles_volume_v01/L31.json) |
| 32. Incidente, restauração e nova liberação | [L32](output/controles_volume_v01/L32.json) |

A [raiz do repositório](../README.md) mantém as instruções da 1ª edição e a nota de direitos dos materiais.
