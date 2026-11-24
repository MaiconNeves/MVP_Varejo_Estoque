import streamlit as st
from aba_coleta import renderizar_aba_coleta
from aba_entradas_saidas import renderizar_aba_xml
from aba_indicadores import renderizar_aba_indicadores

st.set_page_config(page_title="MVP Coleta de Estoque", layout="wide")
st.title("MVP Varejo - Controle e Inteligência de Estoque")

# Inicializa o estado da sessão
if "itens_coletados" not in st.session_state:
    st.session_state.itens_coletados = {}
if "codigo_atual" not in st.session_state:
    st.session_state.codigo_atual = None
if "dados_api" not in st.session_state:
    st.session_state.dados_api = {}
if "aviso_duplicado" not in st.session_state:
    st.session_state.aviso_duplicado = None

# Divide as etapas em abas
aba1, aba2, aba3 = st.tabs([
    "Etapa 1: Coleta Física de Estoque",
    "Etapa 2: Entradas e Saídas (XML)",
    "Etapa 3: Indicadores e Simulação",
])

with aba1:
    renderizar_aba_coleta()

with aba2:
    renderizar_aba_xml()

with aba3:
    renderizar_aba_indicadores()


