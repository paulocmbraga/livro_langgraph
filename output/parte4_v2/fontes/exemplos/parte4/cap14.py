"""Memória entre threads: serviço local sobre InMemoryStore."""
from copy import deepcopy
from dataclasses import dataclass
import json
from threading import RLock
from typing import Literal, TypedDict
from pydantic import BaseModel, ConfigDict, Field
from langgraph.graph import START, END, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.memory import InMemoryStore


# trecho:contrato
@dataclass(frozen=True)
class Identidade:
    organizacao: str
    usuario: str


def namespace(identidade):
    campos = (identidade.organizacao, identidade.usuario)
    if not all(isinstance(v, str) and v.strip() for v in campos):
        raise ValueError("identidade_incompleta")
    return ("memorias", *campos)


class Registro(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    valor: str = Field(min_length=1, max_length=200)
    tipo: Literal["preferencia", "fato"]
    fonte: str = Field(min_length=1)
    revisao_fonte: int = Field(ge=1)
    observado_em: int = Field(ge=0)
    expira_em: int = Field(ge=1)
# fim:contrato


class Conflito(ValueError):
    pass


class Memorias:
    def __init__(self, store=None):
        self.store = store if store is not None else InMemoryStore()
        self.lock = RLock()

    # trecho:escrita
    def escrever(self, identidade, chave, dados, esperada, agora):
        registro = Registro.model_validate(dados)
        if (not isinstance(chave, str) or not chave.strip()
                or type(esperada) is not int or esperada < 0
                or type(agora) is not int or agora < 0):
            raise ValueError("entrada_invalida")
        if not registro.observado_em <= agora < registro.expira_em:
            raise ValueError("intervalo_invalido")
        ns = namespace(identidade)
        with self.lock:
            item = self.store.get(ns, chave)
            atual = item.value["versao"] if item else 0
            if atual != esperada:
                raise Conflito("versao_divergente")
            novo = {"versao": atual + 1, "apagada": False,
                    "dados": registro.model_dump()}
            self.store.put(ns, chave, deepcopy(novo))
            return deepcopy(novo)
    # fim:escrita

    # trecho:leitura
    def ler(self, identidade, chave, agora):
        if type(agora) is not int or agora < 0:
            raise ValueError("instante_invalido")
        with self.lock:
            item = self.store.get(namespace(identidade), chave)
            if item is None or item.value["apagada"]:
                return None
            registro = Registro.model_validate(item.value["dados"])
            if not registro.observado_em <= agora < registro.expira_em:
                return None
            return deepcopy(item.value)

    def esquecer(self, identidade, chave, esperada):
        ns = namespace(identidade)
        with self.lock:
            item = self.store.get(ns, chave)
            atual = item.value["versao"] if item else 0
            if type(esperada) is not int or atual != esperada:
                raise Conflito("versao_divergente")
            tombstone = {"versao": atual + 1, "apagada": True, "dados": None}
            self.store.put(ns, chave, tombstone)
            return deepcopy(tombstone)
    # fim:leitura

    def expurgar_vencidas(self, identidade, agora):
        if type(agora) is not int or agora < 0:
            raise ValueError("instante_invalido")
        # Materialize todas as páginas antes de modificar os registros.
        ns, itens, offset = namespace(identidade), [], 0
        with self.lock:
            while True:
                lote = self.store.search(ns, limit=50, offset=offset)
                itens.extend(lote)
                if len(lote) < 50:
                    break
                offset += len(lote)
            vencidas = [i for i in itens if not i.value["apagada"]
                        and i.value["dados"]["expira_em"] <= agora]
            for i in vencidas:
                self.esquecer(identidade, i.key, i.value["versao"])
            return len(vencidas)


# trecho:grafo
class Estado(TypedDict, total=False):
    chave: str
    memoria: dict | None


@dataclass(frozen=True)
class Contexto:
    identidade: Identidade
    servico: Memorias
    agora: int


def criar_grafo(memoria, saver):
    def lembrar(s, runtime: Runtime[Contexto]):
        ctx = runtime.context
        if runtime.store is not ctx.servico.store:
            raise ValueError("store_incoerente")
        return {"memoria": ctx.servico.ler(
            ctx.identidade, s["chave"], ctx.agora)}
    g = StateGraph(Estado, context_schema=Contexto)
    g.add_node("lembrar", lembrar)
    g.add_edge(START, "lembrar")
    g.add_edge("lembrar", END)
    return g.compile(store=memoria.store, checkpointer=saver)
# fim:grafo


def preferencia(valor="pt-BR", expira=20):
    return {"valor": valor, "tipo": "preferencia", "fonte": "revisao-ana-01",
            "revisao_fonte": 1, "observado_em": 1, "expira_em": expira}


def executar():
    from langgraph.checkpoint.memory import InMemorySaver
    m, identidade = Memorias(), Identidade("aurora", "ana")
    m.escrever(identidade, "idioma", preferencia(), 0, 1)
    g = criar_grafo(m, InMemorySaver())
    saidas = []
    for thread in ("atendimento-1", "atendimento-2"):
        cfg = {"configurable": {"thread_id": thread}}
        r = g.invoke({"chave": "idioma"}, cfg,
                     context=Contexto(identidade, m, 2))
        saidas.append(r["memoria"]["dados"]["valor"])
    m.esquecer(identidade, "idioma", 1)
    return {"duas_threads": saidas, "leitura_apos_esquecer":
            m.ler(identidade, "idioma", 2),
            "checkpoint_antigo_ainda_tem_copia":
            g.get_state(cfg).values["memoria"] is not None}


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2))
