"""O ciclo do robô: coleta, percorre os setores, decide, age, registra e entrega ao MVP."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from encosta_rpa import banco, fontes, mensagens, motor
from encosta_rpa.auditoria import Auditoria, sanitizar
from encosta_rpa.canais import CADEIA, ErroEnvio, montar_canais
from encosta_rpa.config import Config

FUSO = ZoneInfo("America/Sao_Paulo")
FALHAS_SEGUIDAS_PARA_ABRIR_CIRCUITO = 5
TRAVA_VENCIDA_S = 30 * 60
ALERTAS_NO_MVP = 20


def agora_local() -> datetime:
    return datetime.now(FUSO).replace(tzinfo=None, second=0, microsecond=0)


def montar_entrada(agora: datetime, serie: fontes.SerieChuva, leituras: list[dict], relatos: list[dict],
                   sensor_offline: bool) -> motor.Entrada:
    """Agrega as fontes como `construir_fato` da camada Ouro, com a hora atual ainda em andamento."""
    if serie.ouro is not None:
        o = serie.ouro
        return motor.Entrada(
            chuva_1h=o.get("chuva_1h") or 0.0, chuva_24h=o.get("chuva_24h") or 0.0,
            chuva_72h=o.get("chuva_72h") or 0.0, previsao_6h=o.get("previsao_6h") or 0.0,
            umidade=None if sensor_offline else o.get("umidade_solo_media"),
            relatos_confirmados=sum(1 for r in relatos if r["confirmado"]
                                    and r["ts"].replace(minute=0, second=0) == agora.replace(minute=0, second=0)),
        )

    hora = agora.replace(minute=0, second=0, microsecond=0)
    chuva_sensor: Counter = Counter()
    inclinacao_hora: dict[datetime, float] = {}
    ultima_hora = []
    for l in leituras:
        h = l["ts"].replace(minute=0, second=0, microsecond=0)
        chuva_sensor[h] += l["chuva"]
        inclinacao_hora[h] = max(inclinacao_hora.get(h, l["inclinacao"]), l["inclinacao"])
        if agora - timedelta(hours=1) < l["ts"] <= agora:
            ultima_hora.append(l)

    # A hora atual usa os últimos 60 min do sensor: no início da hora, o bucket ainda estaria quase vazio.
    chuva_agora = max(serie.chuva.get(hora, 0.0), sum(l["chuva"] for l in ultima_hora))

    def chuva_da_hora(h: datetime) -> float:
        return chuva_agora if h == hora else max(serie.chuva.get(h, 0.0), chuva_sensor.get(h, 0.0))

    chuva_24h = sum(chuva_da_hora(hora - timedelta(hours=i)) for i in range(24))
    chuva_72h = sum(chuva_da_hora(hora - timedelta(hours=i)) for i in range(72))
    previsao_6h = sum(serie.previsao.get(hora + timedelta(hours=i), 0.0) for i in range(1, 7))

    umidade, delta = None, None
    if not sensor_offline:
        if ultima_hora:
            umidade = sum(l["umidade"] for l in ultima_hora) / len(ultima_hora)
        janela = [inclinacao_hora[hora - timedelta(hours=i)] for i in range(7)
                  if hora - timedelta(hours=i) in inclinacao_hora]
        if janela:
            delta = max(janela) - min(janela)

    confirmados = sum(1 for r in relatos if r["confirmado"] and r["ts"].replace(minute=0, second=0) == hora)
    return motor.Entrada(chuva_agora, chuva_24h, chuva_72h, previsao_6h, umidade, delta, confirmados)


class Robo:
    def __init__(self, cfg: Config, espera=time.sleep):
        self.cfg = cfg
        self.espera = espera
        self.db = banco.conectar(cfg.estado_dir / "robo.db")
        self.auditoria = Auditoria(cfg.logs_dir)
        self.canais = montar_canais(cfg)
        self.open_meteo = fontes.OpenMeteo(cfg, espera=espera)
        self._envios_janela: list[float] = []

    # ------------------------------------------------------------------ ciclo

    def executar_ciclo(self, agora: datetime | None = None, replay: bool = False) -> dict:
        agora = agora or agora_local()
        execucao_id = f"X-{agora:%Y%m%dT%H%M}-{uuid.uuid4().hex[:6]}"
        self.auditoria.iniciar(execucao_id, agora)
        modo = "replay" if replay else "ao_vivo"
        trava = self._obter_trava()
        if trava is None:
            self.auditoria.evento("ciclo_ignorado", motivo="outro ciclo ainda em execução")
            return {"execucao_id": execucao_id, "status": "ignorado", "agora": agora.isoformat(timespec="minutes")}

        r = Counter()
        resumo = {"execucao_id": execucao_id, "agora": agora.isoformat(timespec="minutes"), "modo": modo,
                  "setores": [], "erros": []}
        self.db.execute("INSERT INTO execucoes (id, inicio, modo, status) VALUES (?, ?, ?, 'em_andamento')",
                        (execucao_id, agora.isoformat(timespec="minutes"), modo))
        self.db.commit()
        self.auditoria.evento("ciclo_iniciado", modo=modo)
        try:
            ctx = fontes.Contexto()
            if not replay:
                self._rodar_ponte_sensores(agora, ctx)
            ouro = fontes.carregar_ouro(self.cfg, ctx)
            catalogo = ouro["setores"]
            ids = {s["setor_id"] for s in catalogo}
            leituras = fontes.carregar_sensores(self.cfg, agora, ids, ctx)
            relatos = fontes.carregar_relatos(self.cfg, agora, ids, ctx)
            moradores = fontes.carregar_moradores(self.cfg, agora, ids, ctx)
            if replay:
                chuvas = fontes.chuva_de_arquivos(self.cfg, agora, ids, ctx)
            else:
                chuvas = self.open_meteo.obter(catalogo, agora, ctx, self.auditoria)
                self._conferir_atraso_ouro(ouro, agora)
            self._registrar_quarentena(ctx, agora)
            self._tratar_problemas(ctx, agora)

            # Repetição: um setor com erro é registrado e não impede os outros.
            for setor in catalogo:
                try:
                    with self.db:
                        info = self._processar_setor(setor, agora, chuvas[setor["setor_id"]],
                                                     leituras[setor["setor_id"]], relatos[setor["setor_id"]],
                                                     moradores[setor["setor_id"]], execucao_id, r)
                    resumo["setores"].append(info)
                    r["setores_processados"] += 1
                except Exception as erro:  # noqa: BLE001 - nunca derrubar os demais setores
                    r["setores_com_erro"] += 1
                    mensagem = sanitizar(f"{type(erro).__name__}: {erro}")
                    resumo["erros"].append({"setor_id": setor["setor_id"], "erro": mensagem})
                    self.auditoria.evento("erro_setor", setor_id=setor["setor_id"], erro=mensagem)

            self._despachar(agora, r)
            self._concluir_alertas(agora)
            self._exportar_mvp(agora, execucao_id, modo, catalogo)
            self._gerar_relatorio_do_dia_anterior(agora, r)

            r["descartes"] = sum(ctx.descartes.values())
            resumo["descartes"] = dict(ctx.descartes)
            resumo["problemas"] = [p["mensagem"] for p in ctx.problemas]
            houve_falha = ctx.problemas or r["setores_com_erro"] or r["envios_falhos"] or r["tentativas_falhas"]
            status = "concluido_com_falhas" if houve_falha else "concluido"
        except Exception as erro:  # noqa: BLE001 - falha geral vira registro e aviso, nunca silêncio
            status = "falhou"
            mensagem = sanitizar(f"{type(erro).__name__}: {erro}")
            resumo["erros"].append({"erro": mensagem})
            self.auditoria.evento("ciclo_falhou", erro=mensagem,
                                  rastreio=sanitizar(traceback.format_exc(limit=3)))
            self._abrir_incidente("ciclo_falhou", f"O ciclo do robô falhou: {mensagem}", agora)
        finally:
            trava.unlink(missing_ok=True)

        resumo["status"] = status
        resumo["contagens"] = dict(r)
        self.db.execute("UPDATE execucoes SET fim=?, status=?, resumo=? WHERE id=?",
                        (agora.isoformat(timespec="minutes"), status,
                         json.dumps(resumo, ensure_ascii=False, default=str), execucao_id))
        self.db.commit()
        self.auditoria.evento("ciclo_concluido", status=status, contagens=dict(r), descartes=resumo.get("descartes", {}),
                              erros=resumo["erros"], problemas=resumo.get("problemas", []))
        return resumo

    def _obter_trava(self) -> Path | None:
        """Impede dois ciclos ao mesmo tempo. Uma trava antiga (processo morto) é descartada."""
        caminho = self.cfg.estado_dir / "robo.lock"
        for _ in range(2):
            try:
                os.close(os.open(caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return caminho
            except FileExistsError:
                if time.time() - caminho.stat().st_mtime < TRAVA_VENCIDA_S:
                    return None
                caminho.unlink(missing_ok=True)
        return None

    # ------------------------------------------------------------------ fontes

    def _rodar_ponte_sensores(self, agora: datetime, ctx: fontes.Contexto) -> None:
        """Enquanto o robô físico não publica por MQTT, o simulador do pipeline faz o papel do campo."""
        if not self.cfg.dados_repo_dir:
            return
        try:
            caminho = str(self.cfg.dados_repo_dir / "dags")
            if caminho not in sys.path:
                sys.path.insert(0, caminho)
            from encosta import simulador  # type: ignore[import-not-found]

            for fonte, registros in (("sensor", simulador.leituras_sensor(agora.date())),
                                     ("relatos", simulador.relatos(agora.date()))):
                pasta = self.cfg.estado_dir / "tempo_real" / fonte
                pasta.mkdir(parents=True, exist_ok=True)
                texto = "\n".join(json.dumps(x, ensure_ascii=False) for x in registros) + "\n"
                (pasta / f"{fonte}_{agora.date()}.json").write_text(texto, encoding="utf-8")
        except Exception as erro:  # noqa: BLE001
            ctx.problema("ponte_sensores", f"não foi possível gerar as leituras simuladas ({type(erro).__name__})")

    def _conferir_atraso_ouro(self, ouro: dict, agora: datetime) -> None:
        try:
            atraso = agora - datetime.fromisoformat(ouro["gerado_ate"])
        except (KeyError, TypeError, ValueError):
            return
        if atraso > timedelta(hours=72):
            self._abrir_incidente("ouro_atrasada", f"A camada Ouro está sem atualizar há {atraso.days} dias.", agora)
        else:
            self._fechar_incidente("ouro_atrasada", agora)

    def _registrar_quarentena(self, ctx: fontes.Contexto, agora: datetime) -> None:
        for item in ctx.quarentena:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO quarentena (sha256, arquivo, motivo, registrado_em) VALUES (?, ?, ?, ?)",
                (item["sha256"], item["arquivo"], item["motivo"], agora.isoformat(timespec="minutes")))
            if cur.rowcount:
                self.auditoria.evento("arquivo_em_quarentena", arquivo=item["arquivo"], motivo=item["motivo"])
        self.db.commit()

    def _tratar_problemas(self, ctx: fontes.Contexto, agora: datetime) -> None:
        """Uma fonte com problema abre um incidente. Quando volta ao normal, o incidente é fechado."""
        com_problema = {p["fonte"]: p["mensagem"] for p in ctx.problemas}
        for fonte, mensagem in com_problema.items():
            self._abrir_incidente(f"fonte_{fonte}", mensagem, agora)
        for fonte in ("open_meteo", "ouro", "sensor", "relatos", "cadastro", "chuva", "previsao", "ponte_sensores"):
            if fonte not in com_problema:
                self._fechar_incidente(f"fonte_{fonte}", agora)

    # ------------------------------------------------------------------ decisão

    def _processar_setor(self, setor, agora, serie, leituras, relatos, moradores, execucao_id, r) -> dict:
        setor_id = setor["setor_id"]
        anterior = self.db.execute("SELECT * FROM estado_setor WHERE setor_id=?", (setor_id,)).fetchone()
        nivel_anterior = anterior["nivel_ordem"] if anterior else 1
        episodio = anterior["episodio"] if anterior else 1

        sensor = self._avaliar_sensor(setor, leituras, agora, execucao_id, r)
        offline = sensor["status"] != "online"
        entrada = montar_entrada(agora, serie, leituras, relatos, offline)
        calculado = motor.calcular(entrada)

        # Dado incompleto pode subir o nível, mas nunca baixar nem encerrar um alerta.
        degradado = serie.desatualizado or offline
        nivel = calculado.nivel_ordem
        fatores = calculado.fatores
        mantido = degradado and nivel < nivel_anterior
        if mantido:
            nivel = nivel_anterior
            fatores = "; ".join(x for x in (fatores, "nível mantido porque há dados incompletos") if x)
            r["niveis_mantidos"] += 1

        if nivel > nivel_anterior:
            decisao = "subiu"
        elif nivel == nivel_anterior:
            decisao = "igual"
        elif nivel == 1:
            decisao = "encerrou"
        else:
            decisao = "reduziu"
        r[f"decisao_{decisao}"] += 1

        alerta_id = None
        if decisao == "subiu":
            texto = mensagens.alerta(setor["nome"], motor.NIVEIS[nivel], nivel, fatores, degradado)
            alerta_id = self._registrar_alerta(setor_id, "alerta", nivel, nivel_anterior, fatores, texto, agora,
                                               episodio, moradores, execucao_id, serie.desatualizado, r)
            if nivel >= 3:
                prioridade = "urgente" if nivel == 4 else "alta"
                self._abrir_chamado("vistoria", setor_id, prioridade,
                                    f"Vistoria em {setor['nome']}: {motor.NIVEIS[nivel]}. {fatores}.",
                                    agora, execucao_id, r)
            if nivel == 4:
                self.auditoria.evento("sirene_acionada", setor_id=setor_id,
                                      detalhe="comando para o robô sentinela; decisão de remoção é da Defesa Civil")
        elif decisao == "encerrou":
            alerta_id = self._registrar_alerta(setor_id, "encerramento", 1, nivel_anterior, fatores,
                                               mensagens.encerramento(setor["nome"]), agora, episodio, moradores,
                                               execucao_id, False, r)
            episodio += 1  # Um novo aumento depois do encerramento precisa avisar de novo.

        self.db.execute(
            """INSERT OR REPLACE INTO estado_setor (setor_id, nivel_ordem, episodio, fatores, atualizado_em,
               dado_desatualizado, nivel_mantido, chuva_1h, chuva_24h, chuva_72h, previsao_6h, umidade_solo_media,
               sensor_status, minutos_sem_leitura) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (setor_id, nivel, episodio, fatores, agora.isoformat(timespec="minutes"), int(serie.desatualizado),
             int(mantido), round(entrada.chuva_1h, 2), round(entrada.chuva_24h, 2), round(entrada.chuva_72h, 2),
             round(entrada.previsao_6h, 2), None if entrada.umidade is None else round(entrada.umidade, 2),
             sensor["status"], sensor["minutos"]))

        info = {"setor_id": setor_id, "nome": setor["nome"], "nivel_anterior": nivel_anterior, "nivel": nivel,
                "nivel_calculado": calculado.nivel_ordem, "decisao": decisao, "fatores": fatores,
                "chuva_1h": round(entrada.chuva_1h, 2), "chuva_72h": round(entrada.chuva_72h, 2),
                "previsao_6h": round(entrada.previsao_6h, 2),
                "umidade": None if entrada.umidade is None else round(entrada.umidade, 2),
                "sensor": sensor["status"], "fonte_chuva": serie.origem,
                "dado_desatualizado": serie.desatualizado, "nivel_mantido": mantido, "alerta_id": alerta_id}
        self.auditoria.evento("setor_avaliado", **info)
        return info

    def _avaliar_sensor(self, setor, leituras, agora, execucao_id, r) -> dict:
        setor_id = setor["setor_id"]
        if not leituras:
            minutos, bateria = None, None
        else:
            ultima = leituras[-1]
            minutos, bateria = int((agora - ultima["ts"]).total_seconds() // 60), ultima["bateria"]

        if minutos is None or minutos > self.cfg.sensor_offline_min:
            r["sensores_offline"] += 1
            sem_leitura = "sem leitura registrada" if minutos is None else f"sem leitura há {minutos} min"
            self._abrir_chamado("manutencao_sensor", setor_id, "alta",
                                f"Sensor de {setor['nome']} {sem_leitura}. O setor usa só os dados de chuva.",
                                agora, execucao_id, r)
            status = "offline"
        else:
            status = "online"
            self._fechar_chamado("manutencao_sensor", setor_id, agora, r)

        if bateria is not None and bateria < self.cfg.bateria_minima:
            self._abrir_chamado("bateria_baixa", setor_id, "media",
                                f"Bateria do sensor de {setor['nome']} em {bateria:.0f}%.", agora, execucao_id, r)
        elif bateria is not None:
            self._fechar_chamado("bateria_baixa", setor_id, agora, r)
        return {"status": status, "minutos": minutos}

    def _registrar_alerta(self, setor_id, tipo, nivel, nivel_anterior, fatores, texto, agora, episodio, moradores,
                          execucao_id, desatualizado, r) -> str | None:
        """Grava o alerta e a fila de envios na mesma transação, antes de enviar: se o robô cair, nada se perde."""
        janela = int(agora.timestamp() // (self.cfg.janela_idempotencia_min * 60))
        chave = f"{setor_id}|{tipo}|{nivel}|{janela}|e{episodio}"
        if self.db.execute("SELECT 1 FROM alertas WHERE chave=?", (chave,)).fetchone():
            r["alertas_duplicados"] += 1
            self.auditoria.evento("alerta_duplicado_descartado", setor_id=setor_id, chave=chave)
            return None
        alerta_id = f"A-{uuid.uuid4().hex[:12]}"
        status = "pendente" if moradores else "sem_destinatarios"
        self.db.execute(
            """INSERT INTO alertas (id, chave, setor_id, tipo, nivel_ordem, nivel, nivel_anterior, fatores, mensagem,
               criado_em, status, execucao_id, dado_desatualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (alerta_id, chave, setor_id, tipo, nivel, motor.NIVEIS[nivel], nivel_anterior, fatores, texto,
             agora.isoformat(timespec="minutes"), status, execucao_id, int(desatualizado)))
        # Repetição dentro do setor: um envio na fila para cada morador.
        for morador in moradores:
            canal = morador["canal"] if morador["canal"] in CADEIA else "sms"
            self.db.execute(
                "INSERT INTO envios (alerta_id, morador_hash, canal_preferido, status) VALUES (?, ?, ?, 'pendente')",
                (alerta_id, morador["hash"], canal))
        r["alertas_criados" if tipo == "alerta" else "encerramentos_criados"] += 1
        self.auditoria.evento("alerta_criado", alerta_id=alerta_id, setor_id=setor_id, alerta_tipo=tipo, nivel=nivel,
                              nivel_anterior=nivel_anterior, chave=chave, destinatarios=len(moradores))
        if not moradores:
            self._abrir_incidente(f"sem_moradores_{setor_id}", f"Setor {setor_id} sem morador cadastrado para avisar.", agora)
        return alerta_id

    # ------------------------------------------------------------------ chamados e incidentes

    def _abrir_chamado(self, tipo, setor_id, prioridade, descricao, agora, execucao_id, r) -> None:
        aberto = self.db.execute("SELECT 1 FROM chamados WHERE tipo=? AND setor_id=? AND status='aberto'",
                                 (tipo, setor_id)).fetchone()
        if aberto:
            return
        chamado_id = f"C-{uuid.uuid4().hex[:10]}"
        self.db.execute(
            """INSERT INTO chamados (id, tipo, setor_id, prioridade, descricao, status, aberto_em, execucao_id)
               VALUES (?, ?, ?, ?, ?, 'aberto', ?, ?)""",
            (chamado_id, tipo, setor_id, prioridade, descricao, agora.isoformat(timespec="minutes"), execucao_id))
        r["chamados_abertos"] += 1
        self.auditoria.evento("chamado_aberto", chamado_id=chamado_id, chamado_tipo=tipo, setor_id=setor_id,
                              prioridade=prioridade)

    def _fechar_chamado(self, tipo, setor_id, agora, r) -> None:
        """Só fecha o que o próprio robô consegue confirmar. Vistoria é fechada por uma pessoa."""
        cur = self.db.execute(
            "UPDATE chamados SET status='resolvido', fechado_em=? WHERE tipo=? AND setor_id=? AND status='aberto'",
            (agora.isoformat(timespec="minutes"), tipo, setor_id))
        if cur.rowcount:
            r["chamados_resolvidos"] += cur.rowcount
            self.auditoria.evento("chamado_resolvido", chamado_tipo=tipo, setor_id=setor_id)

    def _abrir_incidente(self, chave: str, descricao: str, agora: datetime) -> None:
        """Avisa o operador uma vez por incidente, para o aviso não virar ruído a cada 15 minutos."""
        cur = self.db.execute("INSERT OR IGNORE INTO incidentes (chave, descricao, aberto_em) VALUES (?, ?, ?)",
                              (chave, descricao, agora.isoformat(timespec="minutes")))
        self.db.commit()
        if cur.rowcount:
            self._avisar_operador("incidente_aberto", chave, descricao, agora)

    def _fechar_incidente(self, chave: str, agora: datetime) -> None:
        cur = self.db.execute("DELETE FROM incidentes WHERE chave=?", (chave,))
        self.db.commit()
        if cur.rowcount:
            self._avisar_operador("incidente_resolvido", chave, f"{chave}: voltou ao normal.", agora)

    def _avisar_operador(self, tipo: str, chave: str, descricao: str, agora: datetime) -> None:
        self.auditoria.evento("aviso_operador", aviso=tipo, chave=chave, descricao=descricao)
        with (self.cfg.saida_dir / "avisos_operador.jsonl").open("a", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write(sanitizar(json.dumps({"em": agora.isoformat(timespec="minutes"), "aviso": tipo, "chave": chave,
                                                "descricao": descricao}, ensure_ascii=False)) + "\n")
        print(f"[operador] {tipo}: {sanitizar(descricao)}", file=sys.stderr)

    # ------------------------------------------------------------------ envio

    def _respeitar_limite(self) -> None:
        """No máximo N tentativas por minuto, para não ser bloqueado pelo provedor."""
        instante = time.monotonic()
        self._envios_janela = [t for t in self._envios_janela if instante - t < 60]
        if len(self._envios_janela) >= self.cfg.limite_envios_min:
            self.espera(max(0.0, 60 - (instante - self._envios_janela[0])))
            self._envios_janela = []
        self._envios_janela.append(time.monotonic())

    def _despachar(self, agora: datetime, r: Counter) -> None:
        """Esvazia a fila, novos e reenvios: tenta N vezes em cada canal e passa para o próximo."""
        fila = self.db.execute(
            """SELECT e.*, a.mensagem, a.setor_id FROM envios e JOIN alertas a ON a.id = e.alerta_id
               WHERE e.status='pendente' ORDER BY a.nivel_ordem DESC, a.criado_em""").fetchall()
        falhas_seguidas: Counter = Counter()
        fora_do_ar: set[str] = set()
        for envio in fila:
            canal_usado, erro_final, tentativas = None, None, envio["tentativas"]
            for canal in CADEIA[envio["canal_preferido"]]:
                if canal in fora_do_ar:
                    erro_final = f"canal {canal} fora do ar neste ciclo"
                    continue
                for _ in range(self.cfg.tentativas_canal):
                    self._respeitar_limite()
                    tentativas += 1
                    try:
                        self.canais[canal].enviar(envio["alerta_id"], envio["morador_hash"], envio["mensagem"], agora)
                        canal_usado = canal
                        falhas_seguidas[canal] = 0
                        break
                    except ErroEnvio as erro:
                        erro_final = sanitizar(str(erro))
                        falhas_seguidas[canal] += 1
                        r["tentativas_falhas"] += 1
                if canal_usado:
                    break
                if falhas_seguidas[canal] >= FALHAS_SEGUIDAS_PARA_ABRIR_CIRCUITO:
                    fora_do_ar.add(canal)
                    self.auditoria.evento("canal_fora_do_ar", canal=canal, erro=erro_final)
                    self._abrir_incidente(f"canal_{canal}", f"Canal {canal} falhou repetidamente: {erro_final}", agora)

            if canal_usado:
                if canal_usado != envio["canal_preferido"]:
                    r["envios_por_canal_alternativo"] += 1
                self.db.execute(
                    """UPDATE envios SET canal=?, status='enviado', tentativas=?, simulado=?, erro=NULL, enviado_em=?
                       WHERE alerta_id=? AND morador_hash=?""",
                    (canal_usado, tentativas, int(self.canais[canal_usado].simulado),
                     agora.isoformat(timespec="minutes"), envio["alerta_id"], envio["morador_hash"]))
                r["envios_ok"] += 1
                r[f"envios_{canal_usado}"] += 1
            else:
                ciclos = envio["ciclos"] + 1
                esgotou = ciclos >= self.cfg.ciclos_max_reenvio
                self.db.execute(
                    "UPDATE envios SET status=?, tentativas=?, ciclos=?, erro=? WHERE alerta_id=? AND morador_hash=?",
                    ("falhou" if esgotou else "pendente", tentativas, ciclos, erro_final,
                     envio["alerta_id"], envio["morador_hash"]))
                r["envios_falhos" if esgotou else "envios_na_fila"] += 1
                if esgotou:
                    self.auditoria.evento("envio_desistiu", alerta_id=envio["alerta_id"],
                                          morador_hash=envio["morador_hash"][:12], erro=erro_final)
                    self._abrir_incidente(f"envio_{envio['alerta_id']}",
                                          f"Moradores de {envio['setor_id']} não foram avisados por nenhum canal.", agora)
        self.db.commit()
        # Canais que funcionaram neste ciclo saem da lista de incidentes.
        for canal in self.canais:
            if canal not in fora_do_ar and r.get(f"envios_{canal}"):
                self._fechar_incidente(f"canal_{canal}", agora)

    def _concluir_alertas(self, agora: datetime) -> None:
        """Atualiza a tabela `alertas` com o que aconteceu nos envios."""
        for alerta in self.db.execute("SELECT id FROM alertas WHERE status IN ('pendente', 'parcial')").fetchall():
            linhas = self.db.execute(
                "SELECT status, canal, enviado_em FROM envios WHERE alerta_id=?", (alerta["id"],)).fetchall()
            enviados = [l for l in linhas if l["status"] == "enviado"]
            pendentes = sum(1 for l in linhas if l["status"] == "pendente")
            if enviados and len(enviados) == len(linhas):
                status = "enviado"
            elif enviados:
                status = "parcial"
            elif pendentes:
                status = "pendente"
            else:
                status = "falhou"
            canais = ",".join(sorted({l["canal"] for l in enviados}))
            primeiro = min((l["enviado_em"] for l in enviados), default=None)
            self.db.execute("UPDATE alertas SET status=?, canal=?, enviado_em=? WHERE id=?",
                            (status, canais or None, primeiro, alerta["id"]))
        self.db.commit()

    # ------------------------------------------------------------------ saída para o MVP

    def _exportar_mvp(self, agora: datetime, execucao_id: str, modo: str, catalogo: list[dict]) -> None:
        """Contrato com a tela do MVP. Só agregados por setor: nenhum hash nem dado pessoal."""
        nomes = {s["setor_id"]: s["nome"] for s in catalogo}
        setores = []
        for e in self.db.execute("SELECT * FROM estado_setor ORDER BY setor_id").fetchall():
            vistoria = self.db.execute("SELECT 1 FROM chamados WHERE setor_id=? AND tipo='vistoria' AND status='aberto'",
                                       (e["setor_id"],)).fetchone()
            setores.append({
                "setor_id": e["setor_id"], "nivel_ordem": e["nivel_ordem"], "nivel_risco": motor.NIVEIS[e["nivel_ordem"]],
                "fatores": e["fatores"], "atualizado_em": e["atualizado_em"], "chuva_1h": e["chuva_1h"],
                "chuva_24h": e["chuva_24h"], "chuva_72h": e["chuva_72h"], "previsao_6h": e["previsao_6h"],
                "umidade_solo_media": e["umidade_solo_media"], "sensor_status": e["sensor_status"],
                "minutos_sem_leitura": e["minutos_sem_leitura"], "dado_desatualizado": bool(e["dado_desatualizado"]),
                "nivel_mantido": bool(e["nivel_mantido"]), "vistoria_aberta": bool(vistoria),
            })
        alertas = []
        for a in self.db.execute(
                "SELECT * FROM alertas ORDER BY criado_em DESC, nivel_ordem DESC LIMIT ?", (ALERTAS_NO_MVP,)).fetchall():
            contagem = self.db.execute(
                """SELECT COUNT(*) AS total, SUM(status='enviado') AS enviados, SUM(simulado=1) AS simulados
                   FROM envios WHERE alerta_id=?""", (a["id"],)).fetchone()
            alertas.append({
                "id": a["id"], "setor_id": a["setor_id"], "setor": nomes.get(a["setor_id"], a["setor_id"]), "tipo": a["tipo"],
                "nivel": a["nivel"], "nivel_ordem": a["nivel_ordem"], "fatores": a["fatores"], "mensagem": a["mensagem"],
                "criado_em": a["criado_em"], "enviado_em": a["enviado_em"], "canal": a["canal"], "status": a["status"],
                "moradores_avisados": contagem["enviados"] or 0, "moradores_total": contagem["total"] or 0,
                "envio_simulado": (contagem["simulados"] or 0) > 0,
            })
        chamados = self.db.execute("SELECT COUNT(*) FROM chamados WHERE status='aberto'").fetchone()[0]
        documento = {
            "tabela_origem": "robo_rpa.alertas", "gerado_em": agora.isoformat(timespec="minutes"),
            "execucao_id": execucao_id, "modo": modo, "intervalo_min": self.cfg.intervalo_min,
            "resumo": {"chamados_abertos": chamados,
                       "setores_em_alerta": sum(1 for s in setores if s["nivel_ordem"] >= 3),
                       "sensores_offline": sum(1 for s in setores if s["sensor_status"] == "offline")},
            "setores": setores, "alertas": alertas,
        }
        destino = self.cfg.mvp_dados_dir / "alertas.json"
        temporario = destino.with_suffix(".tmp")
        temporario.write_text(json.dumps(documento, ensure_ascii=False, indent=1), encoding="utf-8")
        temporario.replace(destino)  # Atômico: a tela nunca lê um arquivo pela metade.
        self.auditoria.evento("mvp_atualizado", arquivo="alertas.json", setores=len(setores), alertas=len(alertas))

    def _gerar_relatorio_do_dia_anterior(self, agora: datetime, r: Counter) -> None:
        """Decisão: na primeira execução de cada dia, gera o relatório do dia que terminou."""
        from encosta_rpa.relatorio import caminho_relatorio, gerar_relatorio

        dia = (agora - timedelta(days=1)).date()
        if caminho_relatorio(self.cfg, dia).exists():
            return
        if not self.db.execute("SELECT 1 FROM execucoes WHERE inicio LIKE ? LIMIT 1", (f"{dia}%",)).fetchone():
            return
        try:
            arquivo = gerar_relatorio(self.cfg, self.db, dia)
            r["relatorios_gerados"] += 1
            self.auditoria.evento("relatorio_gerado", arquivo=arquivo.name)
            self._fechar_incidente("relatorio", agora)
        except Exception as erro:  # noqa: BLE001 - o relatório não pode impedir os alertas
            self._abrir_incidente("relatorio", f"Falha ao gerar o relatório de {dia}: {type(erro).__name__}", agora)
