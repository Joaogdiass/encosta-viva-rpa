"""Gera docs/processo_to_be.bpmn (BPMN 2.0 com diagrama), que abre no bpmn.io e no Camunda Modeler."""
from pathlib import Path
from xml.sax.saxutils import quoteattr

# id: (tipo, rótulo, x, y, largura, altura, pai)
EVENTO, GATE = (36, 36), (50, 50)
TAREFA = (120, 72)
Y1, Y3 = 120, 800  # Centro das linhas de cima e de baixo.

nos = {}
fluxos = []
ROTULO_A_ESQUERDA = {"g_igual", "g_obs"}
ROTULO_ABAIXO = {"g_canais"}


def no(id_, tipo, rotulo, cx, cy, pai="Robo", tam=None, marca=None):
    tam = tam or (EVENTO if "Event" in tipo else GATE if "Gateway" in tipo else TAREFA)
    nos[id_] = dict(tipo=tipo, rotulo=rotulo, cx=cx, cy=cy, l=tam[0], a=tam[1], pai=pai, marca=marca)


def fluxo(a, b, rotulo="", caminho=None):
    fluxos.append(dict(id=f"f{len(fluxos) + 1}", a=a, b=b, rotulo=rotulo, caminho=caminho))


# ---- Linha de cima: preparar
no("inicio", "startEvent", "A cada 15 min", 90, Y1, marca="timer")
no("trava", "task", "Obter trava e abrir execução", 200, Y1)
no("ler", "task", "Ler Ouro, sensores, relatos e cadastro", 350, Y1)
no("g_arq", "exclusiveGateway", "Arquivos válidos?", 480, Y1)
no("quarentena", "task", "Copiar para quarentena e avisar operador", 480, Y1 + 100)
no("validar", "task", "Aplicar regras de qualidade e contar descartes", 620, Y1)
no("hash", "task", "Trocar dados do morador por hash", 770, Y1)
no("api", "task", "Consultar Open-Meteo (3 tentativas com backoff)", 920, Y1)
no("g_api", "exclusiveGateway", "API respondeu?", 1050, Y1)
no("cache", "task", "Usar último valor com flag e avisar operador", 1050, Y1 + 100)
no("g_junta", "exclusiveGateway", "", 1190, Y1)

fluxo("inicio", "trava")
fluxo("trava", "ler")
fluxo("ler", "g_arq")
fluxo("g_arq", "validar", "sim")
fluxo("g_arq", "quarentena", "não")
fluxo("quarentena", "validar", caminho=[(540, Y1 + 100), (620, Y1 + 100), (620, Y1 + 36)])
fluxo("validar", "hash")
fluxo("hash", "api")
fluxo("api", "g_api")
fluxo("g_api", "g_junta", "sim")
fluxo("g_api", "cache", "não")
fluxo("cache", "g_junta", caminho=[(1110, Y1 + 100), (1190, Y1 + 100), (1190, Y1 + 25)])

# ---- Subprocesso: para cada setor
SP = "Setores"
Y_A, Y_B, Y_C, Y_D = 370, 470, 570, 660
no("s_inicio", "startEvent", "", 110, Y_A, pai=SP)
no("s_sensor", "task", "Avaliar última leitura do sensor", 210, Y_A, pai=SP)
no("g_off", "exclusiveGateway", "Sem leitura há mais de 30 min?", 340, Y_A, pai=SP)
no("manut", "task", "Abrir chamado de manutenção e usar só chuva", 340, Y_B, pai=SP)
no("motor", "businessRuleTask", "Calcular nível (motor de risco)", 480, Y_A, pai=SP)
no("g_inc", "exclusiveGateway", "Dado incompleto e nível menor?", 610, Y_A, pai=SP)
no("manter", "task", "Manter o nível anterior", 610, Y_B, pai=SP)
no("g_cmp", "exclusiveGateway", "Nível subiu?", 760, Y_A, pai=SP)
no("g_igual", "exclusiveGateway", "Nível igual?", 760, Y_C, pai=SP)

no("g_chave", "exclusiveGateway", "Chave de idempotência já usada?", 880, Y_A, pai=SP)
no("descartar", "task", "Descartar e contar duplicado", 880, Y_A - 0 + 90, pai=SP)
no("gravar", "task", "Gravar alerta e fila de envios", 1020, Y_A, pai=SP)
no("g_alto", "exclusiveGateway", "Nível Alerta ou maior?", 1150, Y_A, pai=SP)
no("vistoria", "task", "Abrir chamado de vistoria", 1150, Y_B, pai=SP)

