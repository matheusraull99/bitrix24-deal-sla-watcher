"""Vigia de SLA de funil no Bitrix24, com prazo em dias uteis."""

from .feriados import (
    dias_uteis_entre,
    eh_util,
    feriados_do_ano,
    pascoa,
    somar_dias_uteis,
)
from .watcher import Estado, RegraSLA, SLAWatcher, Violacao

__version__ = "1.0.0"

__all__ = [
    "Estado",
    "RegraSLA",
    "SLAWatcher",
    "Violacao",
    "dias_uteis_entre",
    "eh_util",
    "feriados_do_ano",
    "pascoa",
    "somar_dias_uteis",
]
