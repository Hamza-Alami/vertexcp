# Full Streamlit Portfolio Manager with Google Sheets Integration for Streamlit Cloud
# Adjusted to resolve secrets.toml detection issue

import streamlit as st
import gspread
import pandas as pd
from google.oauth2 import service_account

# Debugging Secret Detection
st.write("🔑 Checking for GCP service account credentials...")
st.write(f"Secrets keys found: {list(st.secrets.keys())}")

# Authenticate using Streamlit Cloud Secrets
if "gcp_service_account" not in st.secrets:
    st.error("❌ GCP credentials not found. Ensure '[gcp_service_account]' is correctly defined in Streamlit Cloud secrets.")
else:
    try:
        credentials = service_account.Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]),
            scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        )
        client = gspread.authorize(credentials)
        google_sheet = client.open("Portfolio Manager")
        sheet = google_sheet.sheet1
    except Exception as e:
        st.error(f"⚠️ Google Sheets connection error: {e}")
        st.stop()

    # Load Portfolios Data
    def load_portfolios():
        try:
            data = sheet.get_all_records()
            return pd.DataFrame(data) if data else pd.DataFrame(columns=["client_name", "stock_name", "quantity", "strategy"])
        except Exception as e:
            st.error(f"Failed to load data: {e}")
            return pd.DataFrame(columns=["client_name", "stock_name", "quantity", "strategy"])

    # Save Portfolio Entry
    def save_portfolio(client_name, stock_name, quantity, strategy):
        try:
            sheet.append_row([client_name, stock_name, quantity, strategy])
        except Exception as e:
            st.error(f"Failed to save portfolio: {e}")

    # Delete Portfolio by Client Name
    def delete_portfolio(client_name):
        records = sheet.get_all_records()
        for i, record in enumerate(records, start=2):
            if record.get('client_name') == client_name:
                try:
                    sheet.delete_rows(i)
                    st.success(f"Portfolio for '{client_name}' deleted.")
                    break
                except Exception as e:
                    st.error(f"Failed to delete portfolio: {e}")

    # Streamlit App UI
    st.title("📊 Portfolio Manager")

    portfolios = load_portfolios()
    st.dataframe(portfolios)

    # Add Portfolio Form
    with st.form("add_portfolio"):
        client_name = st.text_input("Client Name")
        stock_name = st.text_input("Stock Name")
        quantity = st.number_input("Quantity", min_value=0, step=1)
        strategy = st.text_input("Strategy")
        if st.form_submit_button("Add Portfolio"):
            save_portfolio(client_name, stock_name, quantity, strategy)
            st.success("Portfolio added successfully!")
            st.experimental_rerun()

    # Delete Portfolio Form
    with st.form("delete_portfolio"):
        client_to_delete = st.text_input("Client Name to Delete")
        if st.form_submit_button("Delete Portfolio"):
            delete_portfolio(client_to_delete)
            st.experimental_rerun()

    # Refresh Button
    if st.button("Refresh Data"):
        st.experimental_rerun()

st.info("✅ Ensure that `secrets.toml` is uploaded and structured correctly. If issues persist, verify that Streamlit Cloud has `[gcp_service_account]` defined under `Settings > Secrets`.")
