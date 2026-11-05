"""Roda os cenários de sucesso, decisão e falha, e grava a saída em tests/evidencias/.

Uso: py scripts/demonstrar.py            (todos)
     py scripts/demonstrar.py decisao    (só um: sucesso, decisao, falha_api, falha_canal, falha_arquivo)

Cada cenário tem estado próprio em estado_demo/. O cenário `decisao` também atualiza o
alertas.json da tela do MVP, se MVP_DADOS_DIR estiver definido no .env.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
BASE = RAIZ / "estado_demo"
EVIDENCIAS = RAIZ / "tests" / "evidencias"
PORTA_FECHADA = "http://127.0.0.1:9/fora-do-ar"
DEMO = RAIZ / "dados_demo"


def rodar(nome: str, titulo: str, *args: str, publicar_mvp: bool = False, **env_extra: str) -> str:
    pasta = BASE / nome
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        # Sempre os dados do repositório, para o resultado não depender da máquina.
        "CHEGADA_DIR": str(pasta / "chegada") if (pasta / "chegada").exists() else str(DEMO / "chegada"),
        "OURO_ORIGEM": str(DEMO / "risco_setores.json"),
        "ESTADO_DIR": str(pasta / "estado"),
        "SAIDA_DIR": str(pasta / "saida"),
        "LOGS_DIR": str(pasta / "logs"),
        "QUARENTENA_DIR": str(pasta / "quarentena"),
        **env_extra,
    }
    if not publicar_mvp:
        env["MVP_DADOS_DIR"] = str(pasta / "mvp")
    comando = [sys.executable, str(RAIZ / "src" / "main.py"), *args]
    r = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", env=env, cwd=RAIZ)
    texto = f"$ py src/main.py {' '.join(args)}\n# {titulo}\n{r.stdout}{r.stderr}\n[código de saída: {r.returncode}]\n"
    print(texto)
    return texto


def sucesso() -> str:
    return rodar("sucesso", "Dia sem chuva forte: nenhum setor muda de nível e ninguém recebe mensagem.",
                 "ciclo", "--replay", "--agora", "2026-10-28T10:00")


def decisao() -> str:
    return rodar("decisao", "Evento de chuva no Jardim Ângela (S04), ciclo a ciclo, de 15 em 15 minutos.",
                 "replay", "--inicio", "2026-11-03T12:00", "--fim", "2026-11-03T20:30", publicar_mvp=True)


def falha_api() -> str:
    # O primeiro ciclo enche o cache com a API real. O segundo aponta para uma porta fechada.
    texto = rodar("falha_api", "API no ar: chuva real do Open-Meteo.", "ciclo")
    texto += rodar("falha_api", "API fora do ar: 3 tentativas, último valor com flag e aviso ao operador.",
                   "ciclo", OPEN_METEO_URL=PORTA_FECHADA)
    texto += rodar("falha_api", "API de volta: o incidente é fechado e o aviso de volta ao normal é registrado.", "ciclo")
    return texto


def falha_canal() -> str:
    texto = rodar("falha_canal", "Telegram fora do ar: depois de 3 falhas, os envios passam para o SMS simulado.",
                  "ciclo", "--replay", "--agora", "2026-11-03T14:00", SIMULAR_FALHA_CANAIS="telegram")
    texto += rodar("falha_canal", "Todos os canais fora: o alerta fica na fila do próximo ciclo.",
                   "ciclo", "--replay", "--agora", "2026-11-03T15:15",
                   SIMULAR_FALHA_CANAIS="telegram,sms,whatsapp,email")
    texto += rodar("falha_canal", "Canais de volta: a fila é esvaziada.", "ciclo", "--replay", "--agora", "2026-11-03T15:30")
    return texto


def falha_arquivo() -> str:
    copia = BASE / "falha_arquivo" / "chegada"
    shutil.copytree(DEMO / "chegada", copia)
    (copia / "relatos" / "relatos_2026-11-03.json").write_text("isto não é JSON\n{quebrado\n", encoding="utf-8")
    return rodar("falha_arquivo", "Arquivo de relatos corrompido: vai para a quarentena e os demais seguem.",
                 "ciclo", "--replay", "--agora", "2026-11-03T14:00")


CENARIOS = {"sucesso": sucesso, "decisao": decisao, "falha_api": falha_api,
            "falha_canal": falha_canal, "falha_arquivo": falha_arquivo}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    pedidos = sys.argv[1:] or list(CENARIOS)
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    for nome in pedidos:
        shutil.rmtree(BASE / nome, ignore_errors=True)
        (BASE / nome).mkdir(parents=True)
        print(f"\n===== Cenário: {nome} =====")
        (EVIDENCIAS / f"cenario_{nome}.txt").write_text(CENARIOS[nome](), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
