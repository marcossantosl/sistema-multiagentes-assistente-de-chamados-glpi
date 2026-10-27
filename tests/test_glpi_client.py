"""chamado_completo: as respostas dos técnicos viram a solução de chamados resolvidos."""
from glpi_rag.config import Config
from glpi_rag.glpi_client import GLPIClient

CFG = Config(glpi_user_token="x", tecnicos=frozenset({"tecnico.um", "tecnico.dois"}))


class GLPIFalso(GLPIClient):
    def __init__(self, ticket, followups, solucoes=()):
        super().__init__(CFG)
        self.ticket, self.dados = ticket, {"ITILFollowup": followups,
                                           "ITILSolution": list(solucoes), "TicketTask": []}

    def obter_chamado(self, ticket_id):
        return self.ticket

    def _sub_itens(self, ticket_id, tipo):
        return self.dados[tipo]


FOLLOWUPS = [
    {"users_id": "usuario.final", "content": "Ainda não funciona"},
    {"users_id": "tecnico.um", "content": "Reiniciei o spooler"},
    {"users_id": "usuario.final", "content": "Voltou, obrigado"},
    {"users_id": "Tecnico.Dois", "content": "Limpei a fila e testei a impressão"},
]


def test_solucionado_usa_ultimas_respostas_dos_tecnicos():
    c = GLPIFalso({"id": 1, "name": "Impressora", "status": 5}, FOLLOWUPS).chamado_completo(1)
    assert c["solucao"] == "Reiniciei o spooler\n---\nLimpei a fila e testei a impressão"
    assert "[Solicitante] Ainda não funciona" in c["acompanhamentos"]
    assert "[Técnico] Limpei a fila" in c["acompanhamentos"]
    assert "usuario" not in c["acompanhamentos"] and "tecnico." not in c["acompanhamentos"]


def test_chamado_aberto_nao_ganha_solucao():
    c = GLPIFalso({"id": 2, "name": "x", "status": 2}, FOLLOWUPS).chamado_completo(2)
    assert c["solucao"] == ""


def test_solucao_formal_tem_prioridade():
    c = GLPIFalso({"id": 3, "name": "x", "status": 6}, FOLLOWUPS,
                  [{"content": "Troca do toner"}]).chamado_completo(3)
    assert c["solucao"] == "Troca do toner"
