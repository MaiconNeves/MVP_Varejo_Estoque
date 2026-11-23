import requests
import streamlit as st

@st.cache_data(ttl=3600)
def buscar_dados_mestres(ean: str) -> dict:
    ean_limpo = "".join(filter(str.isdigit, str(ean)))
    headers = {"User-Agent": "MVPInteligenciaVarejo/1.0"}

    # 1. Busca gratuita: Open Food Facts e Open Beauty Facts
    for dominio in ["world.openfoodfacts.org", "world.openbeautyfacts.org"]:
        try:
            r = requests.get(
                f"https://{dominio}/api/v2/product/{ean_limpo}.json",
                headers=headers,
                timeout=5,
            )
            if r.status_code == 200 and r.json().get("status") == 1:
                p = r.json().get("product", {})
                nome = (
                    p.get("product_name_pt")
                    or p.get("product_name")
                    or p.get("generic_name")
                )
                if nome:
                    return {
                        "descricao": nome,
                        "marca": p.get("brands", ""),
                        "ncm": "",
                        "unidade": p.get("quantity", "UN"),
                    }
        except Exception:
            pass

    # 2. Fallback gratuito: UPCitemdb
    try:
        r = requests.get(
            f"https://upcitemdb.com{ean_limpo}",
            headers=headers,
            timeout=5,
        )
        if r.status_code == 200:
            itens = r.json().get("items", [])
            if itens:
                item = itens[0]
                return {
                    "descricao": item.get("title", ""),
                    "marca": item.get("brand", ""),
                    "ncm": "",
                    "unidade": item.get("size", "UN") or "UN",
                }
    except Exception:
        pass

    return {"descricao": "", "marca": "", "ncm": "", "unidade": "UN"}
