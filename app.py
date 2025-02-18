# 📊 Streamlit Portfolio Manager with Supabase Integration
# Full Version with Stock Management and Client Portfolios

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
    try:
        response = requests.get("https://backend.idbourse.com/api_2/get_all_data", timeout=10)
        response.raise_for_status()
        data = response.json()
        return pd.DataFrame([(s.get('name', 'N/A'), s.get('dernier_cours', 0)) for s in data], columns=['name', 'dernier_cours'])
    except Exception as e:
        st.error(f"Failed to fetch stock data: {e}")
        return pd.DataFrame(columns=["name", "dernier_cours"])

stocks = get_stock_data()

# ✅ Add Client
def add_client(client_name):
    client.table('clients').insert({"name": client_name}).execute()

# ✅ Delete Client
def delete_client(client_name):
    client.table('clients').delete().eq('name', client_name).execute()

# ✅ Get Client List
@st.cache_data
def get_client_list():
    query = client.table('clients').select("name").execute()
    return [c['name'] for c in query.data] if query.data else []

# ✅ Add Stock to Client Portfolio
def add_stock_to_portfolio(client_name, stock_name, quantity):
    stock_price = stocks.loc[stocks['name'] == stock_name, 'dernier_cours'].values[0]
    value = quantity * stock_price
    client.table('portfolios').insert({
        "client_name": client_name,
        "stock_name": stock_name,
        "quantity": quantity,
        "value": value,
        "cash": 0
    }).execute()

# ✅ Update Client Cash
def update_client_cash(client_name, cash):
    client.table('portfolios').update({"cash": cash}).eq("client_name", client_name).execute()

# ✅ Show Client Portfolio
def show_client_portfolio(client_name):
    query = client.table('portfolios').select("*").eq("client_name", client_name).execute()
    df = pd.DataFrame(query.data)
    if not df.empty:
        df['total_value'] = df['quantity'] * df['value'] + df['cash']
        st.dataframe(df)
        total = df['total_value'].sum()
        st.write(f"### 💰 Total Portfolio Value: {total:.2f}")
    else:
        st.write("No stocks found for this client.")

# ✅ Show Inventory
def show_inventory():
    query = client.table('portfolios').select("stock_name, quantity").execute()
    df = pd.DataFrame(query.data)
    if not df.empty:
        inventory = df.groupby("stock_name")["quantity"].sum().reset_index()
        st.dataframe(inventory)
    else:
        st.write("No inventory data available.")

# ✅ Streamlit UI with Sidebar Navigation
page = st.sidebar.selectbox("📂 Select Page", ["Clients", "Cours (Stocks)", "Inventaire"])

if page == "Clients":
    st.title("👤 Manage Clients")
    
    # Add Client
    client_name = st.text_input("Enter Client Name")
    if st.button("➕ Add Client"):
        add_client(client_name)
        st.success(f"Client '{client_name}' added!")
    
    # Delete Client
    clients = get_client_list()
    if clients:
        client_to_delete = st.selectbox("Select Client to Delete", clients)
        if st.button("🗑 Delete Client"):
            delete_client(client_to_delete)
            st.success(f"Client '{client_to_delete}' deleted!")
    else:
        st.write("No clients found.")
    
    # Manage Portfolios
    client_selected = st.selectbox("Select Client for Portfolio", get_client_list())
    if client_selected:
        # Add Stocks
        with st.form("add_stock_form"):
            stock_name = st.selectbox("Select Stock", stocks["name"].tolist())
            quantity = st.number_input("Quantity", min_value=1, step=1)
            if st.form_submit_button("➕ Add Stock to Portfolio"):
                add_stock_to_portfolio(client_selected, stock_name, quantity)
                st.success(f"{quantity} shares of {stock_name} added to {client_selected}'s portfolio.")

        # Manage Cash
        cash = st.number_input("💰 Update Cash", value=0, step=100)
        if st.button("💾 Save Cash"):
            update_client_cash(client_selected, cash)
            st.success(f"Cash updated to {cash} for {client_selected}.")

        # View Portfolio
        show_client_portfolio(client_selected)

elif page == "Cours (Stocks)":
    st.title("📈 Stock Prices from ID Bourse")
    st.dataframe(stocks)

elif page == "Inventaire":
    st.title("📊 Global Portfolio Inventory")
    show_inventory()
