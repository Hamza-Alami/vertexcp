# 📊 Streamlit Portfolio Manager with Supabase Integration (Full Code)
import streamlit as st
import pandas as pd
from supabase import create_client
import requests

# ✅ Supabase Connection
supabase_url = st.secrets["supabase"]["url"]
supabase_key = st.secrets["supabase"]["key"]
client = create_client(supabase_url, supabase_key)

# ✅ Fetch Stocks from ID Bourse API
@st.cache_data
def get_stock_data():
    try:
        response = requests.get("https://api.idbourse.com/stocks", timeout=10)
        response.raise_for_status()
        data = response.json()
        return pd.DataFrame([(s.get('name', 'N/A'), s.get('dernier_cours', 0)) for s in data], columns=['name', 'dernier_cours'])
    except Exception as e:
        st.error(f"Stock data error: {e}")
        return pd.DataFrame(columns=["name", "dernier_cours"])

stocks = get_stock_data()

# ✅ Display Portfolio Inventory
@st.cache_data
def show_inventory():
    query = client.table('portfolios').select("client_name, stock_name, quantity, value, cash").execute()
    df = pd.DataFrame(query.data)
    if not df.empty and "stock_name" in df.columns:
        inventory = df.groupby("stock_name")["quantity"].sum().reset_index()
        st.subheader("📊 Global Inventory")
        st.dataframe(inventory)
    else:
        st.warning("No portfolio data found.")

# ✅ Streamlit UI
page = st.sidebar.selectbox("📂 Choose Page", ["Clients", "Cours (Stocks)", "Inventaire"])

if page == "Clients":
    st.header("👤 Manage Clients")
    client_name = st.text_input("Client Name")
    if st.button("➕ Add Client"):
        client.table('clients').insert({"name": client_name}).execute()
        st.success(f"Client '{client_name}' added!")

elif page == "Cours (Stocks)":
    st.header("📈 Stock Prices")
    st.dataframe(stocks)

elif page == "Inventaire":
    show_inventory()
