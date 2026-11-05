"""Cenários exigidos: sucesso, decisão e falha, mais resiliência e LGPD."""
import hashlib
import json
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import ler_logs
from encosta_rpa import config
from encosta_rpa.canais import montar_canais
from encosta_rpa.robo import Robo

AGORA = datetime(2026, 11, 3, 16, 0)
SETORES = [
    {"setor_id": "S01", "nome": "Vila Teste", "lat": -23.7, "lon": -45.6, "gerado": True},
    {"setor_id": "S02", "nome": "Morro Teste", "lat": -22.5, "lon": -43.1, "gerado": True},
]


class Cena:
    """Monta uma pasta chegada/ pequena, com o clima de cada setor definido pelo teste."""

    def __init__(self, base):
        self.chegada = base / "chegada"
        self.ouro = base / "risco_setores.json"
        self.clima = {s["setor_id"]: {} for s in SETORES}
        self.ouro.write_text(json.dumps({
            "gerado_ate": AGORA.isoformat(timespec="minutes"),
            "setores": [{**s, "chuva_1h": 0, "chuva_24h": 0, "chuva_72h": 0, "previsao_6h": 0,
                         "umidade_solo_media": 50} for s in SETORES],
        }), encoding="utf-8")
        cadastro = []
        for s in SETORES:
            for n, canal in enumerate(["telegram", "sms", "whatsapp"], 1):
                cadastro.append({"morador_id": f"M-{s['setor_id']}-{n:04d}", "nome": f"Morador Ficticio {s['setor_id']}-{n:04d}",
                                 "telefone": f"+55 00 90000-{n:04d}", "setor_id": s["setor_id"], "canal_preferido": canal})
        self._gravar("cadastro", AGORA, cadastro)
        self.definir(AGORA)

    def _gravar(self, fonte, dia, registros):
        pasta = self.chegada / fonte
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / f"{fonte}_{dia.date()}.json").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in registros) + "\n", encoding="utf-8")

    def definir(self, agora, sem_sensor=(), **clima_por_setor):
        """Ex.: definir(agora, S01=dict(chuva_hora=20, acumulado=100, umidade=85))."""
        for setor, clima in clima_por_setor.items():
            self.clima[setor] = clima
        chuva, sensor = [], []
        for setor_id, c in self.clima.items():
            hora = agora.replace(minute=0)
            horas = [hora - timedelta(hours=i) for i in range(10, -1, -1)]
            valores = [c.get("acumulado", 0) / 10] * 10 + [c.get("chuva_hora", 0)]
            chuva.append({"setor_id": setor_id, "coletado_em": agora.isoformat(), "hourly": {
                "time": [h.isoformat(timespec="minutes") for h in horas], "precipitation": valores}})
            if setor_id in sem_sensor:
                continue
            for i in range(24):
                sensor.append({"setor_id": setor_id, "sensor_id": f"SN-{setor_id}",
                               "ts": (agora - timedelta(minutes=15 * i)).isoformat(),
                               "umidade_solo_pct": c.get("umidade", 50), "inclinacao_graus": 3 + (c.get("delta", 0) if i < 4 else 0),
                               "chuva_mm": 0.0, "bateria_pct": c.get("bateria", 90)})
        self._gravar("chuva", agora, chuva)
        self._gravar("sensor", agora, sensor)
        if not sensor:
            (self.chegada / "sensor" / f"sensor_{agora.date()}.json").unlink()


@pytest.fixture
def cena(tmp_path):
    return Cena(tmp_path)


@pytest.fixture
def novo_robo(cena, cfg_factory):
    def fabricar(**ajustes):
        esperas = []
        cfg = cfg_factory(chegada_dir=cena.chegada, ouro_origem=str(cena.ouro), **ajustes)
        robo = Robo(cfg, espera=esperas.append)
        robo.esperas = esperas
        return robo
    return fabricar


def _setor(resumo, setor_id="S01"):
    return next(s for s in resumo["setores"] if s["setor_id"] == setor_id)


def _alertas(robo, setor_id="S01"):
    return robo.db.execute("SELECT * FROM alertas WHERE setor_id=? ORDER BY criado_em", (setor_id,)).fetchall()


