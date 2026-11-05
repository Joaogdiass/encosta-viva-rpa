"""Log de auditoria em JSON Lines. Nome, telefone e token não saem daqui."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_PADROES = [
    (re.compile(r"\+\d{2}\s?\d{2}\s?\d{4,5}-?\d{4}"), "[telefone]"),
    (re.compile(r"\(\d{2}\)\s?\d{4,5}-?\d{4}"), "[telefone]"),
    (re.compile(r"bot\d+:[\w-]+"), "bot[token]"),
    (re.compile(r"Morador Ficticio [\w-]+"), "[nome]"),
    (re.compile(r"M-S\d{2}-\d{4}"), "[morador_id]"),
]


def sanitizar(texto: str) -> str:
    """Última barreira: limpa dados sensíveis que venham em mensagens de erro de terceiros."""
    for padrao, troca in _PADROES:
        texto = padrao.sub(troca, texto)
    return texto


class Auditoria:
    def __init__(self, pasta: Path):
        self.pasta = pasta
        self.execucao_id = ""
        self.agora: datetime | None = None

    def iniciar(self, execucao_id: str, agora: datetime) -> None:
        self.execucao_id, self.agora = execucao_id, agora

    def evento(self, tipo: str, **campos) -> dict:
        registro = {
            "registrado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "horario_referencia": self.agora.isoformat(timespec="minutes") if self.agora else None,
            "execucao_id": self.execucao_id,
            "tipo": tipo,
            **campos,
        }
        dia = self.agora.date().isoformat() if self.agora else "sem-data"
        linha = sanitizar(json.dumps(registro, ensure_ascii=False, default=str))
        with (self.pasta / f"auditoria_{dia}.jsonl").open("a", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write(linha + "\n")
        return registro
