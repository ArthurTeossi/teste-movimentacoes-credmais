import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation  #pra que serve isso anta gorda 

import fdb
from flask import (Flask, render_template, request, redirect, url_for, flash, send_file, jsonify)
from fpdf import FPDF

app = Flask(__name__)

app.config["SECRET_KEY"] = "1234"
host = "localhost"
database = r"C:\Users\Aluno\Downloads\Movimenta-es-main\BANCO.FDB"
user = "SYSDBA"
password = "sysdba"


# Enquanto não existe login nesta tela, usamos sempre o mesmo usuário.
# Quando tiver login, troque por o id do usuário logado (ex.: session["id_usuario"]).
ID_USUARIO = 1

# Valores gravados na coluna TIPO da tabela MOV_FINANCEIRA
TIPO_RECEITA = 1
TIPO_DESPESA = 2

# chave do filtro -> (texto mostrado no botão, quantidade de dias para trás)
PERIODOS = {
    "ano": ("Último ano", 365),
    "mes": ("Último mês", 30),
    "semana": ("Últimos 7 dias", 7),
    "dia": ("Últimas 24 horas", 1),    #tira issso ANTA GORDA
}


def conectar():
    return fdb.connect(
        host=host,
        database=database,
        user=user,
        password=password
    )


def formatar_reais(valor):  #SE VC N EXPLICAR DIREITO TIRA ANTA GORDA
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# permite usar {{ valor|reais }} nos templates
app.add_template_filter(formatar_reais, "reais")  #QUE PORRA É ESSA


def data_inicial(periodo):
    """Calcula a data de início do filtro escolhido."""
    dias = PERIODOS[periodo][1]
    return date.today() - timedelta(days=dias)   #OQUE ISSO SIGNOFICA PORRA 


# ----------------------------------------------------------------
# CONSULTAS AO BANCO
# (se a tabela mudar, os SQLs que precisam ser ajustados estão aqui,
#  em somar(), e nas rotas de nova / editar / excluir)
# ----------------------------------------------------------------

def montar_movimentacao(linha):
    """Transforma uma linha do banco em um dicionário para usar nos templates.

    A linha vem na ordem: ID_MOV_FINANCEIRA, DATA_LANCAMENTO, DESCRICAO, TIPO, VALOR
    """
    return {
        "id": linha[0],
        "data": linha[1].strftime("%d/%m"),
        "data_completa": linha[1].strftime("%d/%m/%Y"),  #QUE PORRA DE TANTO CÓDIGO É ESSE
        "descricao": linha[2] or "",
        "categoria": "Receita" if linha[3] == TIPO_RECEITA else "Despesa",
        "valor": float(linha[4])
    }


def buscar_movimentacoes(data_inicio):
    """Movimentações do usuário desde data_inicio, da mais recente para a mais antiga."""
    con = conectar()
    cursor = con.cursor()
    cursor.execute(
        "SELECT ID_MOV_FINANCEIRA, DATA_LANCAMENTO, DESCRICAO, TIPO, VALOR "
        "FROM MOV_FINANCEIRA "
        "WHERE ID_USUARIO = ? AND DATA_LANCAMENTO >= ? "
        "ORDER BY DATA_LANCAMENTO DESC, ID_MOV_FINANCEIRA DESC",
        (ID_USUARIO, data_inicio)
    )
    linhas = cursor.fetchall()
    cursor.close()
    con.close()

    movimentacoes = []
    for linha in linhas:
        movimentacoes.append(montar_movimentacao(linha))
    return movimentacoes


def buscar_movimentacao(id_mov):
    """Uma movimentação do usuário pelo id. Devolve None se não existir."""
    con = conectar()
    cursor = con.cursor()
    cursor.execute(
        "SELECT ID_MOV_FINANCEIRA, DATA_LANCAMENTO, DESCRICAO, TIPO, VALOR "
        "FROM MOV_FINANCEIRA "
        "WHERE ID_MOV_FINANCEIRA = ? AND ID_USUARIO = ?",
        (id_mov, ID_USUARIO)
    )
    linha = cursor.fetchone()
    cursor.close()
    con.close()

    if linha is None:
        return None
    return montar_movimentacao(linha)