def _chamados(robo, tipo=None):
    return robo.db.execute("SELECT * FROM chamados WHERE (? IS NULL OR tipo=?)", (tipo, tipo)).fetchall()


class ServidorFalso:
    """Faz o papel do Open-Meteo e do Telegram. `respostas` é a fila de códigos HTTP (vazia = 200)."""

    def __init__(self):
        self.respostas, self.pedidos, servidor = [], [], self

        class Tratador(BaseHTTPRequestHandler):
            def _responder(self, corpo):
                servidor.pedidos.append(self.path)
                codigo = servidor.respostas.pop(0) if servidor.respostas else 200
                self.send_response(codigo)
                self.end_headers()
                self.wfile.write(json.dumps(corpo).encode())

            def do_GET(self):
                horas = [AGORA + timedelta(hours=i) for i in range(-72, 12)]
                self._responder({"hourly": {"time": [h.isoformat(timespec="minutes") for h in horas],
                                            "precipitation": [servidor.chuva] * len(horas)}})

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self._responder({"ok": True})

            def log_message(self, *_):
                pass

        self.chuva = 0.0
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()


@pytest.fixture
def servidor():
    s = ServidorFalso()
    yield s
    s.http.shutdown()


# ---------------------------------------------------------------- cenário de sucesso

def test_sucesso_chuva_normal_nao_envia_e_atualiza_o_mvp(novo_robo):
    robo = novo_robo()
    resumo = robo.executar_ciclo(AGORA, replay=True)
    assert resumo["status"] == "concluido"
    assert resumo["contagens"]["setores_processados"] == 2
    assert not robo.db.execute("SELECT * FROM alertas").fetchall()
    mvp = json.loads((robo.cfg.mvp_dados_dir / "alertas.json").read_text(encoding="utf-8"))
    assert [s["nivel_risco"] for s in mvp["setores"]] == ["Observação", "Observação"]
    assert mvp["alertas"] == []


# ---------------------------------------------------------------- cenário de decisão

def test_decisao_nivel_subiu_envia_a_todos_e_abre_vistoria(novo_robo, cena):
    robo = novo_robo()
    robo.executar_ciclo(AGORA, replay=True)
    agora = AGORA + timedelta(minutes=15)
    cena.definir(agora, S01=dict(acumulado=100, chuva_hora=20, umidade=85))
    resumo = robo.executar_ciclo(agora, replay=True)

    assert _setor(resumo)["decisao"] == "subiu" and _setor(resumo)["nivel"] == 3
    assert _setor(resumo, "S02")["decisao"] == "igual"
    alerta = _alertas(robo)[0]
    assert alerta["status"] == "enviado" and alerta["nivel"] == "Alerta"
    assert "199" in alerta["mensagem"] and "Defesa Civil" in alerta["mensagem"]
    assert robo.db.execute("SELECT COUNT(*) FROM envios WHERE status='enviado'").fetchone()[0] == 3
    vistorias = _chamados(robo, "vistoria")
    assert len(vistorias) == 1 and vistorias[0]["setor_id"] == "S01"
    mvp = json.loads((robo.cfg.mvp_dados_dir / "alertas.json").read_text(encoding="utf-8"))
    assert mvp["alertas"][0]["setor"] == "Vila Teste" and mvp["alertas"][0]["moradores_avisados"] == 3
    assert mvp["resumo"]["setores_em_alerta"] == 1


def test_decisao_nivel_igual_nao_reenvia(novo_robo, cena):
    robo = novo_robo()
    agora = AGORA
    cena.definir(agora, S01=dict(acumulado=100, chuva_hora=20, umidade=85))
    robo.executar_ciclo(agora, replay=True)
    for i in range(1, 4):
        agora += timedelta(minutes=15)
        cena.definir(agora)
        resumo = robo.executar_ciclo(agora, replay=True)
        assert _setor(resumo)["decisao"] == "igual"
    assert len(_alertas(robo)) == 1
    assert robo.db.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 3
    assert len(_chamados(robo, "vistoria")) == 1


