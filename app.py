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
            "Manage Clients",
            "Create Portfolio",
            "View Client Portfolio",
            "View All Portfolios",
            "Inventory",
            "Market",
            "Performance & Fees"  # Add new
        ]
    )
    if page == "Manage Clients":
        page_manage_clients()
    elif page == "Create Portfolio":
        page_create_portfolio()
    elif page == "View Client Portfolio":
        page_view_client_portfolio()
    elif page == "View All Portfolios":
        page_view_all_portfolios()
    elif page == "Inventory":
        page_inventory()
    elif page == "Market":
        page_market()
    elif page == "Performance & Fees":
        page_performance_fees()  # call new function

if __name__ == "__main__":
    main()
