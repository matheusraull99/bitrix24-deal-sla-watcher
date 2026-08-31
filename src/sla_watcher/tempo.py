"""O "hoje" do vigia, sempre no fuso de Brasília.

`date.today()` devolve o dia do relógio da máquina, e a máquina que roda o
vigia é um runner do GitHub Actions — que fica em UTC. Depois das 21h no
horário de Brasília o runner já virou o dia: um negócio que entrou no
estágio ontem passa a ser contado como parado há um dia a mais, e o vigia
cobra SLA que ainda não venceu (ou, no sentido contrário, deixa passar).

Como a regra de negócio é "dias úteis no Brasil" — inclusive os feriados de
`feriados.py` —, o fuso certo é o de São Paulo, não UTC. Trocar por
`datetime.now(UTC).date()` calaria o lint e manteria exatamente o bug.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")


def hoje() -> date:
    """Data corrente no fuso de Brasília, independente do relógio do host."""
    return datetime.now(FUSO).date()