def test_decisao_caiu_para_observacao_envia_encerramento(novo_robo, cena):
    robo = novo_robo()
    cena.definir(AGORA, S01=dict(acumulado=100, chuva_hora=20, umidade=85))
    robo.executar_ciclo(AGORA, replay=True)

    agora = AGORA + timedelta(minutes=15)
    cena.definir(agora, S01=dict(acumulado=100, chuva_hora=0, umidade=60))
    assert _setor(robo.executar_ciclo(agora, replay=True))["decisao"] == "reduziu"
    assert len(_alertas(robo)) == 1  # Reduziu sem encerrar: não manda mensagem.

    agora += timedelta(minutes=15)
    cena.definir(agora, S01=dict(acumulado=0, chuva_hora=0, umidade=50))
    assert _setor(robo.executar_ciclo(agora, replay=True))["decisao"] == "encerrou"
    tipos = [a["tipo"] for a in _alertas(robo)]
    assert tipos == ["alerta", "encerramento"]
    assert "voltou para Observação" in _alertas(robo)[1]["mensagem"]


def test_novo_aumento_depois_do_encerramento_avisa_de_novo(novo_robo, cena):
    """A chave de idempotência não pode silenciar um risco novo dentro da mesma janela."""
    robo = novo_robo()
    agora = AGORA
    for clima in (dict(acumulado=100, chuva_hora=20, umidade=85), dict(acumulado=0, chuva_hora=0, umidade=50),
                  dict(acumulado=100, chuva_hora=20, umidade=85)):
        cena.definir(agora, S01=clima)
        robo.executar_ciclo(agora, replay=True)
        agora += timedelta(minutes=15)
    assert [a["tipo"] for a in _alertas(robo)] == ["alerta", "encerramento", "alerta"]


def test_chave_de_idempotencia_descarta_alerta_duplicado(novo_robo, cena):
    robo = novo_robo()
    cena.definir(AGORA, S01=dict(acumulado=100, chuva_hora=20, umidade=85))
    robo.executar_ciclo(AGORA, replay=True)
    robo.db.execute("DELETE FROM estado_setor")  # Simula a perda do estado: o nível "sobe" de novo.
    robo.db.commit()
    resumo = robo.executar_ciclo(AGORA + timedelta(minutes=15), replay=True)
    assert resumo["contagens"]["alertas_duplicados"] == 1
    assert len(_alertas(robo)) == 1
    assert robo.db.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 3


def test_replay_do_evento_real_do_pipeline(cfg_factory):
    """Com os arquivos do Airflow, o Jardim Ângela (S04) sobe até o Alerta máximo no evento simulado."""
    robo = Robo(cfg_factory(), espera=lambda _: None)
    agora, niveis = datetime(2026, 11, 3, 12, 0), []
    while agora <= datetime(2026, 11, 3, 21, 0):
        resumo = robo.executar_ciclo(agora, replay=True)
        assert resumo["status"] == "concluido"
        niveis.append(_setor(resumo, "S04")["nivel"])
        agora += timedelta(minutes=15)
    assert sorted(set(niveis)) == [1, 2, 3, 4]
    assert niveis == sorted(niveis)
    assert [a["nivel_ordem"] for a in _alertas(robo, "S04")] == [2, 3, 4]
    assert robo.db.execute("SELECT COUNT(*) FROM envios WHERE status='enviado'").fetchone()[0] >= 90


# ---------------------------------------------------------------- cenário de falha: API

def test_falha_api_recupera_na_terceira_tentativa_com_backoff(novo_robo, servidor):
    servidor.respostas = [503, 503]
    robo = novo_robo(open_meteo_url=servidor.url)
    resumo = robo.executar_ciclo(AGORA)
    assert robo.esperas == [2, 4]
    assert _setor(resumo)["dado_desatualizado"] is False
    assert resumo["status"] == "concluido"


