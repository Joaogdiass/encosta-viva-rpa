"""O robô precisa chegar aos mesmos níveis que a camada Ouro publica para o MVP."""
import json
from datetime import datetime, timedelta

from conftest import RAIZ
from encosta_rpa import fontes, motor
from encosta_rpa.robo import montar_entrada


def test_niveis_das_regras():
    assert motor.calcular(motor.Entrada()).nivel_ordem == 1
    assert motor.calcular(motor.Entrada(chuva_72h=80)).nivel_ordem == 2
    assert motor.calcular(motor.Entrada(umidade=80)).nivel_ordem == 2
    assert motor.calcular(motor.Entrada(chuva_72h=80, chuva_1h=15)).nivel_ordem == 3
    assert motor.calcular(motor.Entrada(chuva_72h=80, previsao_6h=30)).nivel_ordem == 3
    assert motor.calcular(motor.Entrada(relatos_confirmados=1)).nivel_ordem == 3
    assert motor.calcular(motor.Entrada(umidade=90, chuva_1h=20, delta_inclinacao=2)).nivel_ordem == 4


def test_sem_sensor_valem_so_os_dados_de_chuva():
    resultado = motor.calcular(motor.Entrada(chuva_1h=30, umidade=None, delta_inclinacao=None))
    assert resultado.nivel_ordem == 1
    assert "movimento" not in resultado.fatores


def test_fatores_explicam_o_nivel():
    resultado = motor.calcular(motor.Entrada(chuva_72h=100, chuva_1h=20))
    assert resultado.fatores == "chuva acumulada em 72 h alta; chuva forte agora"


def _comparar_com_ouro(cfg):
    ouro = json.loads((RAIZ / "dados_demo" / "risco_setores.json").read_text(encoding="utf-8"))
    total, iguais, diferencas = 0, 0, []
    for setor in ouro["setores"]:
        setor_id = setor["setor_id"]
        for ponto in setor["serie"]:
            agora = datetime.fromisoformat(ponto["data_hora"]) + timedelta(minutes=45)
            ctx = fontes.Contexto()
            ids = {s["setor_id"] for s in ouro["setores"]}
            leituras = fontes.carregar_sensores(cfg, agora, {setor_id}, ctx)[setor_id]
            relatos = fontes.carregar_relatos(cfg, agora, {setor_id}, ctx)[setor_id]
            serie = fontes.chuva_de_arquivos(cfg, agora, {setor_id}, ctx)[setor_id]
            offline = not leituras or (agora - leituras[-1]["ts"]) > timedelta(minutes=30)
            nivel = motor.calcular(montar_entrada(agora, serie, leituras, relatos, offline)).nivel_ordem
            total += 1
            if nivel == ponto["nivel_ordem"]:
                iguais += 1
            else:
                diferencas.append((setor_id, ponto["data_hora"], ponto["nivel_ordem"], nivel))
    return total, iguais, diferencas


def test_mesmos_niveis_da_camada_ouro(cfg_factory):
    total, iguais, diferencas = _comparar_com_ouro(cfg_factory(dias_arquivos=7))
    print(f"\nparidade com a Ouro: {iguais}/{total}; diferenças: {diferencas[:20]}")
    assert total > 300
    assert not diferencas
