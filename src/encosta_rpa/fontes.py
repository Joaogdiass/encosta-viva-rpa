"""Leitura e validação das fontes. Nada aqui altera a pasta chegada/, que pertence ao Airflow."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from encosta_rpa.config import RAIZ

CHUVA_MAX_MM_H = 150.0
FOLGA_LEITURA_FUTURA = timedelta(days=2)  # O arquivo do dia traz horas que ainda não aconteceram.
FUSO = "America/Sao_Paulo"
TENTATIVAS_API = 3


class ErroFonte(Exception):
    """Fonte indispensável não pôde ser lida nem recuperada."""


@dataclass
class Contexto:
    """O que cada leitura registrou: descartes por motivo, problemas e arquivos em quarentena."""

    descartes: Counter = field(default_factory=Counter)
    problemas: list[dict] = field(default_factory=list)
    quarentena: list[dict] = field(default_factory=list)

    def problema(self, fonte: str, mensagem: str) -> None:
        self.problemas.append({"fonte": fonte, "mensagem": mensagem})


@dataclass
class SerieChuva:
    chuva: dict[datetime, float] = field(default_factory=dict)
    previsao: dict[datetime, float] = field(default_factory=dict)
    origem: str = "open_meteo"
    desatualizado: bool = False
    coletado_em: str | None = None
    ouro: dict | None = None  # Último recurso: valores agregados da camada Ouro.


def _mover_para_quarentena(arquivo: Path, fonte: str, motivo: str, cfg, ctx: Contexto) -> None:
    """Copia o arquivo inválido (a chegada/ é do Airflow) e registra o motivo uma vez por conteúdo."""
    conteudo = arquivo.read_bytes()
    destino = cfg.quarentena_dir / fonte
    destino.mkdir(parents=True, exist_ok=True)
    # O cadastro tem dados pessoais: fica só o registro do motivo, sem cópia do conteúdo.
    if fonte != "cadastro":
        shutil.copyfile(arquivo, destino / arquivo.name)
    ctx.quarentena.append({
        "sha256": hashlib.sha256(conteudo).hexdigest(),
        "arquivo": f"{fonte}/{arquivo.name}",
        "motivo": motivo,
    })


def ler_jsonl(arquivo: Path, fonte: str, cfg, ctx: Contexto) -> list[dict]:
    """Lê JSON Lines. Linha ruim é descartada e contada; arquivo sem nenhuma linha boa vai para a quarentena."""
    try:
        texto = arquivo.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as erro:
        _mover_para_quarentena(arquivo, fonte, f"não foi possível ler ({type(erro).__name__})", cfg, ctx)
        ctx.problema(fonte, f"{arquivo.name}: arquivo ilegível, enviado à quarentena")
        return []
    registros, invalidas = [], 0
    for linha in texto.splitlines():
        if not linha.strip():
            continue
        try:
            registro = json.loads(linha)
            if not isinstance(registro, dict):
                raise ValueError
            registros.append(registro)
        except ValueError:
            invalidas += 1
    if invalidas:
        ctx.descartes[f"{fonte}_linha_json_invalida"] += invalidas
    if not registros:
        _mover_para_quarentena(arquivo, fonte, "nenhum registro JSON válido", cfg, ctx)
        ctx.problema(fonte, f"{arquivo.name}: nenhum registro válido, enviado à quarentena")
    return registros


def _arquivos_recentes(pastas: list[Path], fonte: str, agora: datetime, dias: int) -> list[Path]:
    """Arquivos cuja data no nome cai na janela. O arquivo de D traz medições de D-1, daí o +1."""
    inicio, fim = agora.date() - timedelta(days=dias), agora.date() + timedelta(days=1)
    achados = []
    for pasta in pastas:
        for arquivo in sorted(pasta.glob(f"{fonte}_*.json")):
            try:
                dia = date.fromisoformat(arquivo.stem.removeprefix(f"{fonte}_"))
            except ValueError:
                continue
            if inicio <= dia <= fim:
                achados.append(arquivo)
    return achados


def _pastas(cfg, fonte: str) -> list[Path]:
    return [cfg.chegada_dir / fonte, cfg.estado_dir / "tempo_real" / fonte]


def carregar_ouro(cfg, ctx: Contexto) -> dict:
    """Catálogo de setores e valores da camada Ouro. Se a origem falhar, usa a última cópia boa."""
    copia = cfg.estado_dir / "ultimo_ouro.json"
    origem = cfg.ouro_origem
    try:
        if origem.startswith(("http://", "https://")):
            pedido = urllib.request.Request(origem, headers={"User-Agent": "encosta-viva-rpa/1.0"})
            with urllib.request.urlopen(pedido, timeout=20) as resposta:
                bruto = resposta.read().decode("utf-8")
        else:
            bruto = (RAIZ / origem).read_text(encoding="utf-8")  # Caminho absoluto substitui RAIZ.
        ouro = json.loads(bruto)
        if not ouro.get("setores") or any("setor_id" not in s for s in ouro["setores"]):
            raise ValueError("contrato sem a lista de setores")
    except (OSError, ValueError, urllib.error.URLError) as erro:
        ctx.problema("ouro", f"origem indisponível ou inválida ({type(erro).__name__}); usando a última cópia boa")
        try:
            return json.loads(copia.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ErroFonte("Sem o catálogo de setores: nem a origem nem a cópia local puderam ser lidas.") from None
    copia.write_text(bruto, encoding="utf-8")
    return ouro


def carregar_sensores(cfg, agora: datetime, setores: set[str], ctx: Contexto) -> dict[str, list[dict]]:
    """Leituras válidas por setor, até `agora`, com as mesmas regras de qualidade da Prata."""
    arquivos = _arquivos_recentes(_pastas(cfg, "sensor"), "sensor", agora, cfg.dias_arquivos)
    if not arquivos:
        ctx.problema("sensor", "nenhum arquivo de sensor na janela de leitura")
    limite_passado = agora - timedelta(hours=80)
    vistas: set[tuple] = set()
    por_setor: dict[str, list[dict]] = {s: [] for s in setores}
    for arquivo in arquivos:
        for r in ler_jsonl(arquivo, "sensor", cfg, ctx):
            try:
                setor, sensor = r["setor_id"], r["sensor_id"]
                ts = datetime.fromisoformat(r["ts"])
                umidade, chuva = float(r["umidade_solo_pct"]), float(r["chuva_mm"])
                inclinacao, bateria = float(r["inclinacao_graus"]), float(r["bateria_pct"])
            except (KeyError, TypeError, ValueError):
                ctx.descartes["sensor_campo_invalido"] += 1
                continue
            if ts > agora + FOLGA_LEITURA_FUTURA:
                ctx.descartes["sensor_horario_no_futuro"] += 1
                continue
            if ts > agora or ts < limite_passado:
                continue  # Fora da janela de cálculo: não é erro.
            if setor not in setores:
                ctx.descartes["sensor_setor_desconhecido"] += 1
            elif not 0 <= umidade <= 100:
                ctx.descartes["sensor_umidade_fora_de_0_a_100"] += 1
            elif not 0 <= chuva <= CHUVA_MAX_MM_H:
                ctx.descartes["sensor_chuva_fora_do_limite"] += 1
            elif (setor, sensor, ts) in vistas:
                ctx.descartes["sensor_leitura_duplicada"] += 1
            else:
                vistas.add((setor, sensor, ts))
                por_setor[setor].append({"sensor_id": sensor, "ts": ts, "umidade": umidade, "chuva": chuva,
                                         "inclinacao": inclinacao, "bateria": bateria})
    for leituras in por_setor.values():
        leituras.sort(key=lambda l: l["ts"])
    return por_setor


def carregar_relatos(cfg, agora: datetime, setores: set[str], ctx: Contexto) -> dict[str, list[dict]]:
    arquivos = _arquivos_recentes(_pastas(cfg, "relatos"), "relatos", agora, cfg.dias_arquivos)
    vistos: set[str] = set()
    por_setor: dict[str, list[dict]] = {s: [] for s in setores}
    for arquivo in arquivos:
        for r in ler_jsonl(arquivo, "relatos", cfg, ctx):
            try:
                relato_id, setor = r["relato_id"], r["setor_id"]
                ts = datetime.fromisoformat(r["ts"])
            except (KeyError, TypeError, ValueError):
                ctx.descartes["relato_campo_invalido"] += 1
                continue
            if ts > agora or relato_id in vistos:
                continue
            vistos.add(relato_id)
            if setor not in setores:
                ctx.descartes["relato_setor_desconhecido"] += 1
                continue
            por_setor[setor].append({"ts": ts, "confirmado": bool(r.get("confirmado_visao"))})
    return por_setor


def carregar_moradores(cfg, agora: datetime, setores: set[str], ctx: Contexto) -> dict[str, list[dict]]:
    """LGPD: o nome e o telefone do cadastro nunca são guardados. Só o hash, o setor e o canal."""
    arquivos = sorted((cfg.chegada_dir / "cadastro").glob("cadastro_*.json"))
    por_setor: dict[str, list[dict]] = {s: [] for s in setores}
    if not arquivos:
        ctx.problema("cadastro", "nenhum arquivo de cadastro encontrado")
        return por_setor
    vistos: set[str] = set()
    for r in ler_jsonl(arquivos[-1], "cadastro", cfg, ctx):
        morador_id, setor = r.get("morador_id"), r.get("setor_id")
        if not morador_id or setor not in setores:
            ctx.descartes["cadastro_invalido"] += 1
            continue
        # Igual a sha2(concat(salt, morador_id), 256) da camada Prata.
        morador_hash = hashlib.sha256(f"{cfg.salt}{morador_id}".encode("utf-8")).hexdigest()
        if morador_hash in vistos:
            ctx.descartes["cadastro_duplicado"] += 1
            continue
        vistos.add(morador_hash)
        por_setor[setor].append({"hash": morador_hash, "canal": r.get("canal_preferido") or "sms"})
    return por_setor


def _horas_validas(hourly: dict, ctx: Contexto, fonte: str) -> dict[datetime, float]:
    horas: dict[datetime, float] = {}
    for texto, valor in zip(hourly.get("time", []), hourly.get("precipitation", [])):
        try:
            hora, mm = datetime.fromisoformat(texto), float(valor if valor is not None else 0.0)
        except (TypeError, ValueError):
            ctx.descartes[f"{fonte}_hora_invalida"] += 1
            continue
        if not 0 <= mm <= CHUVA_MAX_MM_H:
            ctx.descartes[f"{fonte}_chuva_fora_do_limite"] += 1
            continue
        horas[hora] = mm
    return horas


def _mais_recentes(cfg, fonte: str, agora: datetime, setores: set[str], ctx: Contexto) -> dict[str, dict]:
    """Junta os arquivos: para cada setor e hora, vale a coleta mais recente (como na Prata)."""
    colecao: dict[str, dict[datetime, tuple[str, float]]] = {s: {} for s in setores}
    for arquivo in _arquivos_recentes(_pastas(cfg, fonte), fonte, agora, cfg.dias_arquivos):
        for r in ler_jsonl(arquivo, fonte, cfg, ctx):
            setor = r.get("setor_id")
            if setor not in setores or not isinstance(r.get("hourly"), dict):
                ctx.descartes[f"{fonte}_registro_invalido"] += 1
                continue
            coletado = r.get("coletado_em", "")
            for hora, valor in _horas_validas(r["hourly"], ctx, fonte).items():
                atual = colecao[setor].get(hora)
                if atual is None or coletado >= atual[0]:
                    colecao[setor][hora] = (coletado, valor)
    return {s: {h: v for h, (_, v) in horas.items()} for s, horas in colecao.items()}


def chuva_de_arquivos(cfg, agora: datetime, setores: set[str], ctx: Contexto) -> dict[str, SerieChuva]:
    """Modo replay: reproduz o que o Airflow coletou, sem chamar a API."""
    chuva = _mais_recentes(cfg, "chuva", agora, setores, ctx)
    previsao = _mais_recentes(cfg, "previsao", agora, setores, ctx)
    return {s: SerieChuva(chuva=chuva[s], previsao=previsao[s], origem="arquivos_airflow") for s in setores}


class OpenMeteo:
    """Chuva e previsão ao vivo, com novas tentativas, cache e flag de dado desatualizado."""

    def __init__(self, cfg, espera=time.sleep):
        self.cfg = cfg
        self.espera = espera
        self.cache_arquivo = cfg.estado_dir / "cache_open_meteo.json"

    def _baixar(self, setor: dict) -> dict:
        consulta = urllib.parse.urlencode({
            "latitude": setor["lat"], "longitude": setor["lon"], "timezone": FUSO,
            "hourly": "precipitation", "past_days": 3, "forecast_days": 2,
        })
        url = f"{self.cfg.open_meteo_url}?{consulta}"
        pedido = urllib.request.Request(url, headers={"User-Agent": "encosta-viva-rpa/1.0"})
        with urllib.request.urlopen(pedido, timeout=15) as resposta:
            dados = json.loads(resposta.read())
        if not isinstance(dados.get("hourly", {}).get("time"), list):
            raise ValueError("resposta sem a lista de horas")
        return dados["hourly"]

    def _com_tentativas(self, setor: dict, auditoria) -> dict:
        for tentativa in range(1, TENTATIVAS_API + 1):
            try:
                return self._baixar(setor)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as erro:
                auditoria.evento("api_tentativa_falhou", fonte="open_meteo", setor_id=setor["setor_id"],
                                 tentativa=tentativa, erro=type(erro).__name__)
                if tentativa == TENTATIVAS_API:
                    raise
                self.espera(2 ** tentativa)  # Backoff exponencial: 2 s e 4 s.
        raise AssertionError("inalcançável")

    def _ler_cache(self) -> dict:
        try:
            return json.loads(self.cache_arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def obter(self, setores: list[dict], agora: datetime, ctx: Contexto, auditoria) -> dict[str, SerieChuva]:
        cache = self._ler_cache()
        series: dict[str, SerieChuva] = {}
        fora_do_ar = False
        for setor in setores:
            setor_id = setor["setor_id"]
            hourly = None
            if not fora_do_ar:
                try:
                    hourly = self._com_tentativas(setor, auditoria)
                    cache[setor_id] = {"hourly": hourly, "coletado_em": agora.isoformat(timespec="minutes")}
                except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                    # Não insiste setor a setor: a API caiu e o ciclo não pode atrasar.
                    fora_do_ar = True
            if hourly is not None:
                horas = _horas_validas(hourly, ctx, "open_meteo")
                series[setor_id] = SerieChuva(chuva=horas, previsao=horas, coletado_em=agora.isoformat(timespec="minutes"))
            elif setor_id in cache:
                horas = _horas_validas(cache[setor_id]["hourly"], ctx, "open_meteo")
                series[setor_id] = SerieChuva(chuva=horas, previsao=horas, origem="cache", desatualizado=True,
                                              coletado_em=cache[setor_id]["coletado_em"])
            else:
                series[setor_id] = SerieChuva(origem="camada_ouro", desatualizado=True, ouro=setor)
        if fora_do_ar:
            ctx.problema("open_meteo", "API fora do ar após 3 tentativas; usando o último valor com flag de dado desatualizado")
        if cache:
            temporario = self.cache_arquivo.with_suffix(".tmp")
            temporario.write_text(json.dumps(cache), encoding="utf-8")
            temporario.replace(self.cache_arquivo)
        return series
