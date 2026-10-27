"""Configuração lida de variáveis de ambiente (ou do arquivo .env)."""
import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv é opcional
    pass

RAIZ = Path(__file__).resolve().parent.parent


def _bool(valor: str | None, padrao: bool) -> bool:
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


@dataclass(frozen=True)
class Config:
    glpi_url: str = os.getenv("GLPI_URL", "http://localhost/glpi").rstrip("/")
    glpi_app_token: str | None = os.getenv("GLPI_APP_TOKEN")
    glpi_user_token: str | None = os.getenv("GLPI_USER_TOKEN")
    glpi_login: str | None = os.getenv("GLPI_LOGIN")
    glpi_senha: str | None = os.getenv("GLPI_SENHA")
    glpi_verificar_ssl: bool = _bool(os.getenv("GLPI_VERIFICAR_SSL"), True)
    # Logins de quem responde os chamados; as respostas deles viram a "solução" do chamado.
    tecnicos: frozenset[str] = frozenset(
        t.strip().lower() for t in os.getenv("GLPI_TECNICOS", "").split(",") if t.strip())
    db_path: Path = Path(os.getenv("DB_PATH", str(RAIZ / "data" / "chamados.db")))
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    modelo: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    @property
    def glpi_api(self) -> str:
        return f"{self.glpi_url}/apirest.php"

    @property
    def glpi_configurado(self) -> bool:
        return bool(self.glpi_user_token or (self.glpi_login and self.glpi_senha))

    def link_chamado(self, ticket_id: int) -> str:
        return f"{self.glpi_url}/front/ticket.form.php?id={ticket_id}"


config = Config()
