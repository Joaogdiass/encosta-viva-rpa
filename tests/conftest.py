import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from encosta_rpa import config  # noqa: E402


@pytest.fixture
def cfg_factory(tmp_path):
    """Config isolada: cada teste tem seu próprio banco, logs e saídas."""

    def fabricar(**ajustes):
        base = dict(
            salt="salt-de-teste",
            chegada_dir=RAIZ / "dados_demo" / "chegada",
            ouro_origem=str(RAIZ / "dados_demo" / "risco_setores.json"),
            estado_dir=tmp_path / "estado",
            saida_dir=tmp_path / "saida",
            logs_dir=tmp_path / "logs",
            quarentena_dir=tmp_path / "quarentena",
            mvp_dados_dir=tmp_path / "mvp",
            dados_repo_dir=None,
            telegram_token="",
            telegram_chat="",
            simular_falha=set(),
        )
        base.update(ajustes)
        return config.carregar(**base)

    return fabricar


def ler_logs(pasta: Path) -> list[dict]:
    eventos = []
    for arquivo in sorted(pasta.glob("auditoria_*.jsonl")):
        eventos += [json.loads(l) for l in arquivo.read_text(encoding="utf-8").splitlines()]
    return eventos
