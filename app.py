# Full Streamlit Portfolio Manager with Google Sheets Integration for Streamlit Cloud
# Updated to adjust for changes in secrets.toml

import streamlit as st
import gspread
import pandas as pd
from google.oauth2 import service_account

# Authenticate using Streamlit Cloud Secrets
if "gcp_service_account" not in st.secrets:
    st.error("❌ Missing GCP service account details. Add them under `[gcp_service_account]` in Streamlit Cloud secrets.")
else:
    credentials = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    )
    client = gspread.authorize(credentials)

    # Connect to Google Sheets
    try:
        google_sheet = client.open("Portfolio Manager")
        sheet = google_sheet.sheet1
    except Exception as e:
        st.error(f"Error connecting to Google Sheets: {e}")

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

    # Display Current Portfolios
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

st.info("Ensure your secrets.toml matches the updated format and is uploaded to Streamlit Cloud.")