def somar(tipo, data_inicio=None):
    """Soma os valores de um tipo (receita/despesa) do usuário."""
    sql = ("SELECT VALOR FROM MOV_FINANCEIRA "
           "WHERE ID_USUARIO = ? AND TIPO = ?")
    parametros = [ID_USUARIO, tipo]

    if data_inicio is not None:
        sql += " AND DATA_LANCAMENTO >= ?"
        parametros.append(data_inicio)

    con = conectar()
    cursor = con.cursor()
    cursor.execute(sql, parametros)
    linhas = cursor.fetchall()
    cursor.close()
    con.close()

    total = 0
    for linha in linhas:
        total += float(linha[0])
    return total


# ----------------------------------------------------------------
# ROTAS
# ----------------------------------------------------------------

@app.route("/")
@app.route("/movimentacoes")
def inicio():
    periodo = request.args.get("periodo", "ano")   #OQUE É AGS
    if periodo not in PERIODOS:
        periodo = "ano"

    dados = buscar_movimentacoes(data_inicial(periodo))

    # Saldo considera todo o histórico do usuário
    saldo = somar(TIPO_RECEITA) - somar(TIPO_DESPESA)

    # Os cartões dizem "Nos últimos 30 dias"
    inicio_30_dias = date.today() - timedelta(days=30)
    receitas = somar(TIPO_RECEITA, inicio_30_dias)
    despesas = somar(TIPO_DESPESA, inicio_30_dias)

    return render_template(
        "index.html",
        dados=dados,
        saldo=saldo,
        receitas=receitas,
        despesas=despesas,
        periodo=periodo,
        periodos=PERIODOS
    )


@app.route("/nova-movimentacao", methods=["GET", "POST"])
def nova_movimentacao():
    if request.method == "POST":
        tipo = request.form.get("tipo", "").strip()
        categoria = request.form.get("categoria", "").strip()
        valor = request.form.get("valor", "").strip()

        if not tipo:
            flash("Informe o tipo de movimentação.", "erro")
            return redirect(url_for("nova_movimentacao"))

        if categoria not in ("Receita", "Despesa"):
            flash("Selecione Receita ou Despesa.", "erro")
            return redirect(url_for("nova_movimentacao"))

        try:
            valor_numerico = Decimal(
                valor.replace(".", "").replace(",", ".")
                if "," in valor
                else valor
            )

            if not valor_numerico.is_finite() or valor_numerico <= 0:
                raise InvalidOperation

        except (InvalidOperation, ValueError):
            flash("Informe um valor válido maior que zero.", "erro")
            return redirect(url_for("nova_movimentacao"))

        tipo_numero = TIPO_RECEITA if categoria == "Receita" else TIPO_DESPESA

        con = conectar()
        cursor = con.cursor()
        cursor.execute(
            "INSERT INTO MOV_FINANCEIRA "
            "(TIPO, VALOR, DATA_LANCAMENTO, DESCRICAO, ID_USUARIO) "
            "VALUES (?, ?, ?, ?, ?)",
            (tipo_numero, valor_numerico, date.today(), tipo, ID_USUARIO)
        )
        con.commit()
        cursor.close()
        con.close()

        flash("Movimentação registrada com sucesso!", "sucesso")
        return redirect(url_for("inicio"))

    return render_template("nova_movimentacao.html")


@app.route("/movimentacao/<int:id_mov>")
def visualizar_movimentacao(id_mov):
    mov = buscar_movimentacao(id_mov)

    if mov is None:
        flash("Movimentação não encontrada.", "erro")
        return redirect(url_for("inicio"))

    return render_template("visualizar_movimentacao.html", mov=mov)


@app.route("/movimentacao/<int:id_mov>/editar", methods=["GET", "POST"])
def editar_movimentacao(id_mov):
    mov = buscar_movimentacao(id_mov)

    if mov is None:
        flash("Movimentação não encontrada.", "erro")
        return redirect(url_for("inicio"))

    if request.method == "POST":
        # Só a descrição pode ser alterada (valor, categoria e data ficam como estão)
        descricao = request.form.get("descricao", "").strip()

        if not descricao:
            flash("Informe a descrição da movimentação.", "erro")
            return redirect(url_for("editar_movimentacao", id_mov=id_mov))

        if len(descricao) > 100:
            flash("A descrição pode ter no máximo 100 caracteres.", "erro")
            return redirect(url_for("editar_movimentacao", id_mov=id_mov))

        con = conectar()
        cursor = con.cursor()
        cursor.execute(
            "UPDATE MOV_FINANCEIRA SET DESCRICAO = ? "
            "WHERE ID_MOV_FINANCEIRA = ? AND ID_USUARIO = ?",
            (descricao, id_mov, ID_USUARIO)
        )
        con.commit()
        cursor.close()
        con.close()

        flash("Descrição atualizada com sucesso!", "sucesso")
        return redirect(url_for("visualizar_movimentacao", id_mov=id_mov))

    return render_template("editar_movimentacao.html", mov=mov)


