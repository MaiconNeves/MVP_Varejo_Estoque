from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st


def _calcular_dias_sem_giro(df: pd.DataFrame, data_referencia: pd.Timestamp) -> pd.Series:
    """Calcula quantos dias se passaram desde a última saída registrada até a data de referência."""
    if "Ultima_Saida" not in df.columns:
        return pd.Series([np.nan] * len(df), index=df.index)

    datas_saida = pd.to_datetime(df["Ultima_Saida"], errors="coerce")
    dias = (data_referencia - datas_saida).dt.days
    return dias.clip(lower=0)


def calcular_indicadores_estoque(
    df_consolidado: pd.DataFrame,
    df_movs: pd.DataFrame | None = None,
    dias_periodo: int = 30,
    cobertura_minima: int = 7,
    cobertura_alvo: int = 15,
    dias_excesso: int = 45,
) -> pd.DataFrame:
    """Calcula os principais KPIs de estoque a partir do consolidado de XMLs."""
    df = df_consolidado.copy()

    # Identifica a coluna de saldo inicial conforme a origem (sessão ou CSV)
    col_inicial = "Qtd Inicial" if "Qtd Inicial" in df.columns else "Qtd Física"
    if col_inicial not in df.columns:
        df[col_inicial] = 0.0

    # Define a data de referência (maior data encontrada nos XMLs ou data atual)
    data_ref = pd.Timestamp.now().normalize()
    if df_movs is not None and not df_movs.empty and "Data_Emissao" in df_movs.columns:
        datas_validas = pd.to_datetime(df_movs["Data_Emissao"], errors="coerce").dropna()
        if not datas_validas.empty:
            data_ref = datas_validas.max()

    # 1. Demanda Média Diária (DMD)
    df["DMD"] = (df["Total_Saidas"] / max(dias_periodo, 1)).round(2)

    # 2. Estoque Médio e Giro de Estoque
    df["Estoque_Medio"] = ((df[col_inicial] + df["Saldo_Calculado"]) / 2).round(2)
    df["Giro_Estoque"] = np.where(
        df["Estoque_Medio"] > 0,
        (df["Total_Saidas"] / df["Estoque_Medio"]).round(2),
        0.0,
    )

    # 3. Cobertura de Estoque (em dias)
    df["Cobertura_Dias"] = np.where(
        df["DMD"] > 0,
        (df["Saldo_Calculado"].clip(lower=0) / df["DMD"]).round(1),
        np.where(df["Saldo_Calculado"] > 0, 999.0, 0.0),
    )

    # 4. Dias sem Giro (desde a última venda registrada)
    df["Dias_Sem_Giro"] = _calcular_dias_sem_giro(df, data_ref)

    # 5. Preço Médio de Venda, Custo Médio de Compra e Valor Estimado em Estoque
    df["Preco_Medio_Venda"] = np.where(
        df["Total_Saidas"] > 0,
        (df["Valor_Saidas"] / df["Total_Saidas"]).round(2),
        0.0,
    )
    df["Custo_Medio_Compra"] = np.where(
        df["Total_Entradas"] > 0,
        (df["Valor_Entradas"] / df["Total_Entradas"]).round(2),
        0.0,
    )
    # Valora o saldo atual pelo custo médio de compra (ou preço de venda se não houve entrada no período)
    valor_unitario_ref = np.where(
        df["Custo_Medio_Compra"] > 0,
        df["Custo_Medio_Compra"],
        df["Preco_Medio_Venda"],
    )
    df["Valor_Estoque_Atual"] = (df["Saldo_Calculado"].clip(lower=0) * valor_unitario_ref).round(2)

    # 6. Curva ABC Financeira (prioriza Valor_Saidas; usa Total_Saidas como fallback)
    usar_financeiro = "Valor_Saidas" in df.columns and df["Valor_Saidas"].sum() > 0
    criterio_abc = "Valor_Saidas" if usar_financeiro else "Total_Saidas"

    df = df.sort_values(by=criterio_abc, ascending=False).reset_index(drop=True)
    total_geral = df[criterio_abc].sum()

    if total_geral > 0:
        df["Participacao_Pct"] = ((df[criterio_abc] / total_geral) * 100).round(2)
        df["Acumulado_Pct"] = df["Participacao_Pct"].cumsum().round(2)
        df["Curva_ABC"] = np.select(
            [df["Acumulado_Pct"] <= 80.0, df["Acumulado_Pct"] <= 95.0],
            ["A", "B"],
            default="C",
        )
    else:
        df["Participacao_Pct"] = 0.0
        df["Acumulado_Pct"] = 0.0
        df["Curva_ABC"] = "C"

    # 7. Diagnóstico de Status Operacional
    df["Status_Estoque"] = np.select(
        [
            df["Saldo_Calculado"] <= 0,
            df["Cobertura_Dias"] < cobertura_minima,
            (df["Cobertura_Dias"] > dias_excesso) & (df["Cobertura_Dias"] < 999.0),
            df["Cobertura_Dias"] == 999.0,
        ],
        [
            "🔴 Ruptura",
            "🟡 Atenção (Baixo)",
            "🔵 Excesso",
            "⚪ Sem Saída no Período",
        ],
        default="🟢 Saudável",
    )

    # 8. Sugestão de Compra para atingir a cobertura alvo (em dias)
    necessidade_bruta = (df["DMD"] * cobertura_alvo) - df["Saldo_Calculado"]
    df["Sugestao_Compra"] = np.where(
        necessidade_bruta > 0,
        np.ceil(necessidade_bruta),
        0.0,
    )

    return df