def test_falha_api_fora_do_ar_usa_cache_com_flag_e_avisa_e_recupera(novo_robo, servidor):
    robo = novo_robo(open_meteo_url=servidor.url)
    servidor.chuva = 2.0
    assert robo.executar_ciclo(AGORA)["status"] == "concluido"

    servidor.http.shutdown()
    servidor.http.server_close()
    robo.cfg.open_meteo_url = "http://127.0.0.1:9/fora-do-ar"
    resumo = robo.executar_ciclo(AGORA + timedelta(minutes=15))
    s = _setor(resumo)
    assert s["dado_desatualizado"] is True and s["fonte_chuva"] == "cache"
    assert s["chuva_72h"] > 0
    assert resumo["status"] == "concluido_com_falhas"
    assert robo.esperas == [2, 4]  # Só o primeiro setor insiste: depois disso a API é dada como fora do ar.
    assert robo.db.execute("SELECT 1 FROM incidentes WHERE chave='fonte_open_meteo'").fetchone()
    avisos = (robo.cfg.saida_dir / "avisos_operador.jsonl").read_text(encoding="utf-8")
    assert "API fora do ar" in avisos
    mvp = json.loads((robo.cfg.mvp_dados_dir / "alertas.json").read_text(encoding="utf-8"))
    assert mvp["setores"][0]["dado_desatualizado"] is True

    # O aviso não se repete a cada ciclo.
    robo.executar_ciclo(AGORA + timedelta(minutes=30))
    assert (robo.cfg.saida_dir / "avisos_operador.jsonl").read_text(encoding="utf-8").count("incidente_aberto") == 1


def test_falha_api_sem_cache_usa_a_camada_ouro(novo_robo):
    robo = novo_robo(open_meteo_url="http://127.0.0.1:9/fora-do-ar")
    resumo = robo.executar_ciclo(AGORA)
    assert _setor(resumo)["fonte_chuva"] == "camada_ouro"
    assert _setor(resumo)["dado_desatualizado"] is True


def test_api_de_volta_fecha_o_incidente(novo_robo, servidor):
    robo = novo_robo(open_meteo_url="http://127.0.0.1:9/fora-do-ar")
    robo.executar_ciclo(AGORA)
    robo.cfg.open_meteo_url = servidor.url
    resumo = robo.executar_ciclo(AGORA + timedelta(minutes=15))
    assert resumo["status"] == "concluido"
    assert not robo.db.execute("SELECT 1 FROM incidentes WHERE chave='fonte_open_meteo'").fetchone()
    assert "incidente_resolvido" in (robo.cfg.saida_dir / "avisos_operador.jsonl").read_text(encoding="utf-8")


def test_dado_incompleto_nao_baixa_nem_encerra_o_alerta(novo_robo, cena):
    robo = novo_robo()
    cena.definir(AGORA, S01=dict(acumulado=100, chuva_hora=20, umidade=85))
    robo.executar_ciclo(AGORA, replay=True)

    # Sensor cai e a chuva some: o cálculo daria Observação, mas falta dado para afirmar isso.
    agora = AGORA + timedelta(minutes=45)
    cena.definir(agora, sem_sensor=("S01",), S01=dict(acumulado=0, chuva_hora=0))
    resumo = robo.executar_ciclo(agora, replay=True)
    s = _setor(resumo)
    assert s["nivel_calculado"] == 1 and s["nivel"] == 3 and s["nivel_mantido"] is True
    assert [a["tipo"] for a in _alertas(robo)] == ["alerta"]


# ---------------------------------------------------------------- cenário de falha: arquivos

def test_arquivo_invalido_vai_para_quarentena_e_o_ciclo_segue(novo_robo, cena):
    (cena.chegada / "relatos").mkdir(exist_ok=True)
    ruim = cena.chegada / "relatos" / f"relatos_{AGORA.date()}.json"
    ruim.write_text("isto não é json\n{quebrado\n", encoding="utf-8")
    robo = novo_robo()
    resumo = robo.executar_ciclo(AGORA, replay=True)
    assert resumo["status"] == "concluido_com_falhas"
    assert resumo["contagens"]["setores_processados"] == 2
    assert ruim.exists()  # A chegada/ pertence ao Airflow: o robô copia, não apaga.
    assert (robo.cfg.quarentena_dir / "relatos" / ruim.name).exists()
    motivos = robo.db.execute("SELECT motivo FROM quarentena").fetchall()
    assert motivos[0]["motivo"] == "nenhum registro JSON válido"
    robo.executar_ciclo(AGORA + timedelta(minutes=15), replay=True)
    assert len(robo.db.execute("SELECT * FROM quarentena").fetchall()) == 1


