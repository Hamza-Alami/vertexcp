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
        return pd.DataFrame([(s['name'], s['dernier_cours']) for s in data], columns=["name", "dernier_cours"])
    except Exception as e:
        st.error(f"Error fetching stock data: {e}")
        return pd.DataFrame(columns=["name", "dernier_cours"])

stocks = get_stock_data()

# ✅ Create Client
def create_client(name):
    client.table('clients').insert({"name": name}).execute()

# ✅ Add Stock to Portfolio
def add_stock_to_portfolio(client_name, stock_name, quantity):
    client_id = get_client_id(client_name)
    if not client_id:
        st.error("Client not found.")
        return

    # Check if stock already exists
    existing_stock = client.table('portfolios').select("*").eq('client_id', client_id).eq('stock_name', stock_name).execute()
    if existing_stock.data:
        # Update existing quantity
        new_quantity = existing_stock.data[0]['quantity'] + quantity
        client.table('portfolios').update({"quantity": new_quantity}).eq('id', existing_stock.data[0]['id']).execute()
    else:
        # Insert new stock
        price = stocks.loc[stocks['name'] == stock_name, 'dernier_cours'].values[0]
        client.table('portfolios').insert({
            "client_id": client_id,
            "stock_name": stock_name,
            "quantity": quantity,
            "value": price * quantity
        }).execute()

# ✅ Get Client ID
def get_client_id(client_name):
    result = client.table('clients').select('id').eq('name', client_name).execute()
    if result.data:
        return result.data[0]['id']
    return None

# ✅ Show Single Portfolio
def show_portfolio(client_name):
    client_id = get_client_id(client_name)
    if not client_id:
        st.error("Client not found.")
        return

    query = client.table('portfolios').select("*").eq('client_id', client_id).execute()
    df = pd.DataFrame(query.data)

    # Display Client Name
    st.subheader(f"📜 Portfolio for {client_name}")

    # Add Cash Row
    cash_row = pd.DataFrame([{"stock_name": "CASH", "quantity": 1, "value": df["value"].sum()}])
    df = pd.concat([df, cash_row], ignore_index=True)

    # Rename Columns
    df = df.rename(columns={
        "stock_name": "valeur",
        "quantity": "quantité",
        "value": "valorisation"
    })

    # Remove Unnecessary Columns
    df = df[["valeur", "quantité", "valorisation"]]

    # Inline Editing of Portfolio
    edited_portfolio = st.data_editor(df, key="portfolio_editor", num_rows="dynamic")

    # Total Portfolio Value
    total_value = edited_portfolio["valorisation"].sum()
    st.subheader(f"💰 Valorisation totale du portefeuille: {total_value:.2f}")

    return edited_portfolio

# ✅ Show All Clients' Portfolios
def show_all_portfolios():
    clients = client.table('clients').select("*").execute().data
    for c in clients:
        show_portfolio(c['name'])

# ✅ Streamlit UI with Sidebar
page = st.sidebar.selectbox("📂 Select Page", ["Clients", "Cours (Stocks)", "Single Portfolio", "All Portfolios"])

if page == "Clients":
    st.title("👤 Manage Clients")
    client_name = st.text_input("Client Name")
    if st.button("➕ Add Client"):
        create_client(client_name)
        st.success(f"Client '{client_name}' added!")

elif page == "Cours (Stocks)":
    st.title("📈 Stock Prices")
    st.dataframe(stocks)

elif page == "Single Portfolio":
    st.title("📜 Client Portfolio")
    client_name = st.text_input("Enter Client Name")
    if st.button("🔍 Show Portfolio"):
        show_portfolio(client_name)

elif page == "All Portfolios":
    st.title("📊 All Clients' Portfolios")
    show_all_portfolios()
