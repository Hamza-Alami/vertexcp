import streamlit as st
import pandas as pd
from supabase import create_client
import requests

# ✅ Connect to Supabase
supabase_url = st.secrets["supabase"]["url"]
supabase_key = st.secrets["supabase"]["key"]
client = create_client(supabase_url, supabase_key)

# ✅ Fetch Stocks from ID Bourse API with Error Handling
@st.cache_data
def get_stock_data():
    try:
        response = requests.get("https://backend.idbourse.com/api_2/get_all_data", timeout=10)
        response.raise_for_status()
        data = response.json()
        return pd.DataFrame(
            [(s.get('name', 'N/A'), s.get('dernier_cours', 0)) for s in data],
            columns=['name', 'dernier_cours']
        )
    except Exception as e:
        st.error(f"Failed to fetch stock data: {e}")
        return pd.DataFrame(columns=["name", "dernier_cours"])

stocks = get_stock_data()

# ✅ Get Client ID by Name
def get_client_id(client_name):
    result = client.table('clients').select("id").eq("name", client_name).execute()
    if result.data:
        return result.data[0]["id"]
    return None

# ✅ Create a New Client
def create_client(name):
    try:
        client.table('clients').insert({"name": name}).execute()
    except Exception as e:
        st.error(f"Error creating client: {e}")

# ✅ Add or Update Stock in Portfolio
def add_stock_to_portfolio(client_name, stock_name, quantity):
    client_id = get_client_id(client_name)
    if not client_id:
        st.error(f"Client '{client_name}' not found.")
        return

    # Check if stock exists
    existing_stock = client.table('portfolios').select("*").eq('client_id', client_id).eq('stock_name', stock_name).execute()
    
    if existing_stock.data:
        # Update quantity if stock already exists
        current_quantity = existing_stock.data[0]["quantity"]
        new_quantity = current_quantity + quantity
        if new_quantity <= 0:
            # Remove stock if quantity <= 0
            client.table('portfolios').delete().eq('client_id', client_id).eq('stock_name', stock_name).execute()
            st.info(f"Removed '{stock_name}' from portfolio.")
        else:
            client.table('portfolios').update({"quantity": new_quantity}).eq('client_id', client_id).eq('stock_name', stock_name).execute()
            st.success(f"Updated '{stock_name}' quantity to {new_quantity}.")
    else:
        # Add new stock
        stock_price = stocks.loc[stocks["name"] == stock_name, "dernier_cours"].values[0] if stock_name in stocks["name"].values else 0
        value = stock_price * quantity
        client.table('portfolios').insert({
            "client_id": client_id,
            "stock_name": stock_name,
            "quantity": quantity,
            "value": value
        }).execute()
        st.success(f"Added '{stock_name}' to portfolio.")

# ✅ Show Portfolio for a Specific Client
def show_portfolio(client_name):
    client_id = get_client_id(client_name)
    if not client_id:
        st.error(f"Client '{client_name}' not found.")
        return

    query = client.table('portfolios').select("stock_name, quantity, value").eq('client_id', client_id).execute()
    df = pd.DataFrame(query.data)

    if df.empty:
        st.warning(f"No portfolio data found for '{client_name}'.")
        return

    # Ensure 'value' column exists
    if 'value' not in df.columns:
        df['value'] = 0.0

    # Add Cash Row
    cash_value = df['value'].sum() * 0.1  # Example: Cash = 10% of portfolio value
    cash_row = pd.DataFrame([{"stock_name": "CASH", "quantity": 1, "value": cash_value}])
    df = pd.concat([df, cash_row], ignore_index=True)

    # Rename Columns for Display
    df.rename(columns={
        "stock_name": "valeur",
        "quantity": "quantité",
        "value": "valorisation"
    }, inplace=True)

    # Display Portfolio with Client Name Above
    st.subheader(f"📜 Portfolio for {client_name}")
    st.dataframe(df, use_container_width=True, height=300)

    # Show Total Portfolio Value
    total_value = df["valorisation"].sum()
    st.write(f"**💰 Valorisation totale du portefeuille:** {total_value}")

# ✅ Show All Clients' Portfolios One by One
def show_all_portfolios():
    clients = client.table('clients').select("name").execute().data
    if not clients:
        st.warning("No clients found.")
        return

    for c in clients:
        client_name = c["name"]
        st.write("---")
        show_portfolio(client_name)

# ✅ Streamlit UI with Pages
page = st.sidebar.selectbox("📂 Choose Page", ["Clients", "Cours (Stocks)", "Client Portfolio", "All Portfolios"])

if page == "Clients":
    st.title("👤 Manage Clients")
    client_name = st.text_input("Client Name")
    if st.button("➕ Add Client"):
        create_client(client_name)
        st.success(f"Client '{client_name}' added!")

elif page == "Cours (Stocks)":
    st.title("📈 Stock Prices")
    st.dataframe(stocks)

elif page == "Client Portfolio":
    st.title("📜 Client Portfolio")
    client_name = st.text_input("Enter Client Name")
    if st.button("🔍 Show Portfolio"):
        show_portfolio(client_name)

elif page == "All Portfolios":
    st.title("📊 All Clients' Portfolios")
    show_all_portfolios()
