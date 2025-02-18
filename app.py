import streamlit as st
import pandas as pd
import requests
from supabase import create_client

# Connect to Supabase
supabase_url = st.secrets["supabase"]["url"]
supabase_key = st.secrets["supabase"]["key"]
client = create_client(supabase_url, supabase_key)

# Fetch Stock Data from ID Bourse API
@st.cache_data
def get_stock_data():
    response = requests.get("https://backend.idbourse.com/api_2/get_all_data")
    data = response.json()
    df = pd.DataFrame(data)
    return df[['name', 'dernier_cours']]

stocks = get_stock_data()

# Display Stocks
st.sidebar.header("📈 Stock Prices")
st.sidebar.dataframe(stocks)

# Manage Clients and Portfolios
st.title("👤 Client Portfolio Manager")

with st.form("add_client"):
    client_name = st.text_input("New Client Name")
    if st.form_submit_button("Add Client"):
        client.table('clients').insert({"name": client_name}).execute()
        st.success(f"Client '{client_name}' added!")
        st.experimental_rerun()

# Show All Clients
all_clients = [c['name'] for c in client.table('clients').select('name').execute().data]
selected_client = st.selectbox("Select Client", all_clients)

# Add Stock to Portfolio
with st.form("add_stock"):
    stock_name = st.selectbox("Select Stock", stocks['name'].tolist())
    quantity = st.number_input("Quantity", min_value=1, step=1)
    if st.form_submit_button("Add to Portfolio"):
        price = stocks.loc[stocks['name'] == stock_name, 'dernier_cours'].values[0]
        value = quantity * price
        client.table('portfolios').insert({
            "client_id": selected_client,
            "name": stock_name,
            "quantity": quantity,
            "value": value
        }).execute()
        st.success(f"Added {quantity} shares of {stock_name}")
        st.experimental_rerun()

# View Client Portfolio
if selected_client:
    portfolio = pd.DataFrame(client.table('portfolios').select('*').eq('client_id', selected_client).execute().data)
    st.write(f"### Portfolio of {selected_client}")
    st.dataframe(portfolio[['name', 'quantity', 'value']])
