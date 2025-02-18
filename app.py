import streamlit as st
import pandas as pd
import requests
from supabase import create_client
import json

# ✅ Connect to Supabase
supabase_url = st.secrets["supabase"]["url"]
supabase_key = st.secrets["supabase"]["key"]
client = create_client(supabase_url, supabase_key)

# ✅ Fetch Stocks from ID Bourse API and Save to Supabase
@st.cache_data
def get_stock_data():
    url = "https://backend.idbourse.com/api_2/get_all_data"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        stocks = pd.DataFrame(data)[['name', 'dernier_cours']]
        stocks.loc[len(stocks)] = ['CASH', 1.0]
        # Save stocks to Supabase
        for _, row in stocks.iterrows():
            client.table("stocks").upsert({
                "name": row["name"],
                "dernier_cours": row["dernier_cours"]
            }).execute()
        return stocks
    else:
        st.error("Failed to fetch stock data.")
        return pd.DataFrame()

stocks = get_stock_data()

# ✅ Create a Client
def create_client(name):
    client.table('clients').insert({"name": name}).execute()
    client.table('portfolios').insert({
        "client_name": name,
        "name": "CASH",
        "quantity": 0,
        "value": 0,
        "cash": 0
    }).execute()

# ✅ Delete a Client
def delete_client(name):
    client.table('clients').delete().eq("name", name).execute()

# ✅ Display Portfolios
def display_portfolios(selected_clients):
    query = client.table('portfolios').select("*").execute()
    df = pd.DataFrame(query.data)
    filtered = df[df['client_name'].isin(selected_clients)]
    st.dataframe(filtered)

# ✅ Add Stock to Portfolio
def add_stock_to_portfolio(client_name, stock_name, quantity):
    stock_price = stocks.loc[stocks['name'] == stock_name, 'dernier_cours'].values[0]
    value = stock_price * quantity
    client.table('portfolios').insert({
        "client_name": client_name,
        "name": stock_name,
        "quantity": quantity,
        "value": value,
        "cash": 0
    }).execute()

# ✅ Streamlit UI with Sidebar Navigation
page = st.sidebar.selectbox("📂 Select Page", ["Clients", "Cours (Stocks)", "Portfolios", "Inventaire"])

# ✅ Clients Page
if page == "Clients":
    st.title("👥 Manage Clients")
    with st.form("add_client"):
        client_name = st.text_input("Client Name")
        if st.form_submit_button("➕ Add Client"):
            create_client(client_name)
            st.success(f"Client '{client_name}' created!")
            st.experimental_rerun()

    with st.form("delete_client"):
        client_name_to_delete = st.text_input("Client to Delete")
        if st.form_submit_button("❌ Delete Client"):
            delete_client(client_name_to_delete)
            st.success(f"Client '{client_name_to_delete}' deleted!")
            st.experimental_rerun()

    # Show All Clients
    all_clients = [c['name'] for c in client.table('clients').select('name').execute().data]
    st.write("### All Clients")
    st.write(all_clients)

# ✅ Cours (Stocks) Page
elif page == "Cours (Stocks)":
    st.title("📈 Cours des Actions")
    st.dataframe(stocks[['name', 'dernier_cours']])

# ✅ Portfolios Page
elif page == "Portfolios":
    st.title("💼 Client Portfolios")
    all_clients = [c['name'] for c in client.table('clients').select('name').execute().data]

    selected_clients = st.multiselect("Select Clients", all_clients)
    if st.button("Show Portfolios"):
        display_portfolios(selected_clients)

    with st.form("add_stock_to_portfolio"):
        client_name = st.selectbox("Select Client", all_clients)
        stock_name = st.selectbox("Select Stock", stocks["name"].tolist())
        quantity = st.number_input("Quantity", min_value=1)
        if st.form_submit_button("➕ Add Stock"):
            add_stock_to_portfolio(client_name, stock_name, quantity)
            st.success(f"Stock '{stock_name}' added to '{client_name}' portfolio!")
            st.experimental_rerun()

# ✅ Inventaire Page
elif page == "Inventaire":
    st.title("📊 Inventaire Global")
    query = client.table('portfolios').select("*").execute()
    df = pd.DataFrame(query.data)
    inventory = df.groupby("name").agg({"quantity": "sum"}).reset_index()
    inventory.loc[inventory["name"] == "CASH", "quantity"] = df["cash"].sum()
    st.dataframe(inventory)
