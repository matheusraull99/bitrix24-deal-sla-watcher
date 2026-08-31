"""Vigia de SLA: acha negócios parados além do prazo e cobra quem precisa.

Duas armadilhas moldaram este código.

**`DATE_MODIFY` não diz há quanto tempo o negócio está no estágio.** Qualquer
edição — anexar arquivo, corrigir telefone — atualiza esse campo. Um negócio
esquecido há 40 dias cujo telefone foi corrigido ontem aparece como
"modificado ontem". O tempo real vem do histórico de estágios.

**Notificar todo dia é a forma mais rápida de o time criar uma regra de
caixa de entrada para o robô.** Depois disso, o alerta que importa também
some. Por isso cada negócio é cobrado uma vez por nível de escalonamento, e
o estado fica em disco.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from bitrix24_client import Bitrix24

from .feriados import dias_uteis_entre, somar_dias_uteis
from .tempo import hoje as hoje_no_brasil

log = logging.getLogger("sla_watcher")


@dataclass(frozen=True)
class RegraSLA:
    """Prazo de um estágio e para quem escalar quando estoura.

    Args:
        estagio_id: ``STAGE_ID`` do funil, ex.: ``C1:PREPARATION``.
        dias_uteis: prazo máximo de permanência.
        escalar_para: ID do usuário que recebe o segundo aviso. ``None``
            mantém a cobrança só com o responsável.
        dias_para_escalar: dias úteis além do prazo antes de escalar.
    """

    estagio_id: str
    dias_uteis: int
    rotulo: str = ""
    escalar_para: int | None = None
    dias_para_escalar: int = 3


@dataclass
class Violacao:
    """Um negócio que passou do prazo, com o contexto do aviso."""

    deal_id: int
    titulo: str
    responsavel_id: int
    estagio_id: str
    regra: RegraSLA
    entrou_em: date
    dias_parado: int
    valor: float = 0.0

    @property
    def atraso(self) -> int:
        return self.dias_parado - self.regra.dias_uteis

    @property
    def nivel(self) -> str:
        """``responsavel`` no primeiro aviso, ``gestor`` depois do limite."""
        if self.regra.escalar_para and self.atraso >= self.regra.dias_para_escalar:
            return "gestor"
        return "responsavel"

    def mensagem(self) -> str:
        """Texto enviado no chat — direto, com o que fazer em seguida."""
        venceu_em = somar_dias_uteis(self.entrou_em, self.regra.dias_uteis)
        rotulo = self.regra.rotulo or self.estagio_id
        return (
            f"[SLA] O negocio #{self.deal_id} — {self.titulo} — esta em "
            f"'{rotulo}' ha {self.dias_parado} dias uteis. "
            f"O prazo era {self.regra.dias_uteis} dias (venceu em "
            f"{venceu_em.strftime('%d/%m')}, {self.atraso} dias de atraso). "
            f"Avance o estagio ou registre o motivo na timeline."
        )


@dataclass
class Estado:
    """Memória entre execuções: quem já foi avisado e em que nível.

    Guardar em JSON e não no CRM é deliberado: é estado operacional do robô,
    não informação de negócio. Poluir a timeline do cliente com controle
    interno é ruído para o vendedor.
    """

    caminho: Path
    avisados: dict[str, str] = field(default_factory=dict)

    @classmethod
    def carregar(cls, caminho: Path) -> Estado:
        if caminho.exists():
            try:
                dados = json.loads(caminho.read_text("utf-8"))
                return cls(caminho, dict(dados.get("avisados", {})))
            except (json.JSONDecodeError, OSError) as exc:
                # Estado corrompido nao pode impedir o vigia de rodar; o
                # pior caso e um aviso repetido, nao um SLA nao cobrado.
                log.warning("estado ilegivel em %s (%s); recomecando", caminho, exc)
        return cls(caminho)

    def salvar(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.caminho.with_suffix(".tmp")
        temporario.write_text(
            json.dumps({"avisados": self.avisados}, indent=2), encoding="utf-8"
        )
        temporario.replace(self.caminho)  # troca atômica: nunca fica meio escrito

    def ja_avisou(self, violacao: Violacao) -> bool:
        return self.avisados.get(str(violacao.deal_id)) == violacao.nivel

    def registrar(self, violacao: Violacao) -> None:
        self.avisados[str(violacao.deal_id)] = violacao.nivel

    def limpar_resolvidos(self, ativos: set[int]) -> int:
        """Esquece negócios que saíram do estágio — senão o arquivo só cresce."""
        antes = len(self.avisados)
        self.avisados = {k: v for k, v in self.avisados.items() if int(k) in ativos}
        return antes - len(self.avisados)


class SLAWatcher:
    """Varre o funil, mede permanência real e notifica quem precisa."""

    def __init__(
        self,
        bx: Bitrix24,
        regras: list[RegraSLA],
        *,
        estado: Estado,
        extras_feriado: frozenset[date] = frozenset(),
        dry_run: bool = True,
    ) -> None:
        self.bx = bx
        self.regras = {r.estagio_id: r for r in regras}
        self.estado = estado
        self.extras = extras_feriado
        self.dry_run = dry_run

    def varrer(self, hoje: date | None = None) -> list[Violacao]:
        """Devolve as violações encontradas, já filtradas por anti-spam."""
        hoje = hoje or hoje_no_brasil()
        negocios = list(
            self.bx.fetch_all(
                "crm.deal.list",
                {
                    "filter": {"STAGE_ID": list(self.regras), "CLOSED": "N"},
                    "select": ["ID", "TITLE", "STAGE_ID", "ASSIGNED_BY_ID", "OPPORTUNITY"],
                },
            )
        )
        log.info("%d negocios abertos nos estagios monitorados", len(negocios))

        entradas = self._quando_entraram([int(n["ID"]) for n in negocios])
        violacoes = []

        for negocio in negocios:
            deal_id = int(negocio["ID"])
            regra = self.regras[negocio["STAGE_ID"]]
            entrou = entradas.get(deal_id)
            if entrou is None:
                log.debug("negocio %d sem historico de estagio; ignorado", deal_id)
                continue

            parado = dias_uteis_entre(entrou, hoje, self.extras)
            if parado <= regra.dias_uteis:
                continue

            violacoes.append(
                Violacao(
                    deal_id=deal_id,
                    titulo=negocio.get("TITLE", ""),
                    responsavel_id=int(negocio.get("ASSIGNED_BY_ID") or 0),
                    estagio_id=negocio["STAGE_ID"],
                    regra=regra,
                    entrou_em=entrou,
                    dias_parado=parado,
                    valor=float(negocio.get("OPPORTUNITY") or 0),
                )
            )

        removidos = self.estado.limpar_resolvidos({int(n["ID"]) for n in negocios})
        if removidos:
            log.debug("%d negocios saíram do estagio e foram esquecidos", removidos)

        return [v for v in violacoes if not self.estado.ja_avisou(v)]

    def _quando_entraram(self, deal_ids: list[int]) -> dict[int, date]:
        """Data de entrada no estágio atual, pelo histórico de movimentação.

        `crm.stagehistory.list` guarda cada transição. A última entrada de
        cada negócio é o momento que interessa. Sem isso, `DATE_MODIFY`
        mentiria toda vez que alguém corrigisse um telefone.
        """
        if not deal_ids:
            return {}

        entradas: dict[int, date] = {}
        for evento in self.bx.fetch_all(
            "crm.stagehistory.list",
            {
                "entityTypeId": 2,  # 2 = negocio
                "filter": {"OWNER_ID": deal_ids},
                "select": ["OWNER_ID", "CREATED_TIME", "STAGE_SEMANTIC_ID", "STAGE_ID"],
            },
        ):
            dono = int(evento["OWNER_ID"])
            quando = _para_data(evento.get("CREATED_TIME"))
            if quando and (dono not in entradas or quando > entradas[dono]):
                entradas[dono] = quando
        return entradas

    def notificar(self, violacoes: list[Violacao]) -> int:
        """Manda a mensagem no chat interno e devolve quantas saíram."""
        enviadas = 0
        for violacao in violacoes:
            destino = (
                violacao.regra.escalar_para
                if violacao.nivel == "gestor"
                else violacao.responsavel_id
            )
            if not destino:
                log.warning("negocio %d sem destinatario; pulado", violacao.deal_id)
                continue

            if self.dry_run:
                log.info("[simulacao] -> usuario %s: %s", destino, violacao.mensagem())
            else:
                self.bx.call(
                    "im.notify.system.add",
                    {"USER_ID": destino, "MESSAGE": violacao.mensagem()},
                )
            self.estado.registrar(violacao)
            enviadas += 1

        if not self.dry_run:
            self.estado.salvar()
        return enviadas


def _para_data(bruto: Any) -> date | None:
    """Converte o ISO-8601 com fuso que o Bitrix devolve em ``date``.

    O portal manda ``2026-08-31T14:03:00+03:00`` — fuso do servidor, que
    raramente é o do cliente. Para contagem em dias, a parte da data basta;
    tentar converter fuso aqui introduz erro de borda sem ganho.
    """
    if not bruto:
        return None
    try:
        return datetime.fromisoformat(str(bruto)).date()
    except ValueError:
        return None
