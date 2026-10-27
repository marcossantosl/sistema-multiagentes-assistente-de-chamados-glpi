"""Cliente da API REST do GLPI (apirest.php).

Para habilitar no GLPI: Configurar > Geral > API > "Habilitar API REST" e criar um
cliente de API (App-Token). O token do usuário fica em Preferências > Chaves de acesso remoto.
"""
from __future__ import annotations

import logging
from typing import Iterator

import requests

from .config import Config, config as config_padrao
from .texto import limpar_html

log = logging.getLogger(__name__)

STATUS = {1: "Novo", 2: "Em atendimento (atribuído)", 3: "Em atendimento (planejado)",
          4: "Pendente", 5: "Solucionado", 6: "Fechado"}


class ErroGLPI(RuntimeError):
    pass


class GLPIClient:
    def __init__(self, cfg: Config = config_padrao, timeout: int = 30):
        if not cfg.glpi_configurado:
            raise ErroGLPI("Defina GLPI_USER_TOKEN (ou GLPI_LOGIN/GLPI_SENHA) no .env")
        self.cfg = cfg
        self.timeout = timeout
        self.http = requests.Session()
        self.http.verify = cfg.glpi_verificar_ssl
        self.session_token: str | None = None

    # ---- sessão -------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.cfg.glpi_app_token:
            h["App-Token"] = self.cfg.glpi_app_token
        if self.session_token:
            h["Session-Token"] = self.session_token
        return h

    def __enter__(self) -> "GLPIClient":
        self.iniciar_sessao()
        return self

    def __exit__(self, *_exc) -> None:
        self.encerrar_sessao()

    def iniciar_sessao(self) -> None:
        headers = self._headers()
        auth = None
        if self.cfg.glpi_user_token:
            headers["Authorization"] = f"user_token {self.cfg.glpi_user_token}"
        else:
            auth = (self.cfg.glpi_login, self.cfg.glpi_senha)
        r = self.http.get(f"{self.cfg.glpi_api}/initSession", headers=headers, auth=auth,
                          timeout=self.timeout)
        if r.status_code != 200:
            raise ErroGLPI(f"initSession falhou ({r.status_code}): {r.text[:300]}")
        self.session_token = r.json()["session_token"]

    def encerrar_sessao(self) -> None:
        if self.session_token:
            try:
                self.http.get(f"{self.cfg.glpi_api}/killSession", headers=self._headers(),
                              timeout=self.timeout)
            finally:
                self.session_token = None

    def _get(self, caminho: str, **params) -> requests.Response:
        r = self.http.get(f"{self.cfg.glpi_api}/{caminho}", headers=self._headers(),
                          params=params, timeout=self.timeout)
        if r.status_code not in (200, 206):
            raise ErroGLPI(f"GET {caminho} falhou ({r.status_code}): {r.text[:300]}")
        return r

    # ---- chamados -----------------------------------------------------------
    def listar_chamados(self, desde: str | None = None, lote: int = 100) -> Iterator[dict]:
        """Percorre os chamados do mais recente para o mais antigo (por date_mod).

        Com `desde` (formato 'AAAA-MM-DD HH:MM:SS'), para ao chegar em chamados não
        modificados desde então — é o que torna a sincronização incremental.
        """
        inicio = 0
        while True:
            r = self._get("Ticket", range=f"{inicio}-{inicio + lote - 1}", sort="date_mod",
                          order="DESC", expand_dropdowns="true", is_deleted=0)
            itens = r.json()
            if not itens:
                return
            for t in itens:
                if desde and (t.get("date_mod") or "") <= desde:
                    return
                yield t
            # Content-Range: 0-99/1234
            total = int(r.headers.get("Content-Range", "0-0/0").split("/")[-1] or 0)
            inicio += lote
            if inicio >= total:
                return

    def obter_chamado(self, ticket_id: int) -> dict:
        return self._get(f"Ticket/{ticket_id}", expand_dropdowns="true").json()

    def _sub_itens(self, ticket_id: int, tipo: str) -> list[dict]:
        try:
            dados = self._get(f"Ticket/{ticket_id}/{tipo}", range="0-200",
                              expand_dropdowns="true").json()
        except ErroGLPI as e:  # perfis sem permissão para tarefas, por exemplo
            log.debug("Ignorando %s do chamado %s: %s", tipo, ticket_id, e)
            return []
        if not isinstance(dados, list):
            return []
        return sorted(dados, key=lambda d: (d.get("date") or "", d.get("id") or 0))

    def chamado_completo(self, ticket: dict | int) -> dict:
        """Devolve o chamado normalizado, com solução, acompanhamentos e tarefas."""
        t = self.obter_chamado(ticket) if isinstance(ticket, int) else ticket
        tid = int(t["id"])
        solucoes = [limpar_html(s.get("content")) for s in self._sub_itens(tid, "ITILSolution")]
        # Só o papel vai para o texto (não o nome), para não mandar dados pessoais à IA.
        respostas = [(str(f.get("users_id") or "").lower() in self.cfg.tecnicos,
                      limpar_html(f.get("content")))
                     for f in self._sub_itens(tid, "ITILFollowup")]
        respostas = [(tec, texto) for tec, texto in respostas if texto]
        tarefas = [limpar_html(f.get("content")) for f in self._sub_itens(tid, "TicketTask")]
        acompanhamentos = [f"[{'Técnico' if tec else 'Solicitante'}] {texto}"
                           for tec, texto in respostas] + [f"[Tarefa] {x}" for x in tarefas if x]
        # Nesta base quase ninguém usa o campo Solução: em chamados solucionados ou fechados,
        # a resolução são as últimas respostas dos técnicos.
        if not any(solucoes) and t.get("status") in (5, 6):
            solucoes = [texto for tec, texto in respostas if tec][-2:]
        return {
            "id": tid,
            "titulo": t.get("name") or "",
            "descricao": limpar_html(t.get("content")),
            "categoria": str(t.get("itilcategories_id") or ""),
            "status": STATUS.get(t.get("status"), str(t.get("status"))),
            "data_abertura": t.get("date") or "",
            "data_solucao": t.get("solvedate") or "",
            "data_modificacao": t.get("date_mod") or "",
            "solucao": "\n---\n".join(s for s in solucoes if s),
            "acompanhamentos": "\n---\n".join(acompanhamentos),
        }
