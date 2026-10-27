"""Ingestão: GLPI (ou arquivo JSON) -> índice local."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .glpi_client import GLPIClient
from .indice import Indice

log = logging.getLogger(__name__)


def sincronizar_glpi(indice: Indice, completo: bool = False, limite: int | None = None) -> int:
    desde = None if completo else indice.meta("ultima_sincronizacao")
    inicio = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    with GLPIClient() as glpi:
        lote: list[dict] = []
        for t in glpi.listar_chamados(desde=desde):
            lote.append(glpi.chamado_completo(t))
            if len(lote) >= 50:
                n += indice.salvar(lote)
                log.info("%d chamados indexados", n)
                lote = []
            if limite and n + len(lote) >= limite:
                break
        n += indice.salvar(lote)
    if not limite:  # uma carga parcial não pode marcar a base como sincronizada
        indice.meta("ultima_sincronizacao", inicio)
    return n


def importar_json(indice: Indice, arquivo: Path | str) -> int:
    """Importa chamados já normalizados (útil para testes ou exportações do GLPI)."""
    dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    return indice.salvar(dados)
