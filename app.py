# app.py (assuming you have the same structure)
import streamlit as st
from pages import (
    page_manage_clients,
    page_create_portfolio,
    page_view_client_portfolio,
    page_view_all_portfolios,
    page_inventory,
    page_market,
    page_performance_fees  # new import
)

def main():
    page = st.sidebar.selectbox(
        "📂 Navigation",
        [
            "Gestion des clients",
            "Créer un Portefeuille",
            "Gérer un Portefeuille",
            "Voir tout les portefeuilles",
            "Inventaire",
            "Marché",
            "Performance & Fees"  # Add new
        ]
    )
    if page == "Gestion des clients":
        page_manage_clients()
    elif page == "Créer un Portefeuille":
        page_create_portfolio()
    elif page == "Gérer un Portefeuille":
        page_view_client_portfolio()
    elif page == "Voir tout les portefeuilles":
        page_view_all_portfolios()
    elif page == "Inventaire":
        page_inventory()
    elif page == "Marché":
        page_market()
    elif page == "Performance & Fees":
        page_performance_fees()  # call new function

if __name__ == "__main__":
    main()
