"""Orquestrador: coordena os agentes e o índice para um chamado."""
from __future__ import annotations

import logging
import time

from google import genai

from .agentes import (AgenteAvaliador, AgenteRevisor, AgenteSolucionador, AgenteTriagem,
                      criar_cliente)
from .config import Config, config as config_padrao
from .indice import Indice
from .texto import cortar_final

log = logging.getLogger(__name__)

RELEVANCIA_MINIMA = 5
MAX_SIMILARES = 8
MAX_CANDIDATOS = 20


class Orquestrador:
    def __init__(self, indice: Indice | None = None, cliente: genai.Client | None = None,
                 cfg: Config = config_padrao):
        self.cfg = cfg
        self.indice = indice or Indice(cfg.db_path)
        cliente = cliente or criar_cliente(cfg.gemini_api_key)
        self.triagem = AgenteTriagem(cliente, cfg.modelo)
        self.avaliador = AgenteAvaliador(cliente, cfg.modelo)
        self.solucionador = AgenteSolucionador(cliente, cfg.modelo)
        self.revisor = AgenteRevisor(cliente, cfg.modelo)

    def carregar_chamado(self, ticket_id: int) -> dict:
        """Busca o chamado no GLPI (dados frescos); se não der, usa o índice local."""
        if self.cfg.glpi_configurado:
            from .glpi_client import GLPIClient

            try:
                with GLPIClient(self.cfg) as glpi:
                    return glpi.chamado_completo(ticket_id)
            except Exception as e:  # rede, permissão, etc.
                log.warning("GLPI indisponível (%s); usando índice local", e)
        chamado = self.indice.obter(ticket_id)
        if not chamado:
            raise LookupError(f"Chamado {ticket_id} não encontrado")
        return chamado

    def sugerir(self, chamado: dict) -> dict:
        rastro: list[dict] = []

        def etapa(nome: str, inicio: float, agente=None, **extra):
            rastro.append({"etapa": nome, "segundos": round(time.perf_counter() - inicio, 2),
                           **({"tokens": agente.uso} if agente else {}), **extra})

        t = time.perf_counter()
        analise = self.triagem.executar(chamado)
        etapa("triagem", t, self.triagem, consultas=analise.consultas_busca)

        t = time.perf_counter()
        consultas = [*analise.consultas_busca, chamado.get("titulo", ""),
                     " ".join(analise.mensagens_erro)]
        candidatos = self.indice.buscar_multi([c for c in consultas if c.strip()],
                                              limite=MAX_CANDIDATOS, excluir=chamado.get("id"))
        etapa("recuperacao", t, candidatos=len(candidatos))

        similares: list[dict] = []
        if candidatos:
            t = time.perf_counter()
            notas = {a.id: a for a in self.avaliador.executar(chamado, analise, candidatos).avaliacoes}
            etapa("avaliacao", t, self.avaliador)
            por_id = {c["id"]: c for c in candidatos}
            for tid, nota in sorted(notas.items(), key=lambda x: -x[1].relevancia):
                if tid in por_id and nota.relevancia >= RELEVANCIA_MINIMA:
                    similares.append({**por_id[tid], "relevancia": nota.relevancia,
                                      "motivo": nota.motivo})
            similares = similares[:MAX_SIMILARES]

        t = time.perf_counter()
        proposta = self.solucionador.executar(chamado, analise, similares)
        etapa("solucao", t, self.solucionador)

        t = time.perf_counter()
        revisao = self.revisor.executar(chamado, proposta, similares)
        etapa("revisao", t, self.revisor)

        return {
            "chamado": {k: chamado.get(k) for k in ("id", "titulo", "categoria", "status")},
            "analise": analise.model_dump(),
            "resumo": revisao.resumo_para_tecnico,
            "diagnostico": proposta.diagnostico,
            "solucoes": [s.model_dump() for s in revisao.solucoes],
            "alertas": revisao.alertas,
            "perguntas_ao_usuario": proposta.perguntas_ao_usuario,
            "chamados_semelhantes": [
                {"id": s["id"], "titulo": s["titulo"], "status": s["status"],
                 "categoria": s["categoria"], "data_abertura": s["data_abertura"],
                 "relevancia": s["relevancia"], "motivo": s["motivo"],
                 "solucao": s["solucao"] or cortar_final(s.get("acompanhamentos") or "", 1500),
                 "link": self.cfg.link_chamado(s["id"])}
                for s in similares],
            "rastro": rastro,
        }
