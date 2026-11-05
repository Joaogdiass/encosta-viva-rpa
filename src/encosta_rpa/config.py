"""Configuração vinda do ambiente e do .env. Nenhuma credencial fica no código."""
from __future__ import annotations

import os
import ssl
from dataclasses import dataclass, field
from pathlib import Path

import certifi

RAIZ = Path(__file__).resolve().parents[2]
URL_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
URL_TELEGRAM = "https://api.telegram.org"


class ErroConfiguracao(Exception):
    """A configuração impede o robô de rodar com segurança."""


def contexto_tls() -> ssl.SSLContext:
    """Verifica certificados com o pacote certifi, para o resultado não depender do Windows da máquina."""
    return ssl.create_default_context(cafile=certifi.where())


def _ler_dotenv(caminho: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if not caminho.is_file():
        return valores
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def _caminho(valor: str | Path) -> Path:
    caminho = Path(valor)
    return caminho if caminho.is_absolute() else (RAIZ / caminho).resolve()


@dataclass
class Config:
    salt: str
    chegada_dir: Path
    ouro_origem: str
    estado_dir: Path
    saida_dir: Path
    logs_dir: Path
    quarentena_dir: Path
    mvp_dados_dir: Path
    dados_repo_dir: Path | None = None
    telegram_token: str = ""
    telegram_chat: str = ""
    telegram_url: str = URL_TELEGRAM
    open_meteo_url: str = URL_OPEN_METEO
    simular_falha: set[str] = field(default_factory=set)
    limite_envios_min: int = 120
    tentativas_canal: int = 3
    ciclos_max_reenvio: int = 3
    janela_idempotencia_min: int = 360
    sensor_offline_min: int = 30
    bateria_minima: float = 20.0
    intervalo_min: int = 15
    dias_arquivos: int = 5

    def __post_init__(self):
        if not self.salt:
            raise ErroConfiguracao(
                "SALT_MORADOR não definido. Copie .env.example para .env e defina um valor: "
                "sem o salt, o robô não consegue proteger os dados dos moradores."
            )
        for pasta in (self.estado_dir, self.saida_dir, self.logs_dir, self.quarentena_dir, self.mvp_dados_dir):
            pasta.mkdir(parents=True, exist_ok=True)


def carregar(**ajustes) -> Config:
    """Lê o ambiente (que tem prioridade) e o .env. `ajustes` substitui qualquer campo."""
    arquivo = _ler_dotenv(RAIZ / ".env")

    def valor(nome: str, padrao: str = "") -> str:
        return os.environ.get(nome) or arquivo.get(nome) or padrao

    dados = valor("ENCOSTA_DADOS_DIR")
    base = dict(
        salt=valor("SALT_MORADOR"),
        chegada_dir=_caminho(valor("CHEGADA_DIR", "dados_demo/chegada")),
        ouro_origem=valor("OURO_ORIGEM", "dados_demo/risco_setores.json"),
        estado_dir=_caminho(valor("ESTADO_DIR", "estado")),
        saida_dir=_caminho(valor("SAIDA_DIR", "saida")),
        logs_dir=_caminho(valor("LOGS_DIR", "logs")),
        quarentena_dir=_caminho(valor("QUARENTENA_DIR", "quarentena")),
        mvp_dados_dir=_caminho(valor("MVP_DADOS_DIR", "saida/mvp")),
        dados_repo_dir=_caminho(dados) if dados else None,
        telegram_token=valor("TELEGRAM_BOT_TOKEN"),
        telegram_chat=valor("TELEGRAM_CHAT_ID"),
        telegram_url=valor("TELEGRAM_URL", URL_TELEGRAM),
        open_meteo_url=valor("OPEN_METEO_URL", URL_OPEN_METEO),
        simular_falha={c.strip() for c in valor("SIMULAR_FALHA_CANAIS").split(",") if c.strip()},
        limite_envios_min=int(valor("LIMITE_ENVIOS_POR_MINUTO", "120")),
        tentativas_canal=int(valor("TENTATIVAS_POR_CANAL", "3")),
        ciclos_max_reenvio=int(valor("CICLOS_MAX_REENVIO", "3")),
        janela_idempotencia_min=int(valor("JANELA_IDEMPOTENCIA_MIN", "360")),
        sensor_offline_min=int(valor("SENSOR_OFFLINE_MIN", "30")),
        bateria_minima=float(valor("BATERIA_MINIMA_PCT", "20")),
    )
    base.update(ajustes)
    return Config(**base)
