import streamlit as st

st.set_page_config(layout="wide")

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
)

PAGES = {
    "Gestion des clients": page_manage_clients,
    "Créer portefeuille": page_create_portfolio,
    "Portefeuille (1 client)": page_view_client_portfolio,
    "Portefeuilles (tous)": page_view_all_portfolios,
    "Inventaire": page_inventory,
    "Marché": page_market,
    "Performance & Frais": page_performance_fees,
    "Stratégies & Simulation": page_strategies_and_simulation,
    "Reporting (PDF)": page_reporting,
}

st.sidebar.title("Navigation")
choice = st.sidebar.radio("Aller à :", list(PAGES.keys()))
PAGES[choice]()
