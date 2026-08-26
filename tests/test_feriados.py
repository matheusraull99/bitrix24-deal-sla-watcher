"""Testes do calendário útil — a conta que decide se o vendedor é cobrado.

As datas de referência foram conferidas contra o calendário oficial. Errar
Carnaval por um dia significa cobrar o time inteiro no feriado.
"""

from __future__ import annotations

from datetime import date

import pytest

from sla_watcher import feriados as f


class TestPascoa:
    @pytest.mark.parametrize(
        "ano,esperado",
        [
            (2024, date(2024, 3, 31)),
            (2025, date(2025, 4, 20)),
            (2026, date(2026, 4, 5)),
            (2027, date(2027, 3, 28)),
            (2030, date(2030, 4, 21)),
        ],
    )
    def test_datas_conhecidas(self, ano, esperado):
        assert f.pascoa(ano) == esperado


class TestFeriadosMoveis:
    def test_carnaval_de_2026(self):
        """Páscoa 05/04/2026 → Carnaval em 16 e 17 de fevereiro."""
        do_ano = f.feriados_do_ano(2026)
        assert do_ano[date(2026, 2, 16)].startswith("Carnaval")
        assert do_ano[date(2026, 2, 17)].startswith("Carnaval")

    def test_sexta_santa_e_corpus_christi_de_2026(self):
        do_ano = f.feriados_do_ano(2026)
        assert do_ano[date(2026, 4, 3)] == "Sexta-feira Santa"
        assert do_ano[date(2026, 6, 4)] == "Corpus Christi"

    def test_fixos_estao_presentes(self):
        do_ano = f.feriados_do_ano(2026)
        assert do_ano[date(2026, 9, 7)] == "Independencia do Brasil"
        assert do_ano[date(2026, 12, 25)] == "Natal"


class TestDiaUtil:
    def test_sabado_e_domingo_nao_sao_uteis(self):
        assert not f.eh_util(date(2026, 9, 5))  # sabado
        assert not f.eh_util(date(2026, 9, 6))  # domingo

    def test_feriado_em_dia_de_semana_nao_e_util(self):
        assert not f.eh_util(date(2026, 9, 7))  # segunda, Independencia

    def test_dia_comum_e_util(self):
        assert f.eh_util(date(2026, 9, 8))

    def test_feriado_extra_estadual_e_respeitado(self):
        """09/07/2026 (Revolucao Constitucionalista, SP) cai numa quinta."""
        feriado_sp = frozenset({date(2026, 7, 9)})
        assert not f.eh_util(date(2026, 7, 9), feriado_sp)
        assert f.eh_util(date(2026, 7, 9)), "sem os extras, continua util"


class TestContagem:
    def test_semana_cheia_da_cinco(self):
        """Segunda 31/08 até sexta 04/09/2026."""
        assert f.dias_uteis_entre(date(2026, 8, 31), date(2026, 9, 4)) == 4

    def test_fim_de_semana_nao_conta(self):
        """Sexta 04/09 até segunda 07/09 — e 07/09 ainda e feriado."""
        assert f.dias_uteis_entre(date(2026, 9, 4), date(2026, 9, 7)) == 0

    def test_carnaval_engole_a_semana(self):
        """Sexta 13/02/2026 ate quarta de cinzas 18/02: so a quarta conta."""
        assert f.dias_uteis_entre(date(2026, 2, 13), date(2026, 2, 18)) == 1

    def test_mesmo_dia_da_zero(self):
        """Entrou no estagio hoje: parado ha zero dias uteis, nao um."""
        assert f.dias_uteis_entre(date(2026, 9, 9), date(2026, 9, 9)) == 0

    def test_data_futura_nao_vira_sla_negativo(self):
        assert f.dias_uteis_entre(date(2026, 9, 20), date(2026, 9, 10)) == 0


class TestSoma:
    def test_pula_o_fim_de_semana(self):
        """Quinta 03/09 + 2 uteis = segunda 07/09... que e feriado, entao 08/09."""
        assert f.somar_dias_uteis(date(2026, 9, 3), 2) == date(2026, 9, 8)

    def test_zero_dias_devolve_a_propria_data(self):
        assert f.somar_dias_uteis(date(2026, 9, 3), 0) == date(2026, 9, 3)


class TestParseExtras:
    def test_converte_lista_iso(self):
        assert f.parse_extras(["2026-01-25"]) == frozenset({date(2026, 1, 25)})

    def test_lista_vazia_ou_none(self):
        assert f.parse_extras(None) == frozenset()

    def test_data_invalida_cita_a_entrada(self):
        with pytest.raises(ValueError, match="25/01/2026"):
            f.parse_extras(["25/01/2026"])
