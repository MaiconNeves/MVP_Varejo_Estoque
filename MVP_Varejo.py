import streamlit as st
from aba_coleta import renderizar_aba_coleta

st.set_page_config(page_title="MVP Coleta de Estoque", layout="wide")
st.title("Etapa 1: Coleta Física de Estoque")

# Inicializa o estado da sessão
if "itens_coletados" not in st.session_state:
    st.session_state.itens_coletados = {}
if "codigo_atual" not in st.session_state:
    st.session_state.codigo_atual = None
if "dados_api" not in st.session_state:
    st.session_state.dados_api = {}
if "aviso_duplicado" not in st.session_state:
    st.session_state.aviso_duplicado = None

# Renderiza a tela de coleta
renderizar_aba_coleta()

