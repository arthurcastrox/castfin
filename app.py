"""CastFin - controle financeiro pessoal (Flask + SQLite)."""
import calendar
import csv
import io
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, url_for)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "castfin.db"

app = Flask(__name__)
app.secret_key = "castfin-dev-troque-depois"  # necessário para mensagens flash

# ---------- Configuração (edite aqui para personalizar) ----------
CATEGORIAS = {
    "despesa": ["Moradia", "Alimentação", "Transporte", "Saúde", "Lazer", "Educação", "Outras"],
    "receita": ["Salário", "Freelance", "Investimentos", "Outras"],
}

# Cor de cada categoria (usada no gráfico, na lista e na tabela)
CORES_CATEGORIA = {
    "Moradia": "#1f6feb",
    "Alimentação": "#0e9f9a",
    "Transporte": "#e0a100",
    "Saúde": "#d6457f",
    "Lazer": "#7c5cd6",
    "Educação": "#6aa11f",
    "Outras": "#6b7686",
    "Salário": "#138a4b",
    "Freelance": "#0e9f9a",
    "Investimentos": "#1f6feb",
}

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun",
               "jul", "ago", "set", "out", "nov", "dez"]

MESES_NO_GRAFICO = 6


# ---------- Banco de dados ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS transacoes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                descricao   TEXT    NOT NULL,
                valor_cents INTEGER NOT NULL CHECK (valor_cents > 0),
                tipo        TEXT    NOT NULL CHECK (tipo IN ('receita', 'despesa')),
                categoria   TEXT    NOT NULL,
                data        TEXT    NOT NULL           -- formato AAAA-MM-DD
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_transacoes_data ON transacoes (data)")


# ---------- Regras financeiras / utilidades ----------
def parse_valor(texto):
    """Converte '1.234,56' ou '1234.56' em centavos (int). Levanta ValueError se inválido."""
    t = (texto or "").strip().replace("R$", "").replace(" ", "")
    if not t:
        raise ValueError("Informe o valor.")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(t)
    except InvalidOperation:
        raise ValueError("Valor inválido. Use números, por exemplo 1.234,56.")
    if not valor.is_finite() or valor <= 0:
        raise ValueError("O valor deve ser maior que zero.")
    return int((valor * 100).to_integral_value(ROUND_HALF_UP))


def formatar_brl(cents):
    cents = int(cents or 0)
    sinal = "-" if cents < 0 else ""
    reais, centavos = divmod(abs(cents), 100)
    return f"{sinal}R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"


def formatar_brl_curto(cents):
    """R$ 4,8 mil / R$ 1,2 mi — para rótulos de gráfico."""
    v = abs(int(cents or 0)) / 100
    if v >= 1_000_000:
        return f"R$ {v / 1_000_000:.1f} mi".replace(".", ",")
    if v >= 1_000:
        return f"R$ {v / 1_000:.1f} mil".replace(".", ",")
    return f"R$ {v:.0f}"


def cents_para_campo(cents):
    reais, centavos = divmod(int(cents), 100)
    return f"{reais},{centavos:02d}"


app.jinja_env.filters["brl"] = formatar_brl
app.jinja_env.filters["brl_curto"] = formatar_brl_curto
app.jinja_env.filters["data_br"] = lambda iso: datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
app.jinja_env.filters["cor_categoria"] = lambda nome: CORES_CATEGORIA.get(nome, "#6b7686")


def mes_valido(texto):
    """Retorna 'AAAA-MM' válido; se inválido ou vazio, usa o mês atual."""
    try:
        return datetime.strptime(texto or "", "%Y-%m").strftime("%Y-%m")
    except ValueError:
        return date.today().strftime("%Y-%m")


def mes_vizinho(mes, delta):
    ano, m = map(int, mes.split("-"))
    idx = ano * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def nome_mes(mes, com_ano=False):
    ano, m = mes.split("-")
    nome = MESES[int(m) - 1]
    return f"{nome.capitalize()} de {ano}" if com_ano else nome


def totais_mes(db, mes):
    totais = {"receita": 0, "despesa": 0}
    for linha in db.execute(
        "SELECT tipo, SUM(valor_cents) AS total FROM transacoes "
        "WHERE strftime('%Y-%m', data) = ? GROUP BY tipo", (mes,)
    ):
        totais[linha["tipo"]] = linha["total"] or 0
    return totais


def variacao(atual, anterior, mais_e_bom, nome_anterior):
    """Compara com o mês anterior. Retorna dict para o template."""
    if not anterior:
        return {"texto": f"sem dados em {nome_anterior}", "classe": "neutro", "seta": ""}
    pct = (atual - anterior) / abs(anterior) * 100
    if round(pct) == 0:
        return {"texto": f"igual a {nome_anterior}", "classe": "neutro", "seta": ""}
    subiu = pct > 0
    bom = subiu == mais_e_bom
    return {
        "texto": f"{abs(pct):.0f}% vs. {nome_anterior}",
        "classe": "bom" if bom else "ruim",
        "seta": "▲" if subiu else "▼",
    }


