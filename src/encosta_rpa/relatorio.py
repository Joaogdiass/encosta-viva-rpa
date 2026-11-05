"""Relatório diário em PDF para o coordenador da Defesa Civil. Só dados agregados por setor."""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

from encosta_rpa.config import Config
from encosta_rpa.motor import NIVEIS

ROTULO_CHAMADO = {"vistoria": "Vistoria", "manutencao_sensor": "Manutenção de sensor", "bateria_baixa": "Bateria baixa"}


def caminho_relatorio(cfg: Config, dia: date) -> Path:
    return cfg.saida_dir / "relatorios" / f"relatorio_{dia}.pdf"


class _Pdf(FPDF):
    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", size=8)
        self.set_text_color(90, 90, 90)
        self.cell(0, 6, f"Encosta Viva. O nível é uma sugestão: quem decide remover moradores é a Defesa Civil. "
                        f"Página {self.page_no()}", align="C")


def _titulo(pdf: FPDF, texto: str) -> None:
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(31, 36, 33)
    pdf.cell(0, 8, texto, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)


def _tabela(pdf: FPDF, colunas: tuple, linhas: list[tuple], larguras: tuple) -> None:
    pdf.set_font("Helvetica", size=8.5)
    with pdf.table(col_widths=larguras, text_align="LEFT", line_height=5.5,
                   headings_style=FontFace(emphasis="BOLD", fill_color=(235, 232, 224))) as tabela:
        cabecalho = tabela.row()
        for coluna in colunas:
            cabecalho.cell(coluna)
        for linha in linhas:
            nova = tabela.row()
            for celula in linha:
                nova.cell(str(celula))


def gerar_relatorio(cfg: Config, db: sqlite3.Connection, dia: date) -> Path:
    prefixo = f"{dia}%"
    execucoes = db.execute("SELECT status, COUNT(*) AS n FROM execucoes WHERE inicio LIKE ? GROUP BY status",
                           (prefixo,)).fetchall()
    alertas = db.execute(
        """SELECT a.*, (SELECT COUNT(*) FROM envios e WHERE e.alerta_id = a.id AND e.status = 'enviado') AS avisados,
                  (SELECT COUNT(*) FROM envios e WHERE e.alerta_id = a.id) AS total
           FROM alertas a WHERE a.criado_em LIKE ? ORDER BY a.criado_em""", (prefixo,)).fetchall()
    envios = db.execute(
        """SELECT e.canal, e.status, COUNT(*) AS n FROM envios e JOIN alertas a ON a.id = e.alerta_id
           WHERE a.criado_em LIKE ? GROUP BY e.canal, e.status ORDER BY e.canal""", (prefixo,)).fetchall()
    chamados = db.execute("SELECT * FROM chamados WHERE aberto_em LIKE ? ORDER BY aberto_em", (prefixo,)).fetchall()
    abertos = db.execute("SELECT COUNT(*) FROM chamados WHERE status = 'aberto'").fetchone()[0]
    estado = db.execute("SELECT * FROM estado_setor ORDER BY nivel_ordem DESC, setor_id").fetchall()
    quarentena = db.execute("SELECT * FROM quarentena WHERE registrado_em LIKE ?", (prefixo,)).fetchall()

    pdf = _Pdf(format="A4")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Encosta Viva: relatório diário", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(89, 97, 92)
    pdf.cell(0, 6, f"Dia {dia:%d/%m/%Y}. Gerado automaticamente pelo robô de alertas.", new_x="LMARGIN", new_y="NEXT")

    total_exec = sum(e["n"] for e in execucoes)
    com_falha = sum(e["n"] for e in execucoes if e["status"] != "concluido")
    so_alertas = [a for a in alertas if a["tipo"] == "alerta"]
    _titulo(pdf, "Resumo do dia")
    pdf.multi_cell(0, 5.5, (
        f"Execuções do robô: {total_exec} ({com_falha} com alguma falha registrada). "
        f"Alertas emitidos: {len(so_alertas)}. Encerramentos: {len(alertas) - len(so_alertas)}. "
        f"Chamados abertos no dia: {len(chamados)}. Chamados em aberto agora: {abertos}. "
        f"Arquivos em quarentena: {len(quarentena)}."
    ), new_x="LMARGIN", new_y="NEXT")

    _titulo(pdf, "Situação atual dos setores")
    _tabela(pdf, ("Setor", "Nível", "Chuva 72 h", "Sensor", "Por quê"),
            [(e["setor_id"], NIVEIS[e["nivel_ordem"]], f"{e['chuva_72h']:.1f} mm", e["sensor_status"],
              e["fatores"] or "sem fatores de atenção") for e in estado],
            (12, 22, 18, 14, 74))

    _titulo(pdf, "Alertas do dia")
    if alertas:
        _tabela(pdf, ("Hora", "Setor", "Tipo", "Nível", "Moradores avisados", "Canais", "Status"),
                [(a["criado_em"][11:16], a["setor_id"], a["tipo"], a["nivel"], f"{a['avisados']} de {a['total']}",
                  a["canal"] or "-", a["status"]) for a in alertas],
                (11, 11, 20, 22, 18, 36, 16))
    else:
        pdf.cell(0, 6, "Nenhum alerta emitido neste dia.", new_x="LMARGIN", new_y="NEXT")

    _titulo(pdf, "Envios por canal")
    if envios:
        _tabela(pdf, ("Canal", "Status", "Quantidade"),
                [(e["canal"] or "sem canal", e["status"], e["n"]) for e in envios], (50, 50, 40))
        simulados = db.execute(
            """SELECT COUNT(*) FROM envios e JOIN alertas a ON a.id = e.alerta_id
               WHERE a.criado_em LIKE ? AND e.simulado = 1""", (prefixo,)).fetchone()[0]
        if simulados:
            pdf.ln(2)
            pdf.multi_cell(0, 5, f"{simulados} envios foram simulados: o cadastro é fictício e a mensagem não saiu para a rede.",
                           new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 6, "Nenhum envio neste dia.", new_x="LMARGIN", new_y="NEXT")

    _titulo(pdf, "Chamados abertos no dia")
    if chamados:
        _tabela(pdf, ("Hora", "Tipo", "Setor", "Prioridade", "Status", "Descrição"),
                [(c["aberto_em"][11:16], ROTULO_CHAMADO.get(c["tipo"], c["tipo"]), c["setor_id"], c["prioridade"],
                  c["status"], c["descricao"]) for c in chamados],
                (11, 26, 11, 15, 15, 62))
    else:
        pdf.cell(0, 6, "Nenhum chamado aberto neste dia.", new_x="LMARGIN", new_y="NEXT")

    destino = caminho_relatorio(cfg, dia)
    destino.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(destino))
    return destino
