"""Limpeza do HTML que o GLPI grava nos campos de texto."""
import html
import re

_TAGS = re.compile(r"<[^>]+>")
_BLOCOS = re.compile(r"</?(p|div|br|li|tr|h\d)[^>]*>", re.I)
_ESPACOS = re.compile(r"[ \t\r\f\v]+")
_LINHAS = re.compile(r"\n\s*\n+")


def limpar_html(valor: str | None) -> str:
    if not valor:
        return ""
    # O GLPI armazena o HTML com entidades escapadas (&lt;p&gt;...), então desescapa duas vezes.
    texto = html.unescape(html.unescape(valor))
    texto = _BLOCOS.sub("\n", texto)
    texto = _TAGS.sub(" ", texto)
    texto = _ESPACOS.sub(" ", texto)
    texto = _LINHAS.sub("\n", texto)
    return texto.strip()


def cortar(texto: str, limite: int) -> str:
    return texto if len(texto) <= limite else texto[:limite].rstrip() + " […]"


def cortar_final(texto: str, limite: int) -> str:
    """Mantém o fim do texto — nos acompanhamentos é onde costuma estar a resolução."""
    return texto if len(texto) <= limite else "[…] " + texto[-limite:].lstrip()
