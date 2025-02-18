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
        return pd.DataFrame(
            [(s.get('name', 'N/A'), s.get('dernier_cours', 0)) for s in data],
            columns=['name', 'dernier_cours']
        )
    except Exception as e:
        st.error(f"Failed to fetch stock data: {e}")
        return pd.DataFrame(columns=["name", "dernier_cours"])

stocks = get_stock_data()

# ✅ Get All Clients
def get_all_clients():
    result = client.table('clients').select("name").execute()
    return [c["name"] for c in result.data] if result.data else []

# ✅ Get or Create Client ID
def get_or_create_client_id(client_name):
    result = client.table('clients').select("id").eq("name", client_name).execute()
    if result.data:
        return result.data[0]["id"]
    else:
        # Create client if doesn't exist
        insert_result = client.table('clients').insert({"name": client_name}).execute()
        if insert_result.data:
            return insert_result.data[0]["id"]
        return None

# ✅ Create Client
def create_client(name):
    client.table('clients').insert({"name": name}).execute()

# ✅ Create Portfolio (with initial Cash)
def create_portfolio(client_name, cash_amount):
    client_id = get_or_create_client_id(client_name)
    if client_id:
        # Add Cash row to portfolio
        client.table('portfolios').insert({
            "client_id": client_id,
            "stock_name": "CASH",
            "quantity": 1,
            "value": cash_amount
        }).execute()
        st.success(f"Portfolio created for '{client_name}' with {cash_amount} cash.")

# ✅ Add Stock to Portfolio
def add_stock_to_portfolio(client_name, stock_name, quantity):
    client_id = get_or_create_client_id(client_name)
    if not client_id:
        st.error(f"Failed to create or retrieve client '{client_name}'")
        return

    # Check if stock already in portfolio
    existing_stock = client.table('portfolios').select("*").eq('client_id', client_id).eq('stock_name', stock_name).execute()
    
    if existing_stock.data:
        # Update quantity
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
    client_id = get_or_create_client_id(client_name)
    if not client_id:
        st.error(f"Client '{client_name}' not found.")
        return

    query = client.table('portfolios').select("*").eq('client_id', client_id).execute()
    df = pd.DataFrame(query.data)

    if df.empty:
        st.warning(f"No portfolio data found for '{client_name}'.")
        return

    # Rename Columns for Display
    df.rename(columns={
        "stock_name": "valeur",
        "quantity": "quantité",
        "value": "valorisation"
    }, inplace=True)

    # Display Editable Portfolio
    st.subheader(f"📜 Portfolio for {client_name}")
    edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic")

    # Save Edits
    if st.button("💾 Save Portfolio Changes"):
        for index, row in edited_df.iterrows():
            client.table('portfolios').update({
                "quantity": row["quantité"],
                "value": row["valorisation"]
            }).eq('id', row["id"]).execute()
        st.success("Portfolio updated!")

    # Show Total Portfolio Value
    total_value = df["valorisation"].sum()
    st.write(f"**💰 Valorisation totale du portefeuille:** {total_value}")

# ✅ Show All Clients' Portfolios
def show_all_portfolios():
    clients = get_all_clients()
    if not clients:
        st.warning("No clients found.")
        return

    for client_name in clients:
        st.write("---")
        show_portfolio(client_name)

# ✅ Streamlit UI with Pages
page = st.sidebar.selectbox(
    "📂 Choose Page",
    ["Clients", "Create Portfolio", "Cours (Stocks)", "Client Portfolio", "All Portfolios"]
)

if page == "Clients":
    st.title("👤 Manage Clients")
    client_name = st.text_input("Client Name", placeholder="Type new or existing client name")
    if st.button("➕ Add Client"):
        create_client(client_name)
        st.success(f"Client '{client_name}' added!")

elif page == "Create Portfolio":
    st.title("🆕 Create Client Portfolio")
    client_name = st.text_input("Client Name", placeholder="Type client name")
    cash_amount = st.number_input("Initial Cash Amount", min_value=0.0, format="%.2f")
    if st.button("💰 Create Portfolio"):
        create_portfolio(client_name, cash_amount)

elif page == "Cours (Stocks)":
    st.title("📈 Stock Prices")
    st.dataframe(stocks)

elif page == "Client Portfolio":
    st.title("📜 Client Portfolio")
    existing_clients = get_all_clients()
    client_name = st.selectbox(
        "Select or Enter Client Name",
        options=[""] + existing_clients,
        placeholder="Type or select client"
    )
    if st.button("🔍 Show Portfolio"):
        show_portfolio(client_name)

elif page == "All Portfolios":
    st.title("📊 All Clients' Portfolios")
    show_all_portfolios()
