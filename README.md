# CastFin

Controle financeiro pessoal e simples, feito com **Python + Flask + SQLite**.

> 🚧 **Projeto em desenvolvimento.** Este é um projeto de estudo, construído aos poucos. Hoje existe apenas o dashboard mensal funcional; o restante está planejado e pode mudar.

## Status atual

| Funcionalidade | Situação |
| --- | --- |
| Dashboard mensal (receitas, despesas e saldo) | ✅ Funcional |
| Despesas por categoria e histórico do mês | ✅ Funcional |
| Navegação entre meses | ✅ Funcional |
| Cadastro e exclusão de lançamentos (alimenta o dashboard) | ✅ Funcional |
| Edição de lançamentos | ⏳ Planejado |
| Orçamento por categoria | ⏳ Planejado |

## Tecnologias

- Python + Flask (lógica da aplicação)
- HTML + CSS (interface responsiva)
- SQLite (banco local, criado automaticamente)

## Como executar

Abra o terminal **dentro da pasta do projeto** (a que contém o `app.py`).

**Windows (cmd ou PowerShell):**

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

**Linux/Mac:**

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Abra http://127.0.0.1:5000 no navegador. O arquivo `castfin.db` é criado na primeira execução.

No Windows, também é possível dar dois cliques em `run_windows.bat`. Se o Windows bloquear o arquivo baixado, use os comandos acima no terminal.

## Estrutura

```
castfin/
├── app.py              # Flask + regras financeiras
├── requirements.txt
├── run_windows.bat
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   └── form.html
└── static/css/style.css
```

## Decisões técnicas

- Valores guardados em **centavos (inteiros)** para evitar erros de arredondamento.
- Datas no formato `AAAA-MM-DD`, exibidas como `DD/MM/AAAA`.
- Consultas SQL parametrizadas.

## Aviso

A `secret_key` em `app.py` é apenas de desenvolvimento. Não use este projeto em produção como está.
