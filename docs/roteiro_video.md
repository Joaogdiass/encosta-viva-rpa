# Roteiro do vídeo (até 3 minutos)

Antes de gravar, deixe abertos: o terminal na pasta do projeto, a tela do MVP e `docs/processo_to_be.bpmn` em bpmn.io ou `assets/fluxo_bpmn.png`. Rode os comandos uma vez antes: o cenário de falha da API leva alguns segundos e precisa de internet.

Para ver a tela do MVP com os alertas, rode o primeiro comando abaixo e sirva a pasta do MVP:

```bash
py -m http.server 8765 --directory ../encosta-viva-dados/mvp
```

| Tempo | O que mostrar | O que falar |
|---|---|---|
| 0:00 | Tela do MVP | Em dia de chuva, a Defesa Civil abre sites, cruza com uma planilha, decide no olho quem avisar e anota vistoria em papel. Um sensor quebrado passa despercebido. A Encosta Viva troca esse processo por um robô que roda a cada 15 minutos. |
| 0:25 | Imagem do BPMN | O robô lê a camada Ouro, os sensores, os relatos e o Open-Meteo. Para cada setor, calcula o nível e compara com o anterior. Depois envia, abre chamados, grava o log e entrega o resultado à tela. |
| 0:50 | Terminal: `py scripts/demonstrar.py decisao` | Esta é a reprodução de um evento de chuva simulado no Jardim Ângela, de 15 em 15 minutos. O setor sobe para Atenção às 14h, Alerta às 15h15 e Alerta máximo às 20h15. Nos outros ciclos, o nível fica igual e o robô não reenvia. |
| 1:25 | Tela do MVP, recarregada | O resultado aparece na tela do cidadão: o alerta, o motivo, o que fazer e os moradores avisados. O envio aqui é simulado, porque o cadastro é fictício. Quem decide remover moradores é a Defesa Civil. |
| 1:50 | Terminal: `py scripts/demonstrar.py falha_api` | Agora a API fica fora do ar. O robô tenta três vezes, usa o último valor com uma flag de dado desatualizado e avisa o operador. Quando a API volta, o incidente é fechado. Dado incompleto nunca encerra um alerta. |
| 2:20 | Terminal: `py scripts/demonstrar.py falha_canal` | Se o Telegram falha três vezes, o envio passa para o SMS. Se todos os canais caem, o alerta fica na fila e sai no ciclo seguinte. |
| 2:40 | `logs/amostras/` e `assets/relatorio_diario_exemplo.pdf` | Cada execução deixa um log com data, itens processados e erros, só com hash, sem nome nem telefone. Todo dia, o coordenador recebe este relatório. |
| 2:55 | Encerramento | O robô é o que faz o alerta chegar a quem mora na encosta, sem depender de alguém clicar. |

Quem aparece e fala no vídeo fica a critério da equipe. Publique como não listado e teste o link em uma janela anônima.