no("igual", "task", "Não reenviar (anti-spam)", 880, Y_C, pai=SP)
no("g_obs", "exclusiveGateway", "Caiu para Observação?", 760, Y_D, pai=SP)
no("encerrar", "task", "Gravar mensagem de encerramento", 1020, Y_D, pai=SP)
no("g_fim", "exclusiveGateway", "", 1300, Y_A, pai=SP)
no("estado", "task", "Atualizar estado do setor", 1420, Y_A, pai=SP)
no("s_fim", "endEvent", "", 1530, Y_A, pai=SP)

fluxo("s_inicio", "s_sensor")
fluxo("s_sensor", "g_off")
fluxo("g_off", "motor", "não")
fluxo("g_off", "manut", "sim")
fluxo("manut", "motor", caminho=[(400, Y_B), (480, Y_B), (480, Y_A + 36)])
fluxo("motor", "g_inc")
fluxo("g_inc", "g_cmp", "não")
fluxo("g_inc", "manter", "sim")
fluxo("manter", "g_cmp", caminho=[(670, Y_B), (700, Y_B), (700, Y_A), (735, Y_A)])
fluxo("g_cmp", "g_chave", "sim")
fluxo("g_cmp", "g_igual", "não")
fluxo("g_igual", "igual", "sim")
fluxo("g_igual", "g_obs", "não: caiu")
fluxo("g_chave", "gravar", "não")
fluxo("g_chave", "descartar", "sim")
fluxo("gravar", "g_alto")
fluxo("g_alto", "g_fim", "não")
fluxo("g_alto", "vistoria", "sim")
fluxo("vistoria", "g_fim", caminho=[(1210, Y_B), (1300, Y_B), (1300, Y_A + 25)])
fluxo("descartar", "g_fim", caminho=[(940, Y_A + 90), (1000, Y_A + 90), (1000, Y_C - 30), (1300, Y_C - 30), (1300, Y_A + 25)])
fluxo("igual", "g_fim", caminho=[(940, Y_C), (1300, Y_C), (1300, Y_A + 25)])
fluxo("g_obs", "encerrar", "sim")
fluxo("g_obs", "g_fim", "não", caminho=[(760, Y_D + 25), (760, Y_D + 45), (1300, Y_D + 45), (1300, Y_A + 25)])
fluxo("encerrar", "g_fim", caminho=[(1080, Y_D), (1300, Y_D), (1300, Y_A + 25)])
fluxo("g_fim", "estado")
fluxo("estado", "s_fim")

# ---- Linha de baixo: agir e entregar
no("Setores", "subProcess", "Para cada setor (repetição)", 830, 500, tam=(1560, 440), marca="loop")
no("enviar", "task", "Enviar a cada morador, com limite por minuto", 170, Y3, marca="loop")
no("g_envio", "exclusiveGateway", "Canal aceitou?", 310, Y3)
no("trocar", "task", "Após 3 falhas, trocar de canal", 310, Y3 + 95)
no("g_canais", "exclusiveGateway", "Algum canal aceitou?", 450, Y3 + 95)
no("fila", "task", "Manter na fila do próximo ciclo; após 3 ciclos, avisar operador", 590, Y3 + 95)
no("concluir", "task", "Atualizar status na tabela alertas", 590, Y3)
no("exportar", "task", "Gravar alertas.json para o MVP (escrita atômica)", 760, Y3)
no("g_dia", "exclusiveGateway", "Primeira execução do dia?", 1060, Y3)
no("relatorio", "task", "Gerar relatório diário em PDF", 1060, Y3 + 95)
no("soltar", "task", "Soltar a trava", 1250, Y3)
no("log", "task", "Gravar resumo da execução no log de auditoria", 1400, Y3)
no("fim", "endEvent", "Fim do ciclo", 1520, Y3)

fluxo("g_junta", "Setores", caminho=[(1215, Y1), (1320, Y1), (1320, 268), (830, 268), (830, 280)])
fluxo("Setores", "enviar", caminho=[(170, 720), (170, Y3 - 36)])
fluxo("enviar", "g_envio")
fluxo("g_envio", "concluir", "sim")
fluxo("g_envio", "trocar", "não")
fluxo("trocar", "g_canais")
fluxo("g_canais", "fila", "não")
fluxo("g_canais", "concluir", "sim", caminho=[(450, Y3 + 70), (450, Y3 + 20), (530, Y3 + 20)])
fluxo("fila", "concluir")
fluxo("concluir", "exportar")
fluxo("exportar", "g_dia")
fluxo("g_dia", "soltar", "não")
fluxo("g_dia", "relatorio", "sim")
fluxo("relatorio", "soltar", caminho=[(1120, Y3 + 95), (1250, Y3 + 95), (1250, Y3 + 36)])
fluxo("soltar", "log")
fluxo("log", "fim")