def validar_lancamento(form):
    """Valida os campos do formulário. Retorna (centavos, None) ou (None, mensagem)."""
    try:
        if form["tipo"] not in CATEGORIAS:
            raise ValueError("Escolha receita ou despesa.")
        if not form["descricao"]:
            raise ValueError("Informe a descrição.")
        if form["categoria"] not in CATEGORIAS[form["tipo"]]:
            raise ValueError("Escolha uma categoria válida.")
        try:
            datetime.strptime(form["data"], "%Y-%m-%d")
        except ValueError:
            raise ValueError("Data inválida.")
        return parse_valor(form["valor"]), None
    except ValueError as e:
        return None, str(e)


CAMPOS_FORM = ("tipo", "descricao", "valor", "categoria", "data")


# ---------- Rotas ----------
@app.route("/")
def dashboard():
    mes = mes_valido(request.args.get("mes"))
    db = get_db()
    hoje = date.today()

    mes_ant = mes_vizinho(mes, -1)
    atual = totais_mes(db, mes)
    anterior = totais_mes(db, mes_ant)
    receitas, despesas = atual["receita"], atual["despesa"]
    saldo = receitas - despesas
    nome_ant = nome_mes(mes_ant)

    # Evolução dos últimos meses
    serie = []
    for i in range(MESES_NO_GRAFICO - 1, -1, -1):
        m = mes_vizinho(mes, -i)
        t = totais_mes(db, m)
        serie.append({"mes": m, "rotulo": MESES_ABREV[int(m[5:]) - 1],
                      "receita": t["receita"], "despesa": t["despesa"], "atual": m == mes})
    teto = max([max(s["receita"], s["despesa"]) for s in serie] + [1])
    for s in serie:
        s["h_receita"] = max(round(s["receita"] / teto * 100, 1), 2 if s["receita"] else 0)
        s["h_despesa"] = max(round(s["despesa"] / teto * 100, 1), 2 if s["despesa"] else 0)

    # Despesas por categoria (com fatias para o gráfico em anel)
    linhas = db.execute(
        """SELECT categoria, SUM(valor_cents) AS total FROM transacoes
           WHERE tipo = 'despesa' AND strftime('%Y-%m', data) = ?
           GROUP BY categoria ORDER BY total DESC""", (mes,)
    ).fetchall()
    por_categoria, fatias, acumulado = [], [], 0.0
    for r in linhas:
        pct = r["total"] / despesas * 100 if despesas else 0
        cor = CORES_CATEGORIA.get(r["categoria"], "#6b7686")
        por_categoria.append({"categoria": r["categoria"], "total": r["total"],
                              "pct": round(pct), "pct_exato": pct, "cor": cor})
        fatias.append(f"{cor} {acumulado:.2f}% {acumulado + pct:.2f}%")
        acumulado += pct
    anel = f"conic-gradient({', '.join(fatias)})" if fatias else "none"

    # Indicadores
    dias = hoje.day if mes == hoje.strftime("%Y-%m") else calendar.monthrange(*map(int, mes.split("-")))[1]
    maior = db.execute(
        """SELECT * FROM transacoes WHERE tipo = 'despesa' AND strftime('%Y-%m', data) = ?
           ORDER BY valor_cents DESC, id DESC LIMIT 1""", (mes,)
    ).fetchone()
    taxa_poupanca = round(saldo / receitas * 100) if receitas else None
    media_diaria = round(despesas / dias) if dias else 0
    comprometido = round(despesas / receitas * 100) if receitas else None

    # Lançamentos (com filtros)
    f_q = (request.args.get("q") or "").strip()
    f_tipo = request.args.get("tipo") if request.args.get("tipo") in CATEGORIAS else ""
    todas_categorias = sorted({c for lista in CATEGORIAS.values() for c in lista})
    f_cat = request.args.get("categoria") if request.args.get("categoria") in todas_categorias else ""

    sql = "SELECT * FROM transacoes WHERE strftime('%Y-%m', data) = ?"
    params = [mes]
    if f_q:
        sql += " AND descricao LIKE ? ESCAPE '\\'"
        params.append("%" + f_q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if f_tipo:
        sql += " AND tipo = ?"
        params.append(f_tipo)
    if f_cat:
        sql += " AND categoria = ?"
        params.append(f_cat)
    sql += " ORDER BY data DESC, id DESC"
    lancamentos = db.execute(sql, params).fetchall()
    total_mes = db.execute(
        "SELECT COUNT(*) FROM transacoes WHERE strftime('%Y-%m', data) = ?", (mes,)
    ).fetchone()[0]

    return render_template(
        "dashboard.html",
        mes=mes,
        mes_titulo=nome_mes(mes, com_ano=True),
        mes_anterior=mes_ant,
        mes_seguinte=mes_vizinho(mes, 1),
        eh_mes_atual=mes == hoje.strftime("%Y-%m"),
        mes_atual=hoje.strftime("%Y-%m"),
        receitas=receitas, despesas=despesas, saldo=saldo,
        var_receitas=variacao(receitas, anterior["receita"], True, nome_ant),
        var_despesas=variacao(despesas, anterior["despesa"], False, nome_ant),
        var_saldo=variacao(saldo, anterior["receita"] - anterior["despesa"], True, nome_ant),
        serie=serie,
        por_categoria=por_categoria, anel=anel,
        taxa_poupanca=taxa_poupanca, media_diaria=media_diaria,
        comprometido=comprometido, maior=maior,
        lancamentos=lancamentos, total_mes=total_mes,
        filtros={"q": f_q, "tipo": f_tipo, "categoria": f_cat},
        filtrando=bool(f_q or f_tipo or f_cat),
        categorias_filtro=todas_categorias,
    )


@app.route("/lancamentos/novo", methods=["GET", "POST"])
def novo_lancamento():
    form = {"tipo": "despesa", "data": date.today().isoformat()}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in CAMPOS_FORM}
        cents, erro = validar_lancamento(form)
        if erro:
            flash(erro, "erro")
        else:
            db = get_db()
            db.execute(
                "INSERT INTO transacoes (descricao, valor_cents, tipo, categoria, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (form["descricao"][:120], cents, form["tipo"], form["categoria"], form["data"]),
            )
            db.commit()
            flash("Lançamento salvo.", "ok")
            return redirect(url_for("dashboard", mes=form["data"][:7]))

    return render_template("form.html", form=form, categorias=CATEGORIAS, editando=None)


