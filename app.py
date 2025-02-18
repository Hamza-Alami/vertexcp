import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# Authenticate with Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = ServiceAccountCredentials.from_json_keyfile_name('benificia-am-029ac0ca270c.json', scope)
client = gspread.authorize(credentials)

# Connect to Google Sheet
google_sheet = client.open("Portfolio Manager")
sheet = google_sheet.sheet1

# Load portfolios data from Google Sheets
def load_portfolios():
    data = sheet.get_all_records()
    return pd.DataFrame(data)

# Save a new portfolio
def save_portfolio(client_name, stock_name, quantity, strategy):
    sheet.append_row([client_name, stock_name, quantity, strategy])

# Delete a portfolio by client name
def delete_portfolio(client_name):
    records = sheet.get_all_records()
    for i, record in enumerate(records, start=2):
        if record['client_name'] == client_name:
            sheet.delete_rows(i)
            break

# Streamlit Interface
st.title("📊 Portfolio Manager")
portfolios = load_portfolios()
st.dataframe(portfolios)

# Add a new portfolio
with st.form("add_portfolio"):
    client_name = st.text_input("Client Name")
    stock_name = st.text_input("Stock Name")
    quantity = st.number_input("Quantity", min_value=0)
    strategy = st.text_input("Strategy")
    submitted = st.form_submit_button("Add Portfolio")

    if submitted:
        save_portfolio(client_name, stock_name, quantity, strategy)
        st.success("Portfolio added!")
        st.experimental_rerun()

# Delete a portfolio
with st.form("delete_portfolio"):
    client_to_delete = st.text_input("Client Name to Delete")
    delete_submitted = st.form_submit_button("Delete Portfolio")

    if delete_submitted:
        delete_portfolio(client_to_delete)
        st.success("Portfolio deleted!")
        st.experimental_rerun()

if st.button("Refresh Data"):
    st.experimental_rerun()
