from datetime import datetime
import io
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st


def _strip_ns(tag: str) -> str:
    """Remove o namespace XML da tag (ex: {http://www.portalfiscal.inf.br/nfe}infNFe -> infNFe)."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find_child(elem, tag_name: str):
    """Busca o primeiro filho direto correspondente ao nome da tag sem namespace."""
    if elem is None:
        return None
    for child in elem:
        if _strip_ns(child.tag) == tag_name:
            return child
    return None


def _get_text(elem, tag_name: str, default: str = "") -> str:
    """Retorna o texto de uma subtag direta ou valor padrão."""
    child = _find_child(elem, tag_name)
    if child is not None and child.text:
        return child.text.strip()
    return default


def _normalizar_sku(valor: str) -> str:
    """Normaliza o SKU para comparação consistente (remove espaços e zeros à esquerda opcionais)."""
    texto = str(valor).strip()
    return texto.lstrip("0") or texto


def processar_arquivo_xml(arquivo_xml, skus_monitorados_map: dict, cnpj_loja: str = ""):
    """
    Lê um arquivo XML de NF-e (modelo 55) ou NFC-e (modelo 65) e extrai
    as movimentações dos SKUs presentes na lista monitorada.
    """
    movimentacoes = []
    try:
        conteudo = arquivo_xml.read()
        root = ET.fromstring(conteudo)
    except Exception as e:
        return [], f"Erro ao ler XML '{arquivo_xml.name}': {e}"

    inf_nfe = None
    for elem in root.iter():
        if _strip_ns(elem.tag) == "infNFe":
            inf_nfe = elem
            break

    if inf_nfe is None:
        return [], None

    ide = _find_child(inf_nfe, "ide")
    emit = _find_child(inf_nfe, "emit")
    dest = _find_child(inf_nfe, "dest")

    modelo = _get_text(ide, "mod")  # '55' = NF-e, '65' = NFC-e
    tp_nf = _get_text(ide, "tpNF")  # '0' = Entrada, '1' = Saída (na visão do emitente)
    fin_nfe = _get_text(ide, "finNFe")  # '1' = Normal, '4' = Devolução

    cnpj_emit = "".join(filter(str.isdigit, _get_text(emit, "CNPJ")))
    cnpj_dest = "".join(filter(str.isdigit, _get_text(dest, "CNPJ")))
    cnpj_loja_limpo = "".join(filter(str.isdigit, cnpj_loja))

    if cnpj_loja_limpo:
        if cnpj_dest == cnpj_loja_limpo and cnpj_emit != cnpj_loja_limpo:
            tipo_mov = "Entrada"
        elif cnpj_emit == cnpj_loja_limpo:
            tipo_mov = "Entrada" if tp_nf == "0" or fin_nfe == "4" else "Saída"
        else:
            tipo_mov = "Entrada" if (modelo == "55" and tp_nf == "1") else "Saída"
    else:
        if modelo == "65":
            tipo_mov = "Entrada" if fin_nfe == "4" else "Saída"
        else:
            tipo_mov = "Entrada"

    for elem in inf_nfe:
        if _strip_ns(elem.tag) != "det":
            continue

        prod = _find_child(elem, "prod")
        if prod is None:
            continue

        c_prod = _get_text(prod, "cProd")
        sku_norm = _normalizar_sku(c_prod)

        sku_chave_original = None
        if c_prod in skus_monitorados_map:
            sku_chave_original = c_prod
        elif sku_norm in skus_monitorados_map:
            sku_chave_original = skus_monitorados_map[sku_norm]

        if not sku_chave_original:
            continue

        try:
            qtd = float(_get_text(prod, "qCom", "0").replace(",", "."))
        except ValueError:
            qtd = 0.0

        movimentacoes.append(
            {
                "SKU": sku_chave_original,
                "Tipo": tipo_mov,
                "Quantidade": qtd,
            }
        )

    return movimentacoes, None


def renderizar_aba_xml():
    st.header("📄 Processamento de XMLs (NF-e 55 e NFC-e 65)")
    st.caption(
        "Cruza a base de itens coletados (por SKU) com os XMLs de entrada e saída para consolidar o saldo."
    )

    # 1. Carregamento da base inicial de itens coletados (sessão atual ou upload de CSV)
    st.subheader("1. Base de SKUs Monitorados")
    fonte_base = st.radio(
        "Origem da lista de produtos:",
        options=[
            "Usar itens coletados na sessão atual",
            "Enviar planilha CSV exportada anteriormente",
        ],
        horizontal=True,
    )

    df_base = None

    if fonte_base == "Usar itens coletados na sessão atual":
        itens_sessao = st.session_state.get("itens_coletados", {})
        if itens_sessao:
            df_base = pd.DataFrame(list(itens_sessao.values()))
            if "EAN" in df_base.columns and "SKU" not in df_base.columns:
                df_base = df_base.rename(columns={"EAN": "SKU"})
            st.success(f"Base ativa carregada com **{len(df_base)}** SKU(s) da sessão.")
        else:
            st.warning(
                "Nenhum item coletado na sessão atual. Colete itens na primeira aba ou envie um arquivo CSV."
            )
    else:
        arquivo_csv = st.file_uploader(
            "Selecione o arquivo .CSV da coleta",
            type=["csv"],
            key="upload_csv_base_xml",
        )
        if arquivo_csv is not None:
            try:
                conteudo_bytes = arquivo_csv.read()
                texto_csv = conteudo_bytes.decode("utf-8-sig")
                separador = ";" if ";" in texto_csv.splitlines()[0] else ","
                df_base = pd.read_csv(io.StringIO(texto_csv), sep=separador, dtype=str)

                if "EAN" in df_base.columns and "SKU" not in df_base.columns:
                    df_base = df_base.rename(columns={"EAN": "SKU"})

                if "Qtd Física" in df_base.columns:
                    df_base["Qtd Física"] = (
                        df_base["Qtd Física"].str.replace(",", ".").astype(float)
                    )
                else:
                    df_base["Qtd Física"] = 0.0

                st.success(f"CSV carregado com **{len(df_base)}** SKU(s).")
            except Exception as e:
                st.error(f"Erro ao ler o arquivo CSV: {e}")

    if df_base is None or df_base.empty:
        return

    with st.expander("Visualizar SKUs monitorados", expanded=False):
        st.dataframe(df_base, use_container_width=True)

    # 2. Upload múltiplo dos arquivos XML
    st.subheader("2. Upload dos Arquivos XML (NF-e e NFC-e)")
    cnpj_loja = st.text_input(
        "CNPJ da Loja (opcional — ajuda a distinguir compras de vendas em NF-e modelo 55)",
        placeholder="Ex: 12.345.678/0001-99 (deixe vazio para considerar NF-e 55 = Entrada e NFC-e 65 = Saída)",
    )

    arquivos_xml = st.file_uploader(
        "Selecione um ou mais arquivos .XML",
        type=["xml"],
        accept_multiple_files=True,
        key="upload_multiplos_xml",
    )

    if not arquivos_xml:
        return

    # 3. Processamento e consolidação
    if st.button("⚙️ Processar XMLs e Gerar Consolidado", type="primary", use_container_width=True):
        skus_map = {}
        for sku_val in df_base["SKU"].astype(str):
            sku_limpo = sku_val.strip()
            skus_map[sku_limpo] = sku_limpo
            skus_map[_normalizar_sku(sku_limpo)] = sku_limpo

        todas_movs = []
        avisos = []

        with st.spinner(f"Processando {len(arquivos_xml)} arquivo(s) XML..."):
            for arq in arquivos_xml:
                movs, erro = processar_arquivo_xml(arq, skus_map, cnpj_loja)
                if erro:
                    avisos.append(erro)
                todas_movs.extend(movs)

        for aviso in avisos:
            st.warning(aviso)

        df_movs = pd.DataFrame(todas_movs)

        df_resultado = df_base.copy()
        df_resultado["SKU"] = df_resultado["SKU"].astype(str).str.strip()

        if not df_movs.empty:
            entradas = (
                df_movs[df_movs["Tipo"] == "Entrada"]
                .groupby("SKU")["Quantidade"]
                .sum()
                .rename("Total_Entradas")
            )
            saidas = (
                df_movs[df_movs["Tipo"] == "Saída"]
                .groupby("SKU")["Quantidade"]
                .sum()
                .rename("Total_Saidas")
            )

            df_resultado = df_resultado.merge(entradas, on="SKU", how="left")
            df_resultado = df_resultado.merge(saidas, on="SKU", how="left")
        else:
            df_resultado["Total_Entradas"] = 0.0
            df_resultado["Total_Saidas"] = 0.0
            st.info("Nenhuma movimentação encontrada nos XMLs enviados para os SKUs da lista.")

        df_resultado["Total_Entradas"] = df_resultado["Total_Entradas"].fillna(0.0)
        df_resultado["Total_Saidas"] = df_resultado["Total_Saidas"].fillna(0.0)

        col_qtd_inicial = "Qtd Física" if "Qtd Física" in df_resultado.columns else "Qtd_Inicial"
        if col_qtd_inicial not in df_resultado.columns:
            df_resultado[col_qtd_inicial] = 0.0

        df_resultado["Saldo_Calculado"] = (
            df_resultado[col_qtd_inicial]
            + df_resultado["Total_Entradas"]
            - df_resultado["Total_Saidas"]
        )

        st.session_state["df_xml_consolidado"] = df_resultado

    # 4. Exibição do consolidado e exportação CSV
    if "df_xml_consolidado" in st.session_state:
        df_res = st.session_state["df_xml_consolidado"]

        st.subheader("3. Consolidado de Entradas e Saídas por SKU")
        st.dataframe(df_res, use_container_width=True)

        data_hoje = datetime.now().strftime("%Y-%m-%d_%H-%M")
        csv_consolidado = df_res.to_csv(index=False, sep=";").encode("utf-8-sig")

        st.download_button(
            label="📥 Baixar Consolidado de Estoque (.CSV)",
            data=csv_consolidado,
            file_name=f"estoque_consolidado_xml_{data_hoje}.csv",
            mime="text/csv",
            type="primary",
            use_container_width=True,
        )
