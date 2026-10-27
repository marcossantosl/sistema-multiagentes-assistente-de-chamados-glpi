"""Linha de comando.

    python -m glpi_rag sincronizar [--completo] [--limite N]
    python -m glpi_rag importar data/exemplo_chamados.json
    python -m glpi_rag buscar "outlook não sincroniza"
    python -m glpi_rag sugerir --id 1234
    python -m glpi_rag sugerir --titulo "VPN" --descricao "não conecta em casa"
    python -m glpi_rag servir [--porta 8000]
"""
import argparse
import json
import logging
import sys

from .config import config
from .indice import Indice


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="glpi_rag")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sincronizar", help="baixa chamados do GLPI para o índice")
    s.add_argument("--completo", action="store_true", help="ignora a última sincronização")
    s.add_argument("--limite", type=int)
    s = sub.add_parser("importar", help="importa chamados de um JSON")
    s.add_argument("arquivo")
    s = sub.add_parser("buscar", help="busca no índice, sem IA")
    s.add_argument("texto")
    s = sub.add_parser("sugerir", help="roda os agentes para um chamado")
    s.add_argument("--id", type=int)
    s.add_argument("--titulo", default="")
    s.add_argument("--descricao", default="")
    s = sub.add_parser("servir", help="sobe a API e a página do técnico")
    s.add_argument("--porta", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    a = p.parse_args(argv)

    indice = Indice(config.db_path)
    if a.cmd == "sincronizar":
        from .sincronizar import sincronizar_glpi

        print(f"{sincronizar_glpi(indice, a.completo, a.limite)} chamados sincronizados")
    elif a.cmd == "importar":
        from .sincronizar import importar_json

        print(f"{importar_json(indice, a.arquivo)} chamados importados")
    elif a.cmd == "buscar":
        for d in indice.buscar_multi([a.texto], limite=10):
            print(f"#{d['id']:<6} {d['rrf']:.4f}  [{d['status']}] {d['titulo']}")
    elif a.cmd == "sugerir":
        from .orquestrador import Orquestrador

        orq = Orquestrador(indice)
        if a.id:
            chamado = orq.carregar_chamado(a.id)
        elif a.titulo or a.descricao:
            chamado = {"titulo": a.titulo, "descricao": a.descricao}
        else:
            p.error("informe --id ou --titulo/--descricao")
        print(json.dumps(orq.sugerir(chamado), ensure_ascii=False, indent=2))
    elif a.cmd == "servir":
        import uvicorn

        uvicorn.run("glpi_rag.api:app", host=a.host, port=a.porta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
