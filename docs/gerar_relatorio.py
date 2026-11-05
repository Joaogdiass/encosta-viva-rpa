"""Gera docs/relatorio_tecnico.pdf na ordem pedida pelo enunciado, com as evidências reais do repositório.

Uso: REPO_URL=... VIDEO_URL=... py docs/gerar_relatorio.py
"""
import html
import os
import subprocess
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NAVEGADOR = os.environ.get("NAVEGADOR", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
PENDENTE = '<mark>A PREENCHER antes da entrega</mark>'


def link(variavel: str) -> str:
    url = os.environ.get(variavel, "")
    return f'<a href="{html.escape(url)}">{html.escape(url)}</a>' if url else PENDENTE


def evidencia(nome: str, primeira: int = 0, ultima: int | None = None) -> str:
    linhas = (RAIZ / "tests" / "evidencias" / nome).read_text(encoding="utf-8").splitlines()
    return "<pre>" + html.escape("\n".join(l[:150] for l in linhas[primeira:ultima])) + "</pre>"


def imagem(arquivo: str, legenda: str, largura: str = "100%") -> str:
    uri = (RAIZ / "assets" / arquivo).as_uri()
    return f'<figure><img src="{uri}" style="width:{largura}" alt="{html.escape(legenda)}"><figcaption>{html.escape(legenda)}</figcaption></figure>'


def amostra_log() -> str:
    linhas = (RAIZ / "logs" / "amostras" / "auditoria_decisao_alerta_maximo.jsonl").read_text(encoding="utf-8").splitlines()
    escolhidas = [l for l in linhas if '"tipo": "alerta_criado"' in l or '"tipo": "ciclo_concluido"' in l]
    return "<pre>" + html.escape("\n".join(escolhidas)) + "</pre>"


CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font: 10.5pt/1.45 "Segoe UI", Arial, sans-serif; color: #1f2421; }
h1 { font-size: 22pt; margin: 0 0 4px; } h2 { font-size: 13.5pt; margin: 20px 0 6px; border-bottom: 1px solid #d8d5cc; padding-bottom: 3px; break-after: avoid; }
h3 { font-size: 11pt; margin: 12px 0 4px; break-after: avoid; } p { margin: 5px 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9.5pt; break-inside: auto; }
th, td { border: 1px solid #c9c6bd; padding: 4px 6px; text-align: left; vertical-align: top; } th { background: #ebe8e0; }
tr { break-inside: avoid; }
pre { background: #f3f1ec; border: 1px solid #d8d5cc; padding: 7px; font: 7.6pt/1.35 Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
figure { margin: 10px 0; break-inside: avoid; } img { border: 1px solid #d8d5cc; } figcaption { font-size: 9pt; color: #59615c; margin-top: 3px; }
code { font-family: Consolas, monospace; font-size: 9.5pt; } mark { background: #ffe58a; padding: 0 3px; }
.sub { color: #59615c; }
"""

CORPO = f"""
<h1>Encosta Viva: robô de alertas</h1>
<p class="sub">Robotic Process Automation · Global Solution 2026.2 · CitizenTech · Engenharia de Software, 4º ano · Professores Bruno Diniz e Cibele Ribeiro</p>

<h2>1. Integrantes</h2>
<table><tr><th>Nome completo</th><th>RM</th></tr>
<tr><td>Ricardo Mattos</td><td>95906</td></tr><tr><td>João Gabriel Dias</td><td>99092</td></tr><tr><td>Julio Zampieri</td><td>98772</td></tr></table>

<h2>2. A CitizenTech e o problema resolvido</h2>
<p>A <strong>Encosta Viva</strong> avisa moradores de encostas sobre o risco de deslizamento por setor, e não por cidade. Hoje, em dia de chuva, o agente da Defesa Civil consulta sites de chuva, cruza com uma planilha de setores, decide no olho quais estão críticos e liga para as lideranças. Com poucas pessoas para muitos setores, esse processo é lento e varia de um agente para outro. Sensor quebrado passa despercebido, e vistoria fica anotada em papel.</p>
<table><tr><th>Hoje (manual)</th><th>Com o robô</th></tr>
<tr><td>Agente abre sites de chuva e planilha de setores</td><td>O robô lê a camada Ouro, o Open-Meteo, os sensores e os relatos</td></tr>
<tr><td>Decide no olho quais setores estão críticos</td><td>As regras do motor de risco valem igualmente para todos os setores</td></tr>
<tr><td>Liga ou manda mensagem para lideranças</td><td>Envia alerta a cada morador do setor, pelo canal preferido</td></tr>
<tr><td>Anota vistorias em papel ou planilha</td><td>Abre chamado de vistoria e gera relatório diário em PDF</td></tr>
<tr><td>Ninguém percebe sensor quebrado</td><td>Detecta sensor sem leitura e abre chamado de manutenção</td></tr></table>

<h2>3. Objetivo da automação e benefício para o cidadão</h2>
<p>Executar esse processo a cada 15 minutos, sem ninguém clicar. O morador recebe uma mensagem em linguagem simples, com o nível, o motivo, o que fazer e os telefones de emergência, sem receber a mesma mensagem repetida. O agente passa a cuidar do que exige uma pessoa: vistoriar e decidir sobre a remoção de moradores.</p>

<h2>4. Descrição do processo e desenho do fluxo</h2>
<p><strong>Início:</strong> gatilho a cada 15 minutos. <strong>Entradas:</strong> camada Ouro (<code>risco_setores.json</code>), Open-Meteo, e os arquivos de sensores, relatos e cadastro da pasta <code>chegada/</code>. <strong>Saídas:</strong> mensagens, tabela <code>alertas</code>, chamados, <code>alertas.json</code>, relatório diário e log de auditoria. O arquivo editável é <code>docs/processo_to_be.bpmn</code>.</p>
{imagem("fluxo_bpmn.png", "Figura 1. Processo TO-BE em BPMN 2.0, validado no bpmn-js.")}

<h2>5. Tecnologias utilizadas e justificativa</h2>
<table><tr><th>Tecnologia</th><th>Uso</th><th>Por quê</th></tr>
<tr><td>Python 3</td><td>Robô completo</td><td>Mesma linguagem do pipeline de Dados, versionável e testável. O robô só precisa de duas bibliotecas externas</td></tr>
<tr><td>SQLite</td><td>Tabelas <code>alertas</code>, <code>envios</code>, <code>chamados</code> e estado</td><td>Guarda o estado entre execuções e tem transações, sem precisar de servidor</td></tr>
<tr><td>Open-Meteo</td><td>Chuva e previsão ao vivo</td><td>API pública, sem chave, já usada no componente de Dados</td></tr>
<tr><td>fpdf2</td><td>Relatório diário</td><td>Gera PDF sem depender de programas instalados</td></tr>
<tr><td>certifi e tzdata</td><td>HTTPS e fuso horário</td><td>O robô funciona igual em qualquer máquina, inclusive em uma instalação limpa do Windows</td></tr>
<tr><td>pytest</td><td>Testes</td><td>Executa os cenários de sucesso, decisão e falha a cada mudança</td></tr>
<tr><td>Telegram Bot API</td><td>Canal real opcional</td><td>Gratuito e simples de usar na demonstração</td></tr></table>

<h2>6. Regras de negócio, decisões e processamento</h2>
<h3>Níveis (mesmas regras da camada Ouro)</h3>
<table><tr><th>Nível</th><th>Condição</th><th>Ação</th></tr>
<tr><td>Observação</td><td>Nenhuma condição abaixo</td><td>Só registra</td></tr>
<tr><td>Atenção</td><td>Chuva em 72 h ≥ 80 mm ou umidade do solo ≥ 80%</td><td>Mensagem preventiva</td></tr>
<tr><td>Alerta</td><td>Atenção + (previsão em 6 h ≥ 30 mm ou chuva em 1 h ≥ 15 mm), ou relato confirmado pela Visão</td><td>Alerta e chamado de vistoria</td></tr>
<tr><td>Alerta máximo</td><td>Variação de inclinação ≥ 2° + umidade ≥ 90% + chuva em 1 h ≥ 20 mm</td><td>Alerta prioritário e chamado urgente</td></tr></table>
<p>Os limiares são ilustrativos e precisam ser calibrados com PPDC, CEMADEN e IPT. Um teste automatizado compara o cálculo do robô com a série publicada pela camada Ouro: os <strong>365 níveis horários são iguais</strong>.</p>
<h3>Decisão</h3>
<table><tr><th>Situação</th><th>Ação</th></tr>
<tr><td>Nível subiu</td><td>Alerta a cada morador; em Alerta ou acima, abre vistoria</td></tr>
<tr><td>Nível igual</td><td>Não reenvia</td></tr>
<tr><td>Caiu, mas não para Observação</td><td>Atualiza o estado, sem mensagem</td></tr>
<tr><td>Caiu para Observação</td><td>Mensagem de encerramento</td></tr>
<tr><td>Dado incompleto e nível calculado menor</td><td>Mantém o nível: dado faltando não encerra alerta</td></tr></table>
<h3>Repetição e lote</h3>
<p>O robô percorre todos os setores e, dentro de cada um, os moradores cadastrados, com limite de envios por minuto. O alerta e a fila de envios são gravados na mesma transação antes do primeiro envio: se o robô cair no meio, o próximo ciclo continua de onde parou.</p>
<h3>Idempotência</h3>
<p>A chave <code>setor + tipo + nível + janela de 6 h + episódio</code> é única no banco. O episódio aumenta a cada encerramento, para um risco novo na mesma janela não ser silenciado.</p>

<h2>7. Tratamento de exceções e recuperação</h2>
<table><tr><th>Falha</th><th>Tratamento</th></tr>
<tr><td>Open-Meteo fora do ar</td><td>3 tentativas com espera de 2 s e 4 s. Depois, usa o último valor com flag de dado desatualizado e avisa o operador. Sem cache, usa os valores da camada Ouro. Quando a API volta, o incidente é fechado</td></tr>
<tr><td>Camada Ouro indisponível</td><td>Usa a última cópia boa. Sem nenhuma cópia, o ciclo termina como <code>falhou</code>, com log e aviso</td></tr>
<tr><td>Sensor sem leitura há mais de 30 min</td><td>Marca como offline, abre chamado de manutenção e usa só a chuva. Fecha o chamado quando as leituras voltam</td></tr>
<tr><td>Arquivo ou JSON inválido</td><td>Copia para <code>quarentena/</code>, registra o motivo e segue. A <code>chegada/</code> não é alterada, porque pertence ao Airflow. Do cadastro, fica só o motivo</td></tr>
<tr><td>Falha no envio</td><td>3 tentativas e troca de canal (Telegram ou WhatsApp → SMS → e-mail). Se todos falharem, o envio fica na fila; após 3 ciclos, o operador é avisado</td></tr>
<tr><td>Dados duplicados ou inconsistentes</td><td>Descartados e contados por motivo: duplicata, umidade fora de 0 a 100%, chuva negativa, horário no futuro e setor desconhecido</td></tr>
<tr><td>Erro em um setor</td><td>É registrado, e os demais setores seguem</td></tr>
<tr><td>Dois ciclos ao mesmo tempo</td><td>Uma trava impede. Trava de processo morto vence em 30 minutos</td></tr>
<tr><td>Falta o salt</td><td>O robô não inicia e explica o motivo</td></tr></table>

<h2>8. Logs e evidências de auditoria</h2>
<p>Cada evento vai para <code>logs/auditoria_AAAA-MM-DD.jsonl</code>, com data e hora, identificador da execução, itens processados, sucessos, falhas e erros. Amostras reais estão em <code>logs/amostras/</code>. Abaixo, o ciclo em que o Jardim Ângela subiu para Alerta máximo:</p>
{amostra_log()}
<p>Todo dia, o robô também gera um relatório para o coordenador da Defesa Civil:</p>
{imagem("relatorio_diario.png", "Figura 2. Relatório diário gerado pelo robô, com os envios por canal e os chamados.", "62%")}

<h2>9. Integração com o MVP</h2>
<p>O robô grava <code>mvp/dados/alertas.json</code> de forma atômica, e a tela do MVP lê esse arquivo. O conteúdo vem da tabela <code>alertas</code> e do estado de cada setor, sem nenhum dado pessoal. Se o arquivo não existir, a tela continua funcionando só com a camada Ouro. Sem conexão, mostra os últimos dados salvos.</p>
<table><tr><th>Campo</th><th>Conteúdo</th></tr>
<tr><td><code>alertas[]</code></td><td>id, setor, nível, tipo, mensagem, enviado_em, canal, status e moradores avisados</td></tr>
<tr><td><code>setores[]</code></td><td>Nível atual, fatores, chuva, umidade, status do sensor, vistoria aberta e flags de dado</td></tr>
<tr><td><code>resumo</code></td><td>Setores em alerta, sensores offline e chamados abertos</td></tr></table>
{imagem("mvp_alertas.png", "Figura 3. Tela do MVP lendo alertas.json depois do replay do evento simulado de 03/11/2026.", "80%")}

<h2>10. Testes realizados</h2>
<p>São <strong>38 testes automatizados, todos aprovados</strong> (<code>tests/evidencias/resultado_pytest.txt</code>). A queda da API e do Telegram é provocada com um servidor HTTP local. A saída abaixo vem de <code>scripts/demonstrar.py</code>.</p>
<h3>Sucesso: dia sem chuva forte, nenhum envio</h3>
{evidencia("cenario_sucesso.txt")}
<h3>Decisão: evento de chuva no Jardim Ângela, de 15 em 15 minutos</h3>
{evidencia("cenario_decisao.txt")}
<h3>Falha: API fora do ar e recuperação</h3>
{evidencia("cenario_falha_api.txt")}
<h3>Falha: canais de envio fora do ar e fila de reenvio</h3>
{evidencia("cenario_falha_canal.txt")}
<h3>Falha: arquivo corrompido e quarentena</h3>
{evidencia("cenario_falha_arquivo.txt")}

<h2>11. Segurança e LGPD</h2>
<ul>
<li><strong>Minimização:</strong> o nome e o telefone do cadastro não são guardados. O banco tem só <code>morador_hash</code> (SHA-256 com salt, igual ao da camada Prata), setor e canal.</li>
<li><strong>Logs:</strong> só hash parcial. Um filtro remove telefone, nome e token de qualquer mensagem de erro, e um teste confere isso nas saídas e no banco.</li>
<li><strong>MVP:</strong> <code>alertas.json</code> só tem dados agregados por setor.</li>
<li><strong>Credenciais:</strong> salt e token ficam no <code>.env</code>, fora do repositório. O token do Telegram não aparece no log nem em caso de erro.</li>
<li><strong>Dados de teste:</strong> o cadastro é fictício, com DDD 00, que não existe.</li>
<li><strong>Pessoa no circuito:</strong> o nível é uma sugestão explicada pelos fatores. Quem decide remover moradores é a Defesa Civil, e as mensagens de alerta dizem isso.</li>
</ul>
<h3>Limitações</h3>
<ul>
<li>WhatsApp, SMS e e-mail são simulados. Sem token configurado, o Telegram também é. O canal Telegram foi testado contra um servidor falso, e não contra a API real.</li>
<li>Sensores, relatos e eventos de chuva extrema vêm do simulador do pipeline. Os horários dos alertas demonstram o método e não medem a antecedência real.</li>
<li>Os limiares do motor são ilustrativos.</li>
</ul>

<h2>12. Links</h2>
<table><tr><th>Item</th><th>Link</th></tr>
<tr><td>Repositório GitHub</td><td>{link("REPO_URL")}</td></tr>
<tr><td>Vídeo demonstrativo</td><td>{link("VIDEO_URL")}</td></tr>
<tr><td>MVP</td><td><a href="https://joaogdiass.github.io/encosta-viva-dados/">https://joaogdiass.github.io/encosta-viva-dados/</a></td></tr></table>
"""

pagina = f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Encosta Viva: robô de alertas</title><style>{CSS}</style></head><body>{CORPO}</body></html>'
destino = RAIZ / "docs" / "relatorio_tecnico.pdf"
with tempfile.TemporaryDirectory() as pasta:
    arquivo = Path(pasta) / "relatorio.html"
    arquivo.write_text(pagina, encoding="utf-8")
    subprocess.run([NAVEGADOR, "--headless=new", "--disable-gpu", f"--user-data-dir={pasta}/perfil", "--no-pdf-header-footer",
                    f"--print-to-pdf={destino}", arquivo.as_uri()], capture_output=True, timeout=120, check=True)
print(destino, destino.stat().st_size)