def test_cadastro_invalido_nao_copia_dados_pessoais_para_a_quarentena(novo_robo, cena):
    arquivo = cena.chegada / "cadastro" / f"cadastro_{AGORA.date()}.json"
    arquivo.write_text("+55 00 90000-0001 Morador Ficticio quebrado\n", encoding="utf-8")
    robo = novo_robo()
    robo.executar_ciclo(AGORA, replay=True)
    assert robo.db.execute("SELECT 1 FROM quarentena").fetchone()
    assert not list((robo.cfg.quarentena_dir / "cadastro").glob("*"))


def test_linhas_ruins_e_duplicadas_sao_contadas_e_descartadas(novo_robo, cena):
    arquivo = cena.chegada / "sensor" / f"sensor_{AGORA.date()}.json"
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    base = json.loads(linhas[0])
    ruins = [linhas[0], "{quebrado", json.dumps({**base, "ts": (AGORA - timedelta(minutes=7)).isoformat(), "umidade_solo_pct": 130}),
             json.dumps({**base, "ts": (AGORA - timedelta(minutes=8)).isoformat(), "chuva_mm": -1}),
             json.dumps({**base, "ts": "2036-01-01T00:00:00"}), json.dumps({**base, "setor_id": "S99"})]
    arquivo.write_text("\n".join(linhas + ruins) + "\n", encoding="utf-8")
    resumo = novo_robo().executar_ciclo(AGORA, replay=True)
    d = resumo["descartes"]
    assert d["sensor_leitura_duplicada"] == 1 and d["sensor_linha_json_invalida"] == 1
    assert d["sensor_umidade_fora_de_0_a_100"] == 1 and d["sensor_chuva_fora_do_limite"] == 1
    assert d["sensor_horario_no_futuro"] == 1 and d["sensor_setor_desconhecido"] == 1


def test_ouro_indisponivel_usa_a_ultima_copia_boa(novo_robo, cena):
    robo = novo_robo()
    robo.executar_ciclo(AGORA, replay=True)
    cena.ouro.unlink()
    resumo = robo.executar_ciclo(AGORA + timedelta(minutes=15), replay=True)
    assert resumo["status"] == "concluido_com_falhas"
    assert resumo["contagens"]["setores_processados"] == 2


def test_sem_catalogo_o_ciclo_falha_de_forma_visivel(novo_robo, cena):
    cena.ouro.unlink()
    robo = novo_robo()
    resumo = robo.executar_ciclo(AGORA, replay=True)
    assert resumo["status"] == "falhou"
    assert any(e["tipo"] == "ciclo_falhou" for e in ler_logs(robo.cfg.logs_dir))
    assert "ciclo_falhou" in (robo.cfg.saida_dir / "avisos_operador.jsonl").read_text(encoding="utf-8")
    assert not (robo.cfg.estado_dir / "robo.lock").exists()


# ---------------------------------------------------------------- sensores

def test_sensor_offline_abre_chamado_e_usa_so_chuva_e_volta(novo_robo, cena):
    robo = novo_robo()
    robo.executar_ciclo(AGORA, replay=True)
    # Última leitura 45 min antes: acima do limite de 30 min.
    resumo = robo.executar_ciclo(AGORA + timedelta(minutes=45), replay=True)
    s = _setor(resumo)
    assert s["sensor"] == "offline" and s["umidade"] is None
    manutencao = _chamados(robo, "manutencao_sensor")
    assert len(manutencao) == 2 and manutencao[0]["status"] == "aberto"

    resumo = robo.executar_ciclo(AGORA + timedelta(minutes=60), replay=True)
    assert len(_chamados(robo, "manutencao_sensor")) == 2  # Não abre de novo.

    agora = AGORA + timedelta(minutes=75)
    cena.definir(agora)
    resumo = robo.executar_ciclo(agora, replay=True)
    assert _setor(resumo)["sensor"] == "online"
    assert {c["status"] for c in _chamados(robo, "manutencao_sensor")} == {"resolvido"}