# ---- Participantes externos (pools recolhidas)
EXTERNOS = {
    "P_moradores": ("Moradores do setor", 30, 500),
    "P_mvp": ("Tela do MVP (Dados)", 560, 450),
    "P_defesa": ("Defesa Civil: vistoria, relatório e decisão de remover moradores", 1040, 590),
}
Y_EXTERNOS = 960
MENSAGENS = [
    ("m1", "enviar", "P_moradores", "alerta", [(170, Y3 + 36), (170, Y_EXTERNOS)]),
    ("m2", "vistoria", "P_defesa", "chamado", [(1150, Y_B + 36), (1150, 690), (1570, 690), (1570, Y_EXTERNOS)]),
    ("m3", "relatorio", "P_defesa", "PDF", [(1060, Y3 + 131), (1060, Y_EXTERNOS)]),
    ("m4", "exportar", "P_mvp", "alertas.json", [(760, Y3 + 36), (760, Y_EXTERNOS)]),
]


def entradas_saidas(id_):
    entradas = "".join(f"<bpmn:incoming>{f['id']}</bpmn:incoming>" for f in fluxos if f["b"] == id_)
    saidas = "".join(f"<bpmn:outgoing>{f['id']}</bpmn:outgoing>" for f in fluxos if f["a"] == id_)
    return entradas + saidas


def xml_no(id_):
    n = nos[id_]
    corpo = entradas_saidas(id_)
    if n["marca"] == "timer":
        corpo += '<bpmn:timerEventDefinition><bpmn:timeCycle xsi:type="bpmn:tFormalExpression">R/PT15M</bpmn:timeCycle></bpmn:timerEventDefinition>'
    if n["marca"] == "loop":
        corpo += '<bpmn:multiInstanceLoopCharacteristics isSequential="true" />'
    if n["tipo"] == "subProcess":
        corpo += "".join(xml_no(i) for i, x in nos.items() if x["pai"] == id_)
        corpo += "".join(xml_fluxo(f) for f in fluxos if nos[f["a"]]["pai"] == id_)
    return f'<bpmn:{n["tipo"]} id="{id_}" name={quoteattr(n["rotulo"])}>{corpo}</bpmn:{n["tipo"]}>'


def xml_fluxo(f):
    return f'<bpmn:sequenceFlow id="{f["id"]}" name={quoteattr(f["rotulo"])} sourceRef="{f["a"]}" targetRef="{f["b"]}" />'


def borda(n, lado):
    return {
        "dir": (n["cx"] + n["l"] / 2, n["cy"]), "esq": (n["cx"] - n["l"] / 2, n["cy"]),
        "baixo": (n["cx"], n["cy"] + n["a"] / 2), "cima": (n["cx"], n["cy"] - n["a"] / 2),
    }[lado]


def waypoints(f):
    a, b = nos[f["a"]], nos[f["b"]]
    if f["caminho"]:
        x, y = f["caminho"][0]
        na_borda = abs(x - a["cx"]) <= a["l"] / 2 and abs(y - a["cy"]) <= a["a"] / 2
        return f["caminho"] if na_borda else [borda_inicio(a, f["caminho"][0])] + f["caminho"]
    if abs(a["cy"] - b["cy"]) < 2:
        return [borda(a, "dir"), borda(b, "esq")]
    if abs(a["cx"] - b["cx"]) < 2:
        return [borda(a, "baixo"), borda(b, "cima")] if a["cy"] < b["cy"] else [borda(a, "cima"), borda(b, "baixo")]
    return [borda(a, "dir"), (b["cx"], a["cy"]), borda(b, "cima")]


def borda_inicio(n, proximo):
    """Sai do nó pelo lado voltado para o primeiro ponto do caminho."""
    dx, dy = proximo[0] - n["cx"], proximo[1] - n["cy"]
    if abs(dx) >= abs(dy):
        return borda(n, "dir" if dx > 0 else "esq")
    return borda(n, "baixo" if dy > 0 else "cima")