def renderizar_aba_indicadores():
    st.header("📊 Indicadores e Simulação de Estoque")
    st.caption(
        "Análise de giro, cobertura, Curva ABC financeira, dias sem venda e necessidade de reposição."
    )

    if "df_xml_consolidado" not in st.session_state or st.session_state["df_xml_consolidado"].empty:
        st.info(
            "Nenhum dado consolidado encontrado. Processe os arquivos XML na **Etapa 2** primeiro."
        )
        return

    df_consolidado = st.session_state["df_xml_consolidado"]
    df_movs = st.session_state.get("df_movs_detalhadas", pd.DataFrame())

    # 1. Parâmetros de Simulação
    with st.container(border=True):
        st.subheader("Parâmetros da Simulação")
        p1, p2, p3, p4 = st.columns(4)
        dias_periodo = p1.number_input(
            "Janela analisada (dias)",
            min_value=1,
            max_value=365,
            value=30,
            help="Quantidade de dias coberta pelos XMLs importados.",
        )
        cobertura_minima = p2.number_input(
            "Cobertura mínima / alerta (dias)",
            min_value=1,
            max_value=90,
            value=7,
            help="Abaixo deste limite o item entra em alerta de reposição.",
        )
        cobertura_alvo = p3.number_input(
            "Cobertura alvo de compra (dias)",
            min_value=1,
            max_value=180,
            value=15,
            help="Base de dias para calcular a sugestão de compra.",
        )
        dias_excesso = p4.number_input(
            "Limite para excesso (dias)",
            min_value=15,
            max_value=365,
            value=45,
            help="Acima deste limite o estoque é considerado excessivo.",
        )

    df_ind = calcular_indicadores_estoque(
        df_consolidado=df_consolidado,
        df_movs=df_movs,
        dias_periodo=int(dias_periodo),
        cobertura_minima=int(cobertura_minima),
        cobertura_alvo=int(cobertura_alvo),
        dias_excesso=int(dias_excesso),
    )

    # 2. Cards de Resumo Executivo
    st.subheader("Resumo Executivo")
    m1, m2, m3, m4, m5 = st.columns(5)

    faturamento_total = df_ind["Valor_Saidas"].sum()
    valor_estoque_total = df_ind["Valor_Estoque_Atual"].sum()
    qtd_ruptura = int((df_ind["Saldo_Calculado"] <= 0).sum())
    qtd_curva_a = int((df_ind["Curva_ABC"] == "A").sum())
    total_sugerido = int(df_ind["Sugestao_Compra"].sum())

    m1.metric("Faturamento (Saídas)", f"R$ {faturamento_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    m2.metric("Capital em Estoque", f"R$ {valor_estoque_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    m3.metric("Itens em Ruptura", f"{qtd_ruptura} SKU(s)")
    m4.metric("Curva A (80% Receita)", f"{qtd_curva_a} SKU(s)")
    m5.metric("Sugestão Total Compra", f"{total_sugerido} un.")

    # 3. Filtros Rápidos
    st.subheader("Detalhamento por Produto")
    f1, f2 = st.columns(2)
    filtro_curva = f1.multiselect(
        "Filtrar por Curva ABC:",
        options=["A", "B", "C"],
        default=["A", "B", "C"],
    )
    filtro_status = f2.multiselect(
        "Filtrar por Status de Estoque:",
        options=sorted(df_ind["Status_Estoque"].unique().tolist()),
        default=sorted(df_ind["Status_Estoque"].unique().tolist()),
    )

    df_filtrado = df_ind[
        df_ind["Curva_ABC"].isin(filtro_curva) & df_ind["Status_Estoque"].isin(filtro_status)
    ].copy()

    # Formatação amigável para exibição
    df_exibicao = df_filtrado.copy()
    df_exibicao["Cobertura_Exibicao"] = np.where(
        df_exibicao["Cobertura_Dias"] >= 999.0,
        "Sem giro (>30d)",
        df_exibicao["Cobertura_Dias"].astype(str) + " d",
    )
    df_exibicao["Dias_Sem_Giro_Exibicao"] = df_exibicao["Dias_Sem_Giro"].apply(
        lambda x: f"{int(x)} d" if pd.notna(x) else "Sem venda"
    )

    colunas_ordenadas = [
        "SKU",
        "Descrição",
        "Curva_ABC",
        "Status_Estoque",
        "Saldo_Calculado",
        "Total_Saidas",
        "Valor_Saidas",
        "Participacao_Pct",
        "DMD",
        "Cobertura_Exibicao",
        "Giro_Estoque",
        "Dias_Sem_Giro_Exibicao",
        "Ultima_Saida",
        "Sugestao_Compra",
    ]
    colunas_presentes = [c for c in colunas_ordenadas if c in df_exibicao.columns]

    st.dataframe(
        df_exibicao[colunas_presentes].rename(
            columns={
                "Curva_ABC": "Curva ABC",
                "Status_Estoque": "Status",
                "Saldo_Calculado": "Saldo Atual",
                "Total_Saidas": "Saídas (Qtd)",
                "Valor_Saidas": "Faturamento (R$)",
                "Participacao_Pct": "% Receita",
                "Cobertura_Exibicao": "Cobertura",
                "Giro_Estoque": "Giro",
                "Dias_Sem_Giro_Exibicao": "Dias s/ Giro",
                "Ultima_Saida": "Última Venda",
                "Sugestao_Compra": "Sugestão Compra",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    # 4. Evolução Diária de Saídas (se houver datas nos XMLs)
    if df_movs is not None and not df_movs.empty and "Data_Emissao" in df_movs.columns:
        df_saidas_dia = df_movs[
            (df_movs["Tipo"] == "Saída") & (df_movs["Data_Emissao"] != "")
        ].copy()
        if not df_saidas_dia.empty:
        st.subheader("Evolução Diária de Vendas (Saídas)")
        resumo_diario = (
        df_saidas_dia.groupby("Data_Emissao", as_index=False)["Quantidade"]
        .sum()
        .sort_values("Data_Emissao")
        )
        st.bar_chart(resumo_diario.set_index("Data_Emissao")["Quantidade"])
        # 5. Exportação do Relatório Completo de Indicadores
        data_hoje = datetime.now().strftime("%Y-%m-%d_%H-%M")
        csv_indicadores = df_filtrado.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button(
        label="📥 Baixar Relatório Completo de Indicadores (.CSV)",
        data=csv_indicadores,
        file_name=f"indicadores_estoque_{data_hoje}.csv",
        mime="text/csv",
        type="primary",
        use_container_width=True,
        )