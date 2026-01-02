import streamlit as st

st.set_page_config(layout="wide", page_title="Benificiaam")

from pages import (
    page_manage_clients,
    page_create_portfolio,
    page_view_client_portfolio,
    page_view_all_portfolios,
    page_inventory,
    page_market,
    page_performance_fees,
    page_strategies_and_simulation,
    page_reporting,
    page_transactions_history,
    page_tpcvm_by_client,
)

with st.sidebar:
    # ✅ Logo (remets ton fichier au bon endroit)
    # Exemple: mets "logo.png" à la racine de benificiaam/
    try:
        st.image("Vertex.png", width=180)
    except Exception:
        st.markdown("### Benificiaam")

    st.markdown("---")

    # ✅ Selectbox (comme avant) au lieu de radio
    page = st.selectbox(
        "Menu",
        [
            "Gestion des Clients",
            "Création Portefeuille",
            "Portefeuille Client",
            "Tous les Portefeuilles",
            "Inventaire",
            "Marché",
            "Performance & Frais",
            "Stratégies & Simulation",
            "Rapport Client (PDF)",
            "Historique Transactions",
            "TPCVM par client",
        ],
        index=0,
    )

if page == "Gestion des Clients":
    page_manage_clients()
elif page == "Création Portefeuille":
    page_create_portfolio()
elif page == "Portefeuille Client":
    page_view_client_portfolio()
elif page == "Tous les Portefeuilles":
    page_view_all_portfolios()
elif page == "Inventaire":
    page_inventory()
elif page == "Marché":
    page_market()
elif page == "Performance & Frais":
    page_performance_fees()
elif page == "Stratégies & Simulation":
    page_strategies_and_simulation()
elif page == "Rapport Client (PDF)":
    page_reporting()
elif page == "Historique Transactions":
    page_transactions_history()
elif page == "TPCVM par client":
    page_tpcvm_by_client()