@app.route("/movimentacao/<int:id_mov>/excluir", methods=["POST"])
def excluir_movimentacao(id_mov):
    mov = buscar_movimentacao(id_mov)   #PQ USA ID DENTRO DA CHAVE 

    if mov is None:
        flash("Movimentação não encontrada.", "erro")
        return redirect(url_for("inicio"))

    con = conectar()
    cursor = con.cursor()
    cursor.execute(
        "DELETE FROM MOV_FINANCEIRA "
        "WHERE ID_MOV_FINANCEIRA = ? AND ID_USUARIO = ?",
        (id_mov, ID_USUARIO)
    )
    con.commit()
    cursor.close()
    con.close()

    flash("Movimentação excluída com sucesso!", "sucesso")
    return redirect(url_for("inicio"))


# ----------------------------------------------------------------
# RELATÓRIO EM PDF
# ----------------------------------------------------------------

def texto_pdf(texto):
    """O FPDF com fonte Arial só aceita Latin-1; troca o que não couber."""
    return str(texto).encode("latin-1", "replace").decode("latin-1")  # OQUE SAO ESSES CODIGOS 


@app.route("/relatorio", methods=["GET"])
def relatorio():
    # 1. Consulta: mesmo filtro que está selecionado na tela
    periodo = request.args.get("periodo", "ano")
    if periodo not in PERIODOS:
        periodo = "ano"

    movimentacoes = buscar_movimentacoes(data_inicial(periodo))

    if not movimentacoes:
        return jsonify({"erro": "Nenhuma movimentação encontrada no período."}), 404  #Q PORRA É JSONIFY

    # 2. Desenho do PDF   # TIRA ESSA PORRA DE DESENHO DO PDF SE NAO TIVER NO CODIGO DA LAIS 
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Arial", style="B", size=16)
    pdf.cell(200, 10, texto_pdf("Relatório de Movimentações - CredMais"), ln=True, align="C")

    pdf.set_font("Arial", size=10)
    pdf.cell(200, 8, texto_pdf(f"Período: {PERIODOS[periodo][0]}  |  Gerado em: "
                               f"{datetime.now().strftime('%d/%m/%Y %H:%M')}"),
             ln=True, align="C")

    # linha separadora
    pdf.ln(5)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # cabeçalho da tabela
    pdf.set_font("Arial", style="B", size=11)
    pdf.cell(30, 10, "Data", border=1)
    pdf.cell(80, 10, texto_pdf("Descrição"), border=1)
    pdf.cell(35, 10, "Categoria", border=1)
    pdf.cell(45, 10, "Valor (R$)", border=1, ln=True)

    # linhas (uma por movimentação)
    pdf.set_font("Arial", size=11)
    total_receitas = 0
    total_despesas = 0

    for item in movimentacoes:
        if item["categoria"] == "Receita":
            total_receitas += item["valor"]
            sinal = "+"
        else:
            total_despesas += item["valor"]
            sinal = "-"

        pdf.cell(30, 10, item["data_completa"], border=1)    #TIRA ISSO TAMBEM NAO TEM NO DA LAISSSSSSSSSSSSSSSSSSSS PORRA         
        pdf.cell(80, 10, texto_pdf(item["descricao"])[:40], border=1)
        pdf.cell(35, 10, item["categoria"], border=1)
        pdf.cell(45, 10, f"{sinal} {formatar_reais(item['valor'])}", border=1, ln=True)

    # totais no final
    contador = len(movimentacoes)
    pdf.ln(10)
    pdf.set_font("Arial", style="B", size=12)
    pdf.cell(200, 10, f"Total de movimentações: {contador}", ln=True, align="C")
    pdf.cell(200, 10, f"Receitas: R$ {formatar_reais(total_receitas)}", ln=True, align="C")
    pdf.cell(200, 10, f"Despesas: R$ {formatar_reais(total_despesas)}", ln=True, align="C")
    pdf.cell(200, 10, f"Saldo do período: R$ {formatar_reais(total_receitas - total_despesas)}",
             ln=True, align="C")

    # 3. Salva e envia para download
    pdf_path = os.path.join(app.root_path, "relatorio_movimentacoes.pdf")
    pdf.output(pdf_path)
    return send_file(pdf_path, as_attachment=True, mimetype="application/pdf")


if __name__ == "__main__":
    app.run(debug=True)
