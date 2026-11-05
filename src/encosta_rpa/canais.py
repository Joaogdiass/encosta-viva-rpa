"""Canais de envio. Só o Telegram é real, e só quando o token e o chat estão configurados."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime

from encosta_rpa.config import Config

# Ordem de troca de canal depois de N falhas.
CADEIA = {
    "telegram": ["telegram", "sms", "email"],
    "whatsapp": ["whatsapp", "sms", "email"],
    "sms": ["sms", "email"],
    "email": ["email"],
}


class ErroEnvio(Exception):
    pass


class CanalSimulado:
    """Registra o envio em saida/caixa_saida/. O cadastro é fictício, então nada sai para a rede."""

    simulado = True

    def __init__(self, nome: str, cfg: Config):
        self.nome = nome
        self.falhar = nome in cfg.simular_falha
        self.pasta = cfg.saida_dir / "caixa_saida"
        self.pasta.mkdir(parents=True, exist_ok=True)

    def enviar(self, alerta_id: str, morador_hash: str, mensagem: str, agora: datetime) -> None:
        if self.falhar:
            raise ErroEnvio(f"falha simulada no canal {self.nome}")
        registro = {"alerta_id": alerta_id, "morador_hash": morador_hash, "canal": self.nome,
                    "enviado_em": agora.isoformat(timespec="minutes"), "simulado": True}
        with (self.pasta / f"{self.nome}.jsonl").open("a", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write(json.dumps(registro) + "\n")


class CanalTelegram:
    """Publica uma vez por alerta no grupo do setor. O cadastro fictício não tem chat individual."""

    simulado = False
    nome = "telegram"

    def __init__(self, cfg: Config):
        self.url = f"{cfg.telegram_url.rstrip('/')}/bot{cfg.telegram_token}/sendMessage"
        self.chat = cfg.telegram_chat
        self.falhar = "telegram" in cfg.simular_falha
        self.publicados: set[str] = set()

    def enviar(self, alerta_id: str, morador_hash: str, mensagem: str, agora: datetime) -> None:
        if self.falhar:
            raise ErroEnvio("falha simulada no canal telegram")
        if alerta_id in self.publicados:
            return
        corpo = json.dumps({"chat_id": self.chat, "text": mensagem}).encode("utf-8")
        pedido = urllib.request.Request(self.url, data=corpo, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(pedido, timeout=15) as resposta:
                dados = json.loads(resposta.read())
        except urllib.error.HTTPError as erro:
            # Só o código: a URL carrega o token e não pode ir para o log.
            raise ErroEnvio(f"Telegram respondeu HTTP {erro.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as erro:
            raise ErroEnvio(f"Telegram indisponível ({type(erro).__name__})") from None
        if not dados.get("ok"):
            raise ErroEnvio("Telegram recusou a mensagem")
        self.publicados.add(alerta_id)


def montar_canais(cfg: Config) -> dict:
    canais = {nome: CanalSimulado(nome, cfg) for nome in ("whatsapp", "sms", "email", "telegram")}
    if cfg.telegram_token and cfg.telegram_chat:
        canais["telegram"] = CanalTelegram(cfg)
    return canais
