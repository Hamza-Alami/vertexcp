import streamlit as st
import pandas as pd
from supabase import create_client
import requests

# ✅ Connect to Supabase
supabase_url = st.secrets["supabase"]["url"]
supabase_key = st.secrets["supabase"]["key"]
client = create_client(supabase_url, supabase_key)

# ✅ Fetch Stocks from Correct API
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

# ✅ Create Client with Duplicate Handling
def create_client(name):
    try:
        client.table('clients').insert({"name": name}).execute()
        st.success(f"Client '{name}' added successfully!")
    except Exception as e:
        if "duplicate key value violates unique constraint" in str(e):
            st.warning(f"Client '{name}' already exists.")
        else:
            st.error(f"Error adding client: {e}")

# ✅ Add Stock to Portfolio
def add_stock_to_portfolio(client_name, stock_name, quantity):
    client_id = get_client_id(client_name)
    if not client_id:
        st.error(f"Client '{client_name}' not found.")
        return

    # Check if stock already exists, update quantity
    existing_stock = client.table('portfolios').select("*").eq('client_id', client_id).eq('stock_name', stock_name).execute().data
    if existing_stock:
        new_quantity = existing_stock[0]['quantity'] + quantity
        client.table('portfolios').update({'quantity': new_quantity}).eq('client_id', client_id).eq('stock_name', stock_name).execute()
        st.success(f"Updated '{stock_name}' quantity for '{client_name}'.")
    else:
        client.table('portfolios').insert({
            "client_id": client_id,
            "stock_name": stock_name,
            "quantity": quantity,
            "value": quantity * stocks.loc[stocks['name'] == stock_name, 'dernier_cours'].values[0]
        }).execute()
        st.success(f"Added '{stock_name}' to '{client_name}' portfolio.")

# ✅ Get Client ID
def get_client_id(name):
    result = client.table('clients').select('id').eq('name', name).execute()
    if result.data:
        return result.data[0]['id']
    return None

# ✅ Show Portfolio for a Specific Client
def show_portfolio(client_name):
    client_id = get_client_id(client_name)
    if not client_id:
        st.error(f"Client '{client_name}' not found.")
        return

    # Fetch Portfolio Data
    query = client.table('portfolios').select("stock_name, quantity, value").eq('client_id', client_id).execute()
    df = pd.DataFrame(query.data)

    # Add Cash Row (Assuming Cash is calculated separately or from DB)
    cash_value = df["value"].sum() * 0.1  # Example: 10% of portfolio value
    cash_row = pd.DataFrame([{"stock_name": "CASH", "quantity": 1, "value": cash_value}])
    df = pd.concat([df, cash_row], ignore_index=True)

    # Rename Columns
    df.rename(columns={
        "stock_name": "valeur",
        "quantity": "quantité",
        "value": "valorisation"
    }, inplace=True)

    # Display Client Name and Portfolio
    st.subheader(f"📜 Portfolio for {client_name}")
    st.dataframe(df, use_container_width=True, height=300)

    # Show Total Portfolio Value
    total_value = df["valorisation"].sum()
    st.write(f"**💰 Valorisation totale du portefeuille:** {total_value}")

# ✅ Show All Clients' Portfolios
def show_all_portfolios():
    clients_query = client.table('clients').select("id, name").execute()
    clients = pd.DataFrame(clients_query.data)

    if clients.empty:
        st.warning("No clients found.")
        return

    for _, row in clients.iterrows():
        show_portfolio(row['name'])

# ✅ Streamlit UI with Sidebar Navigation
page = st.sidebar.selectbox("📂 Select Page", ["Clients", "Cours (Stocks)", "Client Portfolio", "All Portfolios"])

if page == "Clients":
    st.title("👤 Manage Clients")
    client_name = st.text_input("Client Name")
    if st.button("➕ Add Client"):
        create_client(client_name)

elif page == "Cours (Stocks)":
    st.title("📈 Stock Prices")
    st.dataframe(stocks, use_container_width=True)

elif page == "Client Portfolio":
    st.title("📜 Client Portfolio")
    client_name = st.text_input("Enter Client Name")
    if st.button("🔍 Show Portfolio"):
        show_portfolio(client_name)

elif page == "All Portfolios":
    st.title("📊 All Clients' Portfolios")
    show_all_portfolios()
