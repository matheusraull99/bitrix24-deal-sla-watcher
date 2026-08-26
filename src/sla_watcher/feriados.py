"""Calendário útil brasileiro — feriados nacionais, inclusive os móveis.

SLA comercial se mede em dias úteis, não corridos. Um negócio que entrou na
sexta antes do Carnaval e continua parado na quarta-feira de cinzas está
parado há **cinco dias corridos e zero dias úteis**. Cobrar o vendedor nesse
caso queima confiança no robô, e um robô em que ninguém confia é desligado.

Os feriados móveis saem da data da Páscoa pelo algoritmo de Butcher, então
o módulo funciona para qualquer ano sem tabela chumbada nem dependência
externa.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

#: Feriados nacionais de data fixa: (mês, dia, nome).
FIXOS = (
    (1, 1, "Confraternizacao Universal"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independencia do Brasil"),
    (10, 12, "Nossa Senhora Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamacao da Republica"),
    (11, 20, "Consciencia Negra"),
    (12, 25, "Natal"),
)


def pascoa(ano: int) -> date:
    """Domingo de Páscoa pelo algoritmo de Butcher (calendário gregoriano)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - nome do algoritmo original
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


@lru_cache(maxsize=32)
def feriados_do_ano(ano: int) -> dict[date, str]:
    """Todos os feriados nacionais do ano, fixos e móveis.

    O cache importa: o vigia consulta o calendário uma vez por negócio, e um
    portal com 20 mil negócios recalcularia a Páscoa 20 mil vezes.
    """
    p = pascoa(ano)
    datas = {date(ano, mes, dia): nome for mes, dia, nome in FIXOS}
    datas[p - timedelta(days=48)] = "Carnaval (segunda)"
    datas[p - timedelta(days=47)] = "Carnaval (terca)"
    datas[p - timedelta(days=2)] = "Sexta-feira Santa"
    datas[p + timedelta(days=60)] = "Corpus Christi"
    return datas


def eh_util(dia: date, extras: frozenset[date] = frozenset()) -> bool:
    """``True`` se for dia útil.

    Args:
        dia: data a testar.
        extras: feriados municipais/estaduais e recessos da empresa. Ficam
            fora da lista nacional porque variam por cidade — o aniversário
            de São Paulo não para o time do Recife.
    """
    return dia.weekday() < 5 and dia not in feriados_do_ano(dia.year) and dia not in extras


def dias_uteis_entre(inicio: date, fim: date, extras: frozenset[date] = frozenset()) -> int:
    """Conta dias úteis de ``inicio`` (exclusivo) até ``fim`` (inclusivo).

    A borda é assim de propósito: um negócio que entrou no estágio hoje está
    parado há zero dias úteis, não um.

    Returns:
        Zero quando ``fim`` é anterior a ``inicio`` — data futura no CRM
        acontece (fuso, digitação) e não deve virar SLA negativo.
    """
    if fim <= inicio:
        return 0

    total = 0
    cursor = inicio + timedelta(days=1)
    while cursor <= fim:
        if eh_util(cursor, extras):
            total += 1
        cursor += timedelta(days=1)
    return total


def somar_dias_uteis(
    inicio: date, quantidade: int, extras: frozenset[date] = frozenset()
) -> date:
    """Data resultante de somar ``quantidade`` dias úteis a ``inicio``.

    Usado para calcular a data-limite que aparece na notificação: dizer
    "vence em 3 dias úteis" é vago; "vence em 12/09" o vendedor entende.
    """
    cursor = inicio
    restantes = quantidade
    while restantes > 0:
        cursor += timedelta(days=1)
        if eh_util(cursor, extras):
            restantes -= 1
    return cursor


def parse_extras(valores: list[str] | None) -> frozenset[date]:
    """Converte ``["2026-01-25", "2026-07-09"]`` em datas.

    Raises:
        ValueError: data fora do formato ISO, com a entrada citada — erro de
            configuração precisa dizer *qual* linha está errada.
    """
    saida = set()
    for bruto in valores or []:
        try:
            saida.add(date.fromisoformat(bruto.strip()))
        except ValueError as exc:
            raise ValueError(f"feriado extra invalido: {bruto!r} (use AAAA-MM-DD)") from exc
    return frozenset(saida)