def test_bateria_baixa_abre_chamado(novo_robo, cena):
    cena.definir(AGORA, S01=dict(bateria=12))
    robo = novo_robo()
    robo.executar_ciclo(AGORA, replay=True)
    chamados = _chamados(robo, "bateria_baixa")
    assert len(chamados) == 1 and chamados[0]["setor_id"] == "S01"


# ---------------------------------------------------------------- cenário de falha: envio

def _ciclo_com_alerta(robo, cena, agora=AGORA):
    cena.definir(agora, S01=dict(acumulado=100, chuva_hora=20, umidade=85))
    return robo.executar_ciclo(agora, replay=True)


def test_falha_no_canal_troca_para_o_proximo(novo_robo, cena):
    robo = novo_robo(simular_falha={"telegram"})
    resumo = _ciclo_com_alerta(robo, cena)
    c = resumo["contagens"]
    assert c["envios_ok"] == 3 and c["envios_por_canal_alternativo"] == 1
    linha = robo.db.execute("SELECT * FROM envios WHERE canal_preferido='telegram'").fetchone()
    assert linha["canal"] == "sms" and linha["tentativas"] == 4  # 3 no telegram e 1 no sms.
    assert _alertas(robo)[0]["status"] == "enviado"


def test_todos_os_canais_fora_fica_na_fila_e_reenvia_no_proximo_ciclo(novo_robo, cena):
    robo = novo_robo(simular_falha={"telegram", "sms", "whatsapp", "email"})
    resumo = _ciclo_com_alerta(robo, cena)
    assert resumo["contagens"]["envios_na_fila"] == 3
    assert _alertas(robo)[0]["status"] == "pendente"

    robo.canais = montar_canais(replace(robo.cfg, simular_falha=set()))
    resumo = robo.executar_ciclo(AGORA + timedelta(minutes=15), replay=True)
    assert resumo["contagens"]["envios_ok"] == 3
    assert _alertas(robo)[0]["status"] == "enviado"
    assert _alertas(robo)[0]["enviado_em"] == (AGORA + timedelta(minutes=15)).isoformat(timespec="minutes")


def test_depois_de_n_ciclos_desiste_e_avisa_o_operador(novo_robo, cena):
    robo = novo_robo(simular_falha={"telegram", "sms", "whatsapp", "email"})
    agora = AGORA
    _ciclo_com_alerta(robo, cena, agora)
    for _ in range(2):
        agora += timedelta(minutes=15)
        resumo = robo.executar_ciclo(agora, replay=True)
    assert resumo["contagens"]["envios_falhos"] == 3
    assert resumo["status"] == "concluido_com_falhas"
    assert _alertas(robo)[0]["status"] == "falhou"
    assert "não foram avisados" in (robo.cfg.saida_dir / "avisos_operador.jsonl").read_text(encoding="utf-8")


def test_telegram_publica_uma_vez_por_alerta_sem_vazar_token(novo_robo, cena, servidor):
    token = "123456:TOKEN-DE-TESTE"
    robo = novo_robo(telegram_token=token, telegram_chat="-100", telegram_url=servidor.url)
    _ciclo_com_alerta(robo, cena)
    assert len(servidor.pedidos) == 1 and "sendMessage" in servidor.pedidos[0]
    assert robo.db.execute("SELECT simulado FROM envios WHERE canal='telegram'").fetchone()[0] == 0
    assert token not in "".join(p.read_text(encoding="utf-8") for p in robo.cfg.logs_dir.glob("*"))


def test_telegram_com_erro_http_troca_de_canal_sem_vazar_token(novo_robo, cena, servidor):
    token = "123456:TOKEN-DE-TESTE"
    servidor.respostas = [500, 500, 500]
    robo = novo_robo(telegram_token=token, telegram_chat="-100", telegram_url=servidor.url)
    resumo = _ciclo_com_alerta(robo, cena)
    assert resumo["contagens"]["envios_por_canal_alternativo"] == 1
    assert robo.db.execute("SELECT canal FROM envios WHERE canal_preferido='telegram'").fetchone()[0] == "sms"
    assert token not in "".join(p.read_text(encoding="utf-8") for p in robo.cfg.logs_dir.glob("*"))


