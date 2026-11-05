"""Motor de risco: as mesmas regras de databricks/funcoes.py (construir_fato).

Os limiares são ILUSTRATIVOS e precisam ser calibrados com PPDC, CEMADEN e IPT.
O nível é uma sugestão: quem decide remover moradores é a Defesa Civil.
tests/test_motor.py compara este cálculo com os níveis publicados pela camada Ouro.
"""
from __future__ import annotations

from dataclasses import dataclass

LIMIAR_CHUVA_72H = 80.0
LIMIAR_UMIDADE_ATENCAO = 80.0
LIMIAR_UMIDADE_SATURADO = 90.0
LIMIAR_PREVISAO_6H = 30.0
LIMIAR_CHUVA_1H_FORTE = 15.0
LIMIAR_CHUVA_1H_MAXIMO = 20.0
LIMIAR_DELTA_INCLINACAO = 2.0

NIVEIS = {1: "Observação", 2: "Atenção", 3: "Alerta", 4: "Alerta máximo"}


@dataclass(frozen=True)
class Entrada:
    chuva_1h: float = 0.0
    chuva_24h: float = 0.0
    chuva_72h: float = 0.0
    previsao_6h: float = 0.0
    umidade: float | None = None
    delta_inclinacao: float | None = None
    relatos_confirmados: int = 0


@dataclass(frozen=True)
class Resultado:
    nivel_ordem: int
    nivel: str
    fatores: str


def calcular(e: Entrada) -> Resultado:
    # Sem leitura de sensor, as condições de solo ficam falsas: valem só os dados de chuva.
    umidade = e.umidade if e.umidade is not None else 0.0
    delta = e.delta_inclinacao if e.delta_inclinacao is not None else 0.0

    atencao = e.chuva_72h >= LIMIAR_CHUVA_72H or umidade >= LIMIAR_UMIDADE_ATENCAO
    alerta = (
        atencao and (e.previsao_6h >= LIMIAR_PREVISAO_6H or e.chuva_1h >= LIMIAR_CHUVA_1H_FORTE)
    ) or e.relatos_confirmados >= 1
    maximo = (
        delta >= LIMIAR_DELTA_INCLINACAO
        and umidade >= LIMIAR_UMIDADE_SATURADO
        and e.chuva_1h >= LIMIAR_CHUVA_1H_MAXIMO
    )
    ordem = 4 if maximo else 3 if alerta else 2 if atencao else 1

    fatores = [
        texto
        for condicao, texto in (
            (e.chuva_72h >= LIMIAR_CHUVA_72H, "chuva acumulada em 72 h alta"),
            (umidade >= LIMIAR_UMIDADE_ATENCAO, "solo muito úmido"),
            (e.previsao_6h >= LIMIAR_PREVISAO_6H, "previsão de chuva forte"),
            (e.chuva_1h >= LIMIAR_CHUVA_1H_FORTE, "chuva forte agora"),
            (e.relatos_confirmados >= 1, "relato confirmado pela Visão"),
            (delta >= LIMIAR_DELTA_INCLINACAO, "movimento detectado no sensor"),
        )
        if condicao
    ]
    return Resultado(ordem, NIVEIS[ordem], "; ".join(fatores))