@app.route("/lancamentos/<int:lancamento_id>/editar", methods=["GET", "POST"])
def editar_lancamento(lancamento_id):
    db = get_db()
    atual = db.execute("SELECT * FROM transacoes WHERE id = ?", (lancamento_id,)).fetchone()
    if atual is None:
        abort(404)

    form = {"tipo": atual["tipo"], "descricao": atual["descricao"],
            "valor": cents_para_campo(atual["valor_cents"]),
            "categoria": atual["categoria"], "data": atual["data"]}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in CAMPOS_FORM}
        cents, erro = validar_lancamento(form)
        if erro:
            flash(erro, "erro")
        else:
            db.execute(
                "UPDATE transacoes SET descricao = ?, valor_cents = ?, tipo = ?, "
                "categoria = ?, data = ? WHERE id = ?",
                (form["descricao"][:120], cents, form["tipo"], form["categoria"],
                 form["data"], lancamento_id),
            )
            db.commit()
            flash("Alterações salvas.", "ok")
            return redirect(url_for("dashboard", mes=form["data"][:7]))

    return render_template("form.html", form=form, categorias=CATEGORIAS, editando=lancamento_id)


@app.route("/lancamentos/<int:lancamento_id>/excluir", methods=["POST"])
def excluir_lancamento(lancamento_id):
    db = get_db()
    db.execute("DELETE FROM transacoes WHERE id = ?", (lancamento_id,))
    db.commit()
    flash("Lançamento excluído.", "ok")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/exportar")
def exportar_csv():
    """Baixa os lançamentos do mês em CSV (abre direto no Excel)."""
    mes = mes_valido(request.args.get("mes"))
    linhas = get_db().execute(
        "SELECT data, tipo, categoria, descricao, valor_cents FROM transacoes "
        "WHERE strftime('%Y-%m', data) = ? ORDER BY data, id", (mes,)
    ).fetchall()
    saida = io.StringIO()
    saida.write("﻿")  # BOM: o Excel reconhece os acentos
    w = csv.writer(saida, delimiter=";")
    w.writerow(["Data", "Tipo", "Categoria", "Descrição", "Valor (R$)"])
    for r in linhas:
        valor = cents_para_campo(r["valor_cents"]) if r["tipo"] == "receita" else "-" + cents_para_campo(r["valor_cents"])
        w.writerow([datetime.strptime(r["data"], "%Y-%m-%d").strftime("%d/%m/%Y"),
                    r["tipo"].capitalize(), r["categoria"], r["descricao"], valor])
    return Response(saida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=castfin-{mes}.csv"})


init_db()

if __name__ == "__main__":
    import threading
    import webbrowser
    # abre o navegador 1,5 s depois, quando o servidor já subiu
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(debug=False)
