"""Banco do robô (SQLite). A tabela `alertas` segue o contrato do documento de arquitetura."""
from __future__ import annotations

import sqlite3
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS execucoes (
    id TEXT PRIMARY KEY, inicio TEXT, fim TEXT, modo TEXT, status TEXT, resumo TEXT
);
CREATE TABLE IF NOT EXISTS estado_setor (
    setor_id TEXT PRIMARY KEY, nivel_ordem INTEGER NOT NULL, episodio INTEGER NOT NULL DEFAULT 1,
    fatores TEXT, atualizado_em TEXT, dado_desatualizado INTEGER DEFAULT 0, nivel_mantido INTEGER DEFAULT 0,
    chuva_1h REAL, chuva_24h REAL, chuva_72h REAL, previsao_6h REAL, umidade_solo_media REAL,
    sensor_status TEXT, minutos_sem_leitura INTEGER
);
CREATE TABLE IF NOT EXISTS alertas (
    id TEXT PRIMARY KEY, chave TEXT NOT NULL UNIQUE, setor_id TEXT NOT NULL, tipo TEXT NOT NULL,
    nivel_ordem INTEGER NOT NULL, nivel TEXT NOT NULL, nivel_anterior INTEGER, fatores TEXT, mensagem TEXT,
    criado_em TEXT NOT NULL, enviado_em TEXT, canal TEXT, status TEXT NOT NULL, execucao_id TEXT,
    dado_desatualizado INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS envios (
    alerta_id TEXT NOT NULL, morador_hash TEXT NOT NULL, canal_preferido TEXT NOT NULL, canal TEXT,
    status TEXT NOT NULL, tentativas INTEGER NOT NULL DEFAULT 0, ciclos INTEGER NOT NULL DEFAULT 0,
    simulado INTEGER, erro TEXT, enviado_em TEXT,
    PRIMARY KEY (alerta_id, morador_hash)
);
CREATE TABLE IF NOT EXISTS chamados (
    id TEXT PRIMARY KEY, tipo TEXT NOT NULL, setor_id TEXT NOT NULL, prioridade TEXT NOT NULL,
    descricao TEXT, status TEXT NOT NULL, aberto_em TEXT NOT NULL, fechado_em TEXT, execucao_id TEXT
);
CREATE TABLE IF NOT EXISTS incidentes (
    chave TEXT PRIMARY KEY, descricao TEXT, aberto_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quarentena (
    sha256 TEXT PRIMARY KEY, arquivo TEXT, motivo TEXT, registrado_em TEXT
);
CREATE INDEX IF NOT EXISTS idx_envios_status ON envios (status);
CREATE INDEX IF NOT EXISTS idx_alertas_criado ON alertas (criado_em);
"""


def conectar(caminho: Path) -> sqlite3.Connection:
    conexao = sqlite3.connect(caminho)
    conexao.row_factory = sqlite3.Row
    conexao.executescript(ESQUEMA)
    return conexao
