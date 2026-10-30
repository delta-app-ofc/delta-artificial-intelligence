# CI técnico

Em pull requests e por execução manual, o workflow instala as dependências em Python 3.12, verifica conflitos com `pip check`, compila os módulos de `app` e executa os testes versionados em `tests/`. Os testes atuais verificam dois cenários isolados do cálculo de previsão. `APP_ENV=test` evita carregar o `.env`.

Para executar localmente:

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q app
python -m unittest discover -s tests -v
```

Defina `APP_ENV=test` no ambiente antes dos comandos. Estes testes não validam API, bancos, provedores de IA nem integrações externas. O workflow organizacional de checklist continua independente; a obrigatoriedade do check para merge depende das regras do repositório.