def test_limite_de_envios_por_minuto(novo_robo, cena):
    robo = novo_robo(limite_envios_min=2)
    _ciclo_com_alerta(robo, cena)
    assert robo.esperas and all(0 < e <= 60 for e in robo.esperas)


def test_morador_em_alerta_nao_recebe_duas_vezes_com_reexecucao(novo_robo, cena):
    robo = novo_robo()
    _ciclo_com_alerta(robo, cena)
    arquivos = list((robo.cfg.saida_dir / "caixa_saida").glob("*.jsonl"))
    total = sum(len(a.read_text(encoding="utf-8").splitlines()) for a in arquivos)
    robo.executar_ciclo(AGORA, replay=True)
    assert sum(len(a.read_text(encoding="utf-8").splitlines()) for a in arquivos) == total == 3


# ---------------------------------------------------------------- operação e LGPD

def test_dois_ciclos_ao_mesmo_tempo_nao_rodam(novo_robo):
    robo = novo_robo()
    (robo.cfg.estado_dir / "robo.lock").touch()
    assert robo.executar_ciclo(AGORA, replay=True)["status"] == "ignorado"


def test_erro_em_um_setor_nao_impede_os_outros(novo_robo, monkeypatch):
    robo = novo_robo()
    original = robo._processar_setor

    def com_erro(setor, *args):
        if setor["setor_id"] == "S01":
            raise RuntimeError("erro em +55 00 90000-0001")
        return original(setor, *args)

    monkeypatch.setattr(robo, "_processar_setor", com_erro)
    resumo = robo.executar_ciclo(AGORA, replay=True)
    assert resumo["contagens"]["setores_com_erro"] == 1 and resumo["contagens"]["setores_processados"] == 1
    assert "[telefone]" in resumo["erros"][0]["erro"]
    assert resumo["status"] == "concluido_com_falhas"


def test_sem_salt_o_robo_nao_roda(cfg_factory):
    with pytest.raises(config.ErroConfiguracao):
        cfg_factory(salt="")


def test_hash_igual_ao_da_camada_prata(novo_robo, cena):
    robo = novo_robo()
    _ciclo_com_alerta(robo, cena)
    esperado = hashlib.sha256("salt-de-testeM-S01-0001".encode()).hexdigest()
    assert robo.db.execute("SELECT 1 FROM envios WHERE morador_hash=?", (esperado,)).fetchone()


def test_nenhum_dado_pessoal_nas_saidas(novo_robo, cena):
    robo = novo_robo(simular_falha={"telegram"})
    _ciclo_com_alerta(robo, cena)
    from encosta_rpa.relatorio import gerar_relatorio

    pdf = gerar_relatorio(robo.cfg, robo.db, AGORA.date())
    assert pdf.read_bytes().startswith(b"%PDF")

    textos = [p.read_text(encoding="utf-8") for pasta in (robo.cfg.logs_dir, robo.cfg.saida_dir, robo.cfg.mvp_dados_dir)
              for p in pasta.rglob("*") if p.is_file() and p.suffix in (".jsonl", ".json")]
    tudo = "\n".join(textos)
    assert textos
    for sensivel in ("Morador Ficticio", "+55", "90000-", "M-S01-"):
        assert sensivel not in tudo
    despejo = "\n".join(robo.db.iterdump())
    for sensivel in ("Morador Ficticio", "90000-", "M-S01-"):
        assert sensivel not in despejo
    mvp = (robo.cfg.mvp_dados_dir / "alertas.json").read_text(encoding="utf-8")
    assert "hash" not in mvp


def test_log_tem_o_que_a_auditoria_pede(novo_robo, cena):
    robo = novo_robo()
    _ciclo_com_alerta(robo, cena)
    eventos = ler_logs(robo.cfg.logs_dir)
    tipos = {e["tipo"] for e in eventos}
    assert {"ciclo_iniciado", "setor_avaliado", "alerta_criado", "chamado_aberto", "mvp_atualizado", "ciclo_concluido"} <= tipos
    fim = next(e for e in eventos if e["tipo"] == "ciclo_concluido")
    assert fim["registrado_em"] and fim["execucao_id"] and fim["contagens"]["envios_ok"] == 3