def di_no(id_):
    n = nos[id_]
    x, y = n["cx"] - n["l"] / 2, n["cy"] - n["a"] / 2
    extra = ' isExpanded="true"' if n["tipo"] == "subProcess" else ""
    marcador = ' isMarkerVisible="true"' if "Gateway" in n["tipo"] else ""
    rotulo = ""
    if n["tipo"] in ("startEvent", "endEvent", "exclusiveGateway") and n["rotulo"]:
        ly = y - 34 if "Gateway" in n["tipo"] else y + n["a"] + 2
        lx = n["cx"] - 55
        if id_ in ROTULO_A_ESQUERDA:
            lx, ly = n["cx"] - 140, n["cy"] - 15
        if id_ in ROTULO_ABAIXO:
            ly = y + n["a"] + 2
        rotulo = f'<bpmndi:BPMNLabel><dc:Bounds x="{lx}" y="{ly}" width="110" height="30" /></bpmndi:BPMNLabel>'
    if n["tipo"] == "subProcess":
        rotulo = f'<bpmndi:BPMNLabel><dc:Bounds x="{x + 12}" y="{y + 8}" width="300" height="16" /></bpmndi:BPMNLabel>'
    return (f'<bpmndi:BPMNShape id="{id_}_di" bpmnElement="{id_}"{extra}{marcador}>'
            f'<dc:Bounds x="{x}" y="{y}" width="{n["l"]}" height="{n["a"]}" />{rotulo}</bpmndi:BPMNShape>')


def di_fluxo(id_, pontos, rotulo=""):
    wps = "".join(f'<di:waypoint x="{x}" y="{y}" />' for x, y in pontos)
    lab = ""
    if rotulo:
        (x1, y1), (x2, y2) = pontos[0], pontos[1]
        lab = (f'<bpmndi:BPMNLabel><dc:Bounds x="{(x1 + x2) / 2 - 30 + (6 if x1 == x2 else 0) + (30 if x1 == x2 else 0)}" '
               f'y="{(y1 + y2) / 2 - 18 if y1 == y2 else (y1 + y2) / 2 - 8}" width="60" height="14" /></bpmndi:BPMNLabel>')
    return f'<bpmndi:BPMNEdge id="{id_}_di" bpmnElement="{id_}">{wps}{lab}</bpmndi:BPMNEdge>'


def gerar() -> str:
    raiz = "".join(xml_no(i) for i, n in nos.items() if n["pai"] == "Robo")
    raiz += "".join(xml_fluxo(f) for f in fluxos if nos[f["a"]]["pai"] == "Robo")
    participantes = '<bpmn:participant id="P_robo" name="Robô de alertas Encosta Viva (software)" processRef="Robo" />'
    participantes += "".join(f'<bpmn:participant id="{i}" name={quoteattr(r)} />' for i, (r, _, _) in EXTERNOS.items())
    participantes += "".join(
        f'<bpmn:messageFlow id="{i}" name={quoteattr(r)} sourceRef="{a}" targetRef="{b}" />' for i, a, b, r, _ in MENSAGENS)

    formas = '<bpmndi:BPMNShape id="P_robo_di" bpmnElement="P_robo" isHorizontal="true"><dc:Bounds x="30" y="30" width="1600" height="910" /></bpmndi:BPMNShape>'
    formas += "".join(
        f'<bpmndi:BPMNShape id="{i}_di" bpmnElement="{i}" isHorizontal="true"><dc:Bounds x="{x}" y="{Y_EXTERNOS}" width="{l}" height="50" /></bpmndi:BPMNShape>'
        for i, (_, x, l) in EXTERNOS.items())
    formas += di_no("Setores") + "".join(di_no(i) for i in nos if i != "Setores")
    arestas = "".join(di_fluxo(f["id"], waypoints(f), f["rotulo"]) for f in fluxos)
    for i, a, _, r, caminho in MENSAGENS:
        arestas += di_fluxo(i, caminho, r)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" id="Definicoes" targetNamespace="https://encostaviva.example/rpa">
<bpmn:collaboration id="Colaboracao">{participantes}</bpmn:collaboration>
<bpmn:process id="Robo" name="Robô de alertas" isExecutable="false">{raiz}</bpmn:process>
<bpmndi:BPMNDiagram id="Diagrama"><bpmndi:BPMNPlane id="Plano" bpmnElement="Colaboracao">{formas}{arestas}</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>
</bpmn:definitions>
"""


if __name__ == "__main__":
    destino = Path(__file__).with_name("processo_to_be.bpmn")
    destino.write_text(gerar(), encoding="utf-8")
    print(destino)
