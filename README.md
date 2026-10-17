# Engenharia de Agentes com LangGraph

**Fundamentos, laboratórios e arquiteturas para produção** — Paulo Cesar Braga

Código complementar da primeira edição. Reúne os exemplos em Python dos 24 capítulos,
os laboratórios, os testes e capturas de referência. A obra completa é distribuída
separadamente. Os arquivos do livro e as artes de capa não integram este repositório.

## Preparar o ambiente

Use Python **3.12**. Na raiz do repositório, no PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s testes -v
```

Em Linux/macOS, substitua `py -3.12` por `python3.12` e
`.\.venv\Scripts\python.exe` por `.venv/bin/python`.
O lock fixa LangGraph 1.2.15 e suas dependências; uma versão diferente exige nova validação.

## Começar e avançar

```powershell
.\.venv\Scripts\python.exe -m exemplos.cap01
.\.venv\Scripts\python.exe -m exemplos.laboratorios --capitulo 4
.\.venv\Scripts\python.exe -m exemplos.parte2.cap05
.\.venv\Scripts\python.exe -m exemplos.parte3.cap09
.\.venv\Scripts\python.exe -m exemplos.parte4.cap13
.\.venv\Scripts\python.exe -m exemplos.parte5.cap17
.\.venv\Scripts\python.exe -m exemplos.parte6.cap21
.\.venv\Scripts\python.exe -m scripts.avancados.capturar --conferir
```

Os diretórios `parte2` a `parte6` contêm os módulos dos capítulos seguintes.
`exemplos/avancados` reúne guardrails, planejamento, coordenação, MCP e A2A.
`exemplos/apendices` contém as demonstrações dos apêndices.
Use `--help` nos módulos de laboratório para consultar seus argumentos.

Os testes e laboratórios principais usam respostas e dados preparados, sem exigir
chave de API, GPU ou inferência de um modelo. MCP usa subprocesso via stdio e A2A usa
HTTP local. As aplicações da Parte VI usam HTTP em loopback e SQLite; são demonstrações
didáticas locais. Integrações opcionais dependem dos serviços descritos no livro.

## Capturas e verificações

As pastas `output/reescrita_v2`, `parte2_v1`, `parte3_v1`, `parte4_v2`, `parte5_v2`,
`parte6_v2`, `apendices_v1` e `avancados_v04` preservam resultados de referência,
fontes capturadas e hashes. A captura avançada registra 262 testes e seis demonstrações.
Capturas antigas podem apontar para versões históricas preservadas em `fontes/`.
Não sobrescreva essas pastas ao executar seus próprios experimentos.

Execute a suíte integral no seu ambiente para produzir evidência nova. A verificação
`scripts.avancados.capturar --conferir` confere os hashes da captura, sem repetir os ensaios.
Os scripts `conferir_livro.py` e `*/conferir.py` foram preservados para rastreabilidade,
mas a conferência editorial de capítulos depende dos manuscritos privados. Eles não
são necessários para executar exemplos, laboratórios e testes deste pacote.
Comandos `producao/*` citados no livro também pertencem à produção editorial privada.

O arquivo `exemplos/parte6/interface.html` acompanha o servidor local descrito no capítulo 21.
Não exponha o servidor didático na internet como se fosse uma implantação de produção.

## Direitos

© 2026 Paulo Cesar Braga. Todos os direitos reservados. Este pacote não atribui
automaticamente uma licença de código aberto. As bibliotecas utilizadas conservam
suas próprias licenças. LangGraph e demais marcas citadas pertencem a seus titulares.
