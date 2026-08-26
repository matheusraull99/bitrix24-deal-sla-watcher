"""Linha de comando do vigia de SLA.

Feito para rodar no agendador: código de saída 0 quando está tudo em dia,
1 quando houve violação. Assim o cron/Actions falha visivelmente em vez de
esconder o problema num log que ninguém lê.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from bitrix24_client import from_env
from bitrix24_client.errors import BitrixError

from .feriados import parse_extras
from .watcher import Estado, RegraSLA, SLAWatcher


def carregar_regras(caminho: Path) -> tuple[list[RegraSLA], frozenset[date]]:
    """Lê o JSON de configuração.

    Raises:
        ValueError: configuração sem ``regras`` ou com feriado mal formado.
    """
    dados = json.loads(caminho.read_text("utf-8"))
    brutas = dados.get("regras")
    if not brutas:
        raise ValueError(f"{caminho} nao tem a chave 'regras'")

    regras = [
        RegraSLA(
            estagio_id=r["estagio_id"],
            dias_uteis=int(r["dias_uteis"]),
            rotulo=r.get("rotulo", ""),
            escalar_para=r.get("escalar_para"),
            dias_para_escalar=int(r.get("dias_para_escalar", 3)),
        )
        for r in brutas
    ]
    return regras, parse_extras(dados.get("feriados_extras"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="vigiar-sla",
        description="Encontra negocios parados alem do SLA e cobra o responsavel.",
    )
    p.add_argument("--config", type=Path, default=Path("sla.json"))
    p.add_argument("--estado", type=Path, default=Path("state.json"))
    p.add_argument("--executar", action="store_true", help="envia as notificacoes")
    p.add_argument("--hoje", type=date.fromisoformat, help="data de referencia (teste)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        regras, extras = carregar_regras(args.config)
        bx = from_env()
        watcher = SLAWatcher(
            bx,
            regras,
            estado=Estado.carregar(args.estado),
            extras_feriado=extras,
            dry_run=not args.executar,
        )
        violacoes = watcher.varrer(args.hoje)
        enviadas = watcher.notificar(violacoes)
    except (BitrixError, ValueError, OSError) as exc:
        print(f"falhou: {exc}", file=sys.stderr)
        return 2

    if not violacoes:
        print("nenhum SLA estourado")
        return 0

    valor_parado = sum(v.valor for v in violacoes)
    print(f"\n{len(violacoes)} negocios fora do SLA | R$ {valor_parado:,.2f} parados")
    for v in sorted(violacoes, key=lambda x: x.atraso, reverse=True)[:20]:
        print(f"  #{v.deal_id:<8} {v.atraso:>3}d de atraso  [{v.nivel}]  {v.titulo[:50]}")
    print(f"\n{enviadas} notificacoes {'enviadas' if args.executar else 'simuladas'}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
