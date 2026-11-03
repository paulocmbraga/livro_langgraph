"""Inferência CPU com modelo e binário identificados. O processo pertence ao ensaio."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import Request, urlopen

MODEL = 'qwen2.5-0.5b-instruct-q4_k_m.gguf'
MODEL_SHA = '74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db'
SERVER_SHA = '6a4635aeb35656153d4bfeeddf761d24ed84aada9c9108d580737cbed465141b'

def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def http(url, data=None, timeout=30):
    payload = None if data is None else json.dumps(data, ensure_ascii=False).encode()
    with urlopen(Request(url, data=payload, headers={'Content-Type':'application/json'}), timeout=timeout) as r:
        return json.load(r)

@contextmanager
def servidor(modelo, exe):
    if sha(modelo) != MODEL_SHA or sha(exe) != SERVER_SHA:
        raise ValueError('modelo ou runtime fora do protocolo Windows CPU b11669')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    cmd = [str(Path(exe).resolve()), '-m', str(Path(modelo).resolve()), '--host','127.0.0.1','--port',str(port),
           '-t','4','-tb','4','-c','2048','-np','1','-ngl','0','--no-webui']
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        for _ in range(180):
            if proc.poll() is not None:
                raise RuntimeError('llama-server terminou antes de ficar disponível')
            try:
                if http(url+'/health', timeout=1).get('status') == 'ok':
                    break
            except OSError:
                pass
            time.sleep(.25)
        else:
            raise TimeoutError('inicialização do servidor')
        yield url
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

class Limite(Exception):
    pass

class Modelo:
    def __init__(self, url, seed, plano):
        self.url, self.seed, self.plano = url, seed, plano
        self.chamadas = []
        self.inicio = time.monotonic()

    def restante(self):
        segundos = self.plano['timeout_s'] - (time.monotonic() - self.inicio)
        if segundos <= 0:
            raise Limite('tempo')
        return segundos

    def gerar(self, papel, instrucao, pedido, entregas, alternativas=''):
        n = len(self.chamadas)
        if n >= self.plano['chamadas']:
            raise Limite('chamadas')
        limit = 2 if alternativas else self.plano['saida_max']
        user = json.dumps({'pedido':pedido,'observações':entregas}, ensure_ascii=False)
        prompt = f'<|im_start|>system\n{instrucao}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n'
        ids = http(self.url+'/tokenize', {'content':prompt,'add_special':False,'parse_special':True},
                   self.restante())['tokens']
        used = sum(c['entrada'] + (c['saida'] or 0) for c in self.chamadas)
        if used + len(ids) + limit > self.plano['tokens']:
            raise Limite('tokens')
        seed = self.seed + n
        req = dict(prompt=ids, seed=seed, temperature=self.plano['temperatura'],
                   n_predict=limit, cache_prompt=False, stop=['<|im_end|>'])
        if alternativas:
            req['grammar'] = 'root ::= ' + ' | '.join(json.dumps(c) for c in alternativas)
        call = dict(papel=papel,seed=seed,entrada=len(ids),saida=None,prompt=prompt,opcoes=alternativas)
        self.chamadas.append(call)
        start = time.monotonic()
        try:
            result = http(self.url+'/completion',req,self.restante())
            ans = result['content'].strip()
            call.update(saida=result['tokens_predicted'],texto=ans,stop=result.get('stop_type'),
                        ms=round((time.monotonic()-start)*1000,2))
            self.restante()
            if alternativas and (len(ans)!=1 or ans not in alternativas):
                raise ValueError('resposta fora da gramática')
            return ans
        except Exception as exc:
            call['erro'] = f'{type(exc).__name__}: {exc}'
            raise
