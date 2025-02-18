# 📊 Streamlit Portfolio Manager with Supabase Integration
# Full Corrected Code Including Stock Management and Inventory View

import streamlit as st
import pandas as pd
from supabase import create_client
import requests

# ✅ Connect to Supabase
supabase_url = st.secrets["supabase"]["url"]
supabase_key = st.secrets["supabase"]["key"]
client = create_client(supabase_url, supabase_key)

# ✅ Fetch Stocks from ID Bourse API
@st.cache_data
def get_stock_data():
    response = requests.get("https://api.idbourse.com/stocks")
    if response.status_code == 200:
        data = response.json()
        return pd.DataFrame([(s['name'], s['dernier_cours']) for s in data], columns=['name', 'dernier_cours'])
    return pd.DataFrame(columns=["name", "dernier_cours"])

stocks = get_stock_data()

# ✅ Add Stock to Portfolio
def add_stock_to_portfolio(client_name, stock_name, quantity):
    price = stocks.loc[stocks['name'] == stock_name, 'dernier_cours'].values[0]
    value = price * quantity
    client.table('portfolios').insert({
        "client_name": client_name,
        "stock_name": stock_name,
        "quantity": quantity,
        "value": value,
        "cash": 0
    }).execute()

# ✅ Display Portfolio Inventory
def show_inventory():
    query = client.table('portfolios').select("*").execute()
    df = pd.DataFrame(query.data)
    if "stock_name" in df.columns:
        inventory = df.groupby("stock_name")["quantity"].sum().reset_index()
        st.write("### 📊 Global Inventory")
        st.dataframe(inventory)
    else:
        st.error("'stock_name' column missing. Verify Supabase table.")

# ✅ Streamlit UI
st.sidebar.title("📂 Navigation")
page = st.sidebar.selectbox("Choose Page", ["Clients", "Cours (Stocks)", "Inventaire"])

if page == "Clients":
    st.title("👤 Manage Clients")
    client_name = st.text_input("Client Name")
    if st.button("➕ Add Client"):
        client.table('clients').insert({"name": client_name}).execute()
        st.success(f"Client '{client_name}' added!")

elif page == "Cours (Stocks)":
    st.title("📈 Stock Prices")
    st.dataframe(stocks)

elif page == "Inventaire":
    show_inventory()
