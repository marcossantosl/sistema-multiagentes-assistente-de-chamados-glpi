"""Base de conhecimento local dos chamados: SQLite + FTS5 (ranqueamento BM25).

É a camada de recuperação do RAG. Cada consulta gerada pelo agente de triagem é
executada aqui e os resultados são fundidos por Reciprocal Rank Fusion (RRF).
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from .config import config

CAMPOS = ("id", "titulo", "descricao", "categoria", "status", "data_abertura",
          "data_solucao", "data_modificacao", "solucao", "acompanhamentos")

STOPWORDS = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por para pra com sem
e ou que se nao não ao aos à às é ser foi esta está estao estão tem ter há
me meu minha meus minhas eu ele ela eles elas voce você voces vocês isso isto
esse essa este esta aquele aquela mais menos muito pouco ja já quando onde como
favor bom dia boa tarde noite ola olá obrigado obrigada att atenciosamente
consigo conseguindo problema erro chamado usuario usuário
""".split())

_PALAVRA = re.compile(r"[a-z0-9][a-z0-9_.\-]*", re.I)


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def termos(texto: str) -> list[str]:
    vistos: list[str] = []
    for p in _PALAVRA.findall(_sem_acento(texto.lower())):
        p = p.strip(".-_")
        if len(p) < 2 or p in STOPWORDS or p in vistos:
            continue
        vistos.append(p)
    return vistos


def consulta_fts(texto: str) -> str | None:
    """Transforma texto livre numa expressão FTS5 segura (OR de termos, com prefixo).

    O prefixo (`impress*`) faz o papel de um stemmer simples para o português:
    'impressora', 'impressoras' e 'impressão' casam com a mesma consulta.
    """
    partes = []
    for t in termos(texto):
        t = re.sub(r"[^a-z0-9]", " ", t).strip()
        for sub in t.split():
            if len(sub) >= 6:
                partes.append(f'"{sub[:-2]}"*')
            elif len(sub) >= 2:
                partes.append(f'"{sub}"')
    return " OR ".join(dict.fromkeys(partes)) or None


class Indice:
    def __init__(self, caminho: Path | str = config.db_path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._criar()

    @contextmanager
    def _con(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.caminho)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _criar(self) -> None:
        with self._con() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS chamados (
                    id INTEGER PRIMARY KEY, titulo TEXT, descricao TEXT, categoria TEXT,
                    status TEXT, data_abertura TEXT, data_solucao TEXT, data_modificacao TEXT,
                    solucao TEXT, acompanhamentos TEXT
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chamados_fts USING fts5(
                    titulo, descricao, categoria, solucao, acompanhamentos,
                    tokenize = 'unicode61 remove_diacritics 2'
                );
                CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
            """)

    # ---- escrita ------------------------------------------------------------
    def salvar(self, chamados: Iterable[dict]) -> int:
        n = 0
        with self._con() as con:
            for c in chamados:
                linha = {k: c.get(k, "") for k in CAMPOS}
                linha["id"] = int(linha["id"])
                con.execute(f"INSERT OR REPLACE INTO chamados ({','.join(CAMPOS)}) "
                            f"VALUES ({','.join('?' * len(CAMPOS))})",
                            [linha[k] for k in CAMPOS])
                con.execute("DELETE FROM chamados_fts WHERE rowid = ?", (linha["id"],))
                con.execute("INSERT INTO chamados_fts (rowid, titulo, descricao, categoria, "
                            "solucao, acompanhamentos) VALUES (?, ?, ?, ?, ?, ?)",
                            (linha["id"], linha["titulo"], linha["descricao"], linha["categoria"],
                             linha["solucao"], linha["acompanhamentos"]))
                n += 1
        return n

    def meta(self, chave: str, valor: str | None = None) -> str | None:
        with self._con() as con:
            if valor is not None:
                con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (chave, valor))
                return valor
            r = con.execute("SELECT valor FROM meta WHERE chave = ?", (chave,)).fetchone()
            return r["valor"] if r else None

    # ---- leitura ------------------------------------------------------------
    def obter(self, ticket_id: int) -> dict | None:
        with self._con() as con:
            r = con.execute("SELECT * FROM chamados WHERE id = ?", (ticket_id,)).fetchone()
            return dict(r) if r else None

    def total(self) -> dict:
        with self._con() as con:
            r = con.execute("SELECT COUNT(*) total, SUM(solucao <> '') com_solucao "
                            "FROM chamados").fetchone()
            return {"total": r["total"], "com_solucao": r["com_solucao"] or 0}

    def buscar(self, texto: str, limite: int = 20, excluir: int | None = None) -> list[dict]:
        expr = consulta_fts(texto)
        if not expr:
            return []
        with self._con() as con:
            linhas = con.execute(
                """SELECT c.*, bm25(chamados_fts, 4.0, 1.0, 1.5, 2.0, 1.0) AS score
                   FROM chamados_fts JOIN chamados c ON c.id = chamados_fts.rowid
                   WHERE chamados_fts MATCH ? AND c.id IS NOT ?
                   ORDER BY score LIMIT ?""",
                (expr, excluir, limite)).fetchall()
        return [dict(r) for r in linhas]

    def buscar_multi(self, consultas: list[str], limite: int = 25, excluir: int | None = None,
                     k: int = 60) -> list[dict]:
        """Executa várias consultas e funde os rankings com Reciprocal Rank Fusion."""
        pontos: dict[int, float] = {}
        docs: dict[int, dict] = {}
        for consulta in consultas:
            for pos, doc in enumerate(self.buscar(consulta, limite * 2, excluir)):
                pontos[doc["id"]] = pontos.get(doc["id"], 0.0) + 1.0 / (k + pos + 1)
                docs[doc["id"]] = doc
        # Chamados já resolvidos valem mais para o técnico.
        for tid, doc in docs.items():
            if doc.get("solucao") or doc.get("status") in ("Solucionado", "Fechado"):
                pontos[tid] *= 1.15
        ordem = sorted(pontos, key=pontos.get, reverse=True)[:limite]
        return [{**docs[t], "rrf": round(pontos[t], 5)} for t in ordem]
