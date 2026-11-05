"""Textos do alerta, em linguagem simples. O número de emergência aparece em todos."""
from __future__ import annotations

EMERGENCIA = "Em emergência, ligue 199 (Defesa Civil) ou 193 (Bombeiros)."
AVISO_SUGESTAO = "Este nível é uma sugestão do sistema. Quem decide remover moradores é a Defesa Civil."
AVISO_DADO = "Atenção: parte dos dados está atrasada ou incompleta."

_ORIENTACAO = {
    2: (
        "Fique atento. Observe rachaduras novas, portas e janelas que emperram, "
        "postes ou árvores tortos e água barrenta. Se notar algum desses sinais, saia de casa."
    ),
    3: (
        "Risco alto. A Defesa Civil recebeu um pedido de vistoria. Deixe documentos e remédios "
        "à mão e combine com a família para onde ir. Se notar rachaduras ou barulho no morro, saia já."
    ),
    4: (
        "Risco muito alto agora. Saia de casa e vá para um local seguro, longe da encosta, "
        "ou para o ponto de apoio indicado pela Defesa Civil."
    ),
}


def alerta(nome_setor: str, nivel: str, ordem: int, fatores: str, dado_incompleto: bool) -> str:
    partes = [f"Encosta Viva - {nivel} em {nome_setor}.", _ORIENTACAO[ordem]]
    if fatores:
        partes.append(f"Por quê: {fatores}.")
    if dado_incompleto:
        partes.append(AVISO_DADO)
    partes += [EMERGENCIA, AVISO_SUGESTAO]
    return " ".join(partes)


def encerramento(nome_setor: str) -> str:
    return " ".join([
        f"Encosta Viva - O nível de {nome_setor} voltou para Observação.",
        "Continue atento à chuva e aos sinais no terreno.",
        "Se você saiu de casa, só volte com a liberação da Defesa Civil.",
        EMERGENCIA,
    ])
