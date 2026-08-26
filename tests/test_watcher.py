"""Testes do vigia: escalonamento, anti-spam e persistência de estado."""

from __future__ import annotations

import json
from datetime import date

from sla_watcher.watcher import Estado, RegraSLA, Violacao

REGRA = RegraSLA(
    estagio_id="C1:PREPARATION",
    dias_uteis=5,
    rotulo="Proposta enviada",
    escalar_para=42,
    dias_para_escalar=3,
)


def violacao(dias_parado: int, deal_id: int = 100) -> Violacao:
    return Violacao(
        deal_id=deal_id,
        titulo="Obra Centro",
        responsavel_id=7,
        estagio_id=REGRA.estagio_id,
        regra=REGRA,
        entrou_em=date(2026, 9, 1),
        dias_parado=dias_parado,
        valor=15_000.0,
    )


class TestEscalonamento:
    def test_atraso_pequeno_fica_com_o_responsavel(self):
        assert violacao(6).nivel == "responsavel"

    def test_atraso_grande_sobe_para_o_gestor(self):
        assert violacao(8).nivel == "gestor", "5 de prazo + 3 de tolerancia"

    def test_sem_gestor_configurado_nunca_escala(self):
        sem_gestor = RegraSLA("C1:NEW", dias_uteis=2, escalar_para=None)
        v = Violacao(1, "x", 7, "C1:NEW", sem_gestor, date(2026, 9, 1), 30)
        assert v.nivel == "responsavel"

    def test_atraso_e_a_diferenca_para_o_prazo(self):
        assert violacao(9).atraso == 4


class TestMensagem:
    def test_cita_negocio_prazo_e_data_limite(self):
        texto = violacao(8).mensagem()
        assert "#100" in texto
        assert "Obra Centro" in texto
        assert "Proposta enviada" in texto, "usa o rotulo, nao o STAGE_ID cru"
        assert "8 dias uteis" in texto

    def test_usa_rotulo_legivel_quando_existe(self):
        assert "C1:PREPARATION" not in violacao(8).mensagem()


class TestEstado:
    def test_nao_avisa_duas_vezes_no_mesmo_nivel(self, tmp_path):
        estado = Estado.carregar(tmp_path / "state.json")
        v = violacao(6)
        assert not estado.ja_avisou(v)
        estado.registrar(v)
        assert estado.ja_avisou(v)

    def test_avisa_de_novo_quando_escala_para_gestor(self, tmp_path):
        """Subir de nível é informação nova — o gestor ainda não soube."""
        estado = Estado.carregar(tmp_path / "state.json")
        estado.registrar(violacao(6))
        assert not estado.ja_avisou(violacao(9)), "nivel gestor e um aviso novo"

    def test_sobrevive_ao_reinicio(self, tmp_path):
        caminho = tmp_path / "state.json"
        primeiro = Estado.carregar(caminho)
        primeiro.registrar(violacao(6))
        primeiro.salvar()

        segundo = Estado.carregar(caminho)
        assert segundo.ja_avisou(violacao(6))

    def test_estado_corrompido_nao_derruba_o_robo(self, tmp_path):
        """Pior caso deve ser um aviso repetido, nunca um SLA não cobrado."""
        caminho = tmp_path / "state.json"
        caminho.write_text("{ isso nao e json", encoding="utf-8")
        estado = Estado.carregar(caminho)
        assert estado.avisados == {}

    def test_esquece_negocio_que_saiu_do_estagio(self, tmp_path):
        estado = Estado.carregar(tmp_path / "state.json")
        estado.registrar(violacao(6, deal_id=100))
        estado.registrar(violacao(6, deal_id=200))

        removidos = estado.limpar_resolvidos({100})

        assert removidos == 1
        assert "200" not in estado.avisados

    def test_salvamento_e_atomico(self, tmp_path):
        """Robô morto no meio da escrita não pode deixar JSON pela metade."""
        caminho = tmp_path / "sub" / "state.json"
        estado = Estado.carregar(caminho)
        estado.registrar(violacao(6))
        estado.salvar()

        assert json.loads(caminho.read_text("utf-8"))["avisados"] == {"100": "responsavel"}
        assert not caminho.with_suffix(".tmp").exists(), "temporario deve sumir"
