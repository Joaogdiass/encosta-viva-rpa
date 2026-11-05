"""Linha de comando do robô. Rode `py src/main.py --help`."""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta

from encosta_rpa import config, motor
from encosta_rpa.relatorio import gerar_relatorio
from encosta_rpa.robo import Robo


def _imprimir(resumo: dict, so_mudancas: bool = False) -> None:
    if resumo.get("status") == "ignorado":
        print(f"{resumo['agora']}  ciclo ignorado: outro ciclo em execução")
        return
    contagens = resumo.get("contagens", {})
    if not so_mudancas:
        print(f"\n{resumo['agora']}  modo={resumo['modo']}  status={resumo['status']}")
    for s in resumo.get("setores", []):
        mudou = s["decisao"] != "igual"
        if so_mudancas and not mudou:
            continue
        marca = {"subiu": "ALERTA", "encerrou": "ENCERRA", "reduziu": "reduziu", "igual": "sem envio"}[s["decisao"]]
        extra = "".join([" [dado desatualizado]" if s["dado_desatualizado"] else "",
                         " [nível mantido]" if s["nivel_mantido"] else "",
                         " [sensor offline]" if s["sensor"] != "online" else ""])
        print(f"{resumo['agora'] if so_mudancas else ' '}  {s['setor_id']} {s['nome']:<18} "
              f"{motor.NIVEIS[s['nivel_anterior']]} -> {motor.NIVEIS[s['nivel']]:<13} {marca:<9} "
              f"72h={s['chuva_72h']:.1f}mm  fonte={s['fonte_chuva']}{extra}")
    if not so_mudancas:
        print("  " + ", ".join(f"{k}={v}" for k, v in sorted(contagens.items())))
        for problema in resumo.get("problemas", []):
            print(f"  problema: {problema}")
    for erro in resumo.get("erros", []):
        print(f"  ERRO: {erro}")


def cmd_ciclo(args) -> int:
    robo = Robo(config.carregar())
    agora = datetime.fromisoformat(args.agora) if args.agora else None
    resumo = robo.executar_ciclo(agora, replay=args.replay)
    _imprimir(resumo)
    return 1 if resumo.get("status") == "falhou" else 0


def cmd_agendar(args) -> int:
    """Roda a cada N minutos, sem ninguém clicar. Um erro no ciclo não derruba o agendador."""
    robo = Robo(config.carregar())
    print(f"Robô agendado a cada {args.minutos} min. Ctrl+C para parar.")
    while True:
        inicio = time.monotonic()
        try:
            _imprimir(robo.executar_ciclo())
        except Exception as erro:  # noqa: BLE001
            print(f"Erro no agendador ({type(erro).__name__}); novo ciclo no próximo horário.", file=sys.stderr)
        time.sleep(max(1.0, args.minutos * 60 - (time.monotonic() - inicio)))


def cmd_replay(args) -> int:
    """Reproduz um período com os arquivos do Airflow, com um relógio simulado de 15 em 15 min."""
    robo = Robo(config.carregar())
    agora, fim = datetime.fromisoformat(args.inicio), datetime.fromisoformat(args.fim)
    ciclos, falhas = 0, 0
    while agora <= fim:
        resumo = robo.executar_ciclo(agora, replay=True)
        _imprimir(resumo, so_mudancas=True)
        ciclos += 1
        falhas += resumo.get("status") == "falhou"
        agora += timedelta(minutes=args.passo)
    print(f"\n{ciclos} ciclos reproduzidos, {falhas} com falha geral.")
    return 1 if falhas else 0


def cmd_relatorio(args) -> int:
    robo = Robo(config.carregar())
    print(gerar_relatorio(robo.cfg, robo.db, date.fromisoformat(args.data)))
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Robô de alertas da Encosta Viva")
    comandos = parser.add_subparsers(dest="comando", required=True)

    ciclo = comandos.add_parser("ciclo", help="roda um ciclo e termina")
    ciclo.add_argument("--agora", help="horário de referência, ex.: 2026-11-03T16:45")
    ciclo.add_argument("--replay", action="store_true", help="lê a chuva dos arquivos do Airflow, sem chamar a API")
    ciclo.set_defaults(funcao=cmd_ciclo)

    agendar = comandos.add_parser("agendar", help="roda em loop a cada N minutos")
    agendar.add_argument("--minutos", type=int, default=15)
    agendar.set_defaults(funcao=cmd_agendar)

    replay = comandos.add_parser("replay", help="reproduz um período passado")
    replay.add_argument("--inicio", required=True)
    replay.add_argument("--fim", required=True)
    replay.add_argument("--passo", type=int, default=15)
    replay.set_defaults(funcao=cmd_replay)

    relatorio = comandos.add_parser("relatorio", help="gera o PDF de um dia")
    relatorio.add_argument("--data", required=True)
    relatorio.set_defaults(funcao=cmd_relatorio)

    args = parser.parse_args()
    try:
        return args.funcao(args)
    except config.ErroConfiguracao as erro:
        print(f"Erro de configuração: {erro}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
