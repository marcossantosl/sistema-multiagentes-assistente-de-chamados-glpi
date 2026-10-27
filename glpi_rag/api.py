"""API HTTP + página do técnico.  Rodar:  python -m glpi_rag servir"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from google.genai import errors as erros_gemini
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .agentes import ErroAgente
from .config import config
from .indice import Indice
from .orquestrador import Orquestrador

log = logging.getLogger(__name__)
app = FastAPI(title="Assistente de Chamados GLPI", version="1.0")
indice = Indice(config.db_path)
_orq: Orquestrador | None = None


def orquestrador() -> Orquestrador:
    global _orq
    if _orq is None:
        _orq = Orquestrador(indice)
    return _orq


class PedidoSugestao(BaseModel):
    ticket_id: int | None = None
    titulo: str | None = None
    descricao: str | None = None


@app.get("/")
def pagina():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/status")
def status():
    return {**indice.total(), "ultima_sincronizacao": indice.meta("ultima_sincronizacao"),
            "glpi": config.glpi_url, "glpi_configurado": config.glpi_configurado,
            "modelo": config.modelo}


@app.get("/api/busca")
def busca(q: str, limite: int = 10):
    return [{k: d[k] for k in ("id", "titulo", "status", "categoria", "rrf")}
            for d in indice.buscar_multi([q], limite=limite)]


@app.post("/api/sugestoes")
def sugestoes(pedido: PedidoSugestao):
    orq = orquestrador()
    if pedido.ticket_id:
        try:
            chamado = orq.carregar_chamado(pedido.ticket_id)
        except LookupError as e:
            raise HTTPException(404, str(e))
    elif pedido.descricao or pedido.titulo:
        chamado = {"titulo": pedido.titulo or "", "descricao": pedido.descricao or ""}
    else:
        raise HTTPException(422, "Informe ticket_id ou titulo/descricao")
    try:
        return orq.sugerir(chamado)
    except erros_gemini.ClientError as e:
        if e.code == 429:
            raise HTTPException(429, "Limite do nível gratuito do Gemini atingido; tente em instantes")
        raise HTTPException(502, f"Erro na API do Gemini ({e.code}): {e.message}")
    except erros_gemini.APIError as e:
        raise HTTPException(502, f"Erro na API do Gemini ({e.code})")
    except ErroAgente as e:
        raise HTTPException(502, str(e))


@app.post("/api/sincronizar")
def sincronizar(tarefas: BackgroundTasks, completo: bool = False):
    if not config.glpi_configurado:
        raise HTTPException(400, "GLPI não configurado no .env")
    from .sincronizar import sincronizar_glpi

    tarefas.add_task(sincronizar_glpi, indice, completo)
    return {"iniciado": True, "completo": completo}
