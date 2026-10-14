"""CastFin - controle financeiro simples (Flask + SQLite)."""
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "castfin.db"

app = Flask(__name__)
app.secret_key = "castfin-dev-troque-depois"  # necessário para mensagens flash

CATEGORIAS = {
    "despesa": ["Alimentação", "Transporte", "Moradia", "Saúde", "Lazer", "Educação", "Outras"],
    "receita": ["Salário", "Freelance", "Investimentos", "Outras"],
}
PESSOAS = ["Eu"]  # futuramente: adicionar a segunda pessoa para finanças compartilhadas

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


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
                data        TEXT    NOT NULL,          -- formato AAAA-MM-DD
                pessoa      TEXT    NOT NULL DEFAULT 'Eu'
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
        raise ValueError("Valor inválido.")
    if not valor.is_finite() or valor <= 0:
        raise ValueError("O valor deve ser maior que zero.")
    return int((valor * 100).to_integral_value(ROUND_HALF_UP))


def formatar_brl(cents):
    cents = int(cents or 0)
    sinal = "-" if cents < 0 else ""
    reais, centavos = divmod(abs(cents), 100)
    return f"{sinal}R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"


app.jinja_env.filters["brl"] = formatar_brl
app.jinja_env.filters["data_br"] = lambda iso: datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")


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


# ---------- Rotas ----------
@app.route("/")
def dashboard():
    mes = mes_valido(request.args.get("mes"))
    db = get_db()
    filtro = "strftime('%Y-%m', data) = ?"

    totais = {"receita": 0, "despesa": 0}
    for linha in db.execute(
        f"SELECT tipo, SUM(valor_cents) AS total FROM transacoes WHERE {filtro} GROUP BY tipo", (mes,)
    ):
        totais[linha["tipo"]] = linha["total"] or 0

    por_categoria = db.execute(
        f"""SELECT categoria, SUM(valor_cents) AS total FROM transacoes
            WHERE tipo = 'despesa' AND {filtro}
            GROUP BY categoria ORDER BY total DESC""",
        (mes,),
    ).fetchall()

    lancamentos = db.execute(
        f"SELECT * FROM transacoes WHERE {filtro} ORDER BY data DESC, id DESC", (mes,)
    ).fetchall()

    ano, m = mes.split("-")
    return render_template(
        "dashboard.html",
        mes=mes,
        mes_titulo=f"{MESES[int(m) - 1].capitalize()} de {ano}",
        mes_anterior=mes_vizinho(mes, -1),
        mes_seguinte=mes_vizinho(mes, 1),
        receitas=totais["receita"],
        despesas=totais["despesa"],
        saldo=totais["receita"] - totais["despesa"],
        por_categoria=por_categoria,
        lancamentos=lancamentos,
    )


@app.route("/lancamentos/novo", methods=["GET", "POST"])
def novo_lancamento():
    form = {"tipo": "despesa", "data": date.today().isoformat(), "pessoa": PESSOAS[0]}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in
                ("tipo", "descricao", "valor", "categoria", "data", "pessoa")}
        erro = None
        try:
            if form["tipo"] not in CATEGORIAS:
                raise ValueError("Escolha receita ou despesa.")
            if not form["descricao"]:
                raise ValueError("Informe a descrição.")
            if form["categoria"] not in CATEGORIAS[form["tipo"]]:
                raise ValueError("Escolha uma categoria válida.")
            if form["pessoa"] not in PESSOAS:
                raise ValueError("Pessoa inválida.")
            try:
                datetime.strptime(form["data"], "%Y-%m-%d")
            except ValueError:
                raise ValueError("Data inválida.")
            cents = parse_valor(form["valor"])
        except ValueError as e:
            erro = str(e)

        if erro:
            flash(erro, "erro")
        else:
            db = get_db()
            db.execute(
                "INSERT INTO transacoes (descricao, valor_cents, tipo, categoria, data, pessoa) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (form["descricao"][:120], cents, form["tipo"], form["categoria"], form["data"], form["pessoa"]),
            )
            db.commit()
            flash("Lançamento salvo!", "ok")
            return redirect(url_for("dashboard", mes=form["data"][:7]))

    return render_template("form.html", form=form, categorias=CATEGORIAS, pessoas=PESSOAS)


@app.route("/lancamentos/<int:lancamento_id>/excluir", methods=["POST"])
def excluir_lancamento(lancamento_id):
    db = get_db()
    db.execute("DELETE FROM transacoes WHERE id = ?", (lancamento_id,))
    db.commit()
    flash("Lançamento excluído.", "ok")
    return redirect(request.referrer or url_for("dashboard"))


init_db()

if __name__ == "__main__":
    import threading, webbrowser
    # abre o navegador 1,5 s depois, quando o servidor já subiu
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(debug=False)
