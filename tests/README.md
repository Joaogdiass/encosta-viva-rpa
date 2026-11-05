# Testes

```bash
py -m pytest tests -v
```

| Arquivo | O que cobre |
|---|---|
| `test_motor.py` | Regras do motor de risco e paridade com os níveis publicados pela camada Ouro |
| `test_cenarios.py` | Cenários de sucesso, decisão e falha, resiliência e LGPD |

A queda da API e do Telegram é testada de verdade, com um servidor HTTP local que responde com erro ou fica fora do ar.

`evidencias/` guarda a saída de `py scripts/demonstrar.py` e o resultado do pytest. O cenário `falha_api` precisa de internet, porque consulta o Open-Meteo real.
