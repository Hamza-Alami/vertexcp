import streamlit as st
import pandas as pd
import requests
from supabase import create_client

# ✅ Connect to Supabase
supabase_url = st.secrets["supabase"]["url"]
supabase_key = st.secrets["supabase"]["key"]
client = create_client(supabase_url, supabase_key)

# ✅ Fetch Stocks from ID Bourse API + Add Cash
@st.cache_data
def get_stock_list():
    try:
        response = requests.get("https://backend.idbourse.com/api_2/get_all_data", timeout=10)
        response.raise_for_status()
        data = response.json()
        stocks_df = pd.DataFrame(
            [(s.get('name', 'N/A'), s.get('dernier_cours', 0)) for s in data],
            columns=['valeur', 'cours']
        )
        # Add Cash as a stock with a fixed price of 1
        cash_row = pd.DataFrame([{'valeur': 'Cash', 'cours': 1}])
        return pd.concat([stocks_df, cash_row], ignore_index=True)
    except Exception as e:
        st.error(f"Failed to fetch stock data: {e}")
        return pd.DataFrame(columns=["valeur", "cours"])

stocks = get_stock_list()

# ✅ Helper: Get All Clients
def get_all_clients():
    result = client.table('clients').select("*").execute()
    return [c["name"] for c in result.data] if result.data else []

# ✅ Helper: Get Client ID
def get_client_id(client_name):
    result = client.table('clients').select("id").eq("name", client_name).execute()
    return result.data[0]["id"] if result.data else None

# ✅ Create Client
def create_client(name):
    if not name:
        st.error("Client name cannot be empty.")
        return
    try:
        client.table('clients').insert({"name": name}).execute()
        st.success(f"Client '{name}' added!")
    except Exception as e:
        st.error(f"Error adding client: {e}")

# ✅ Rename Client
def rename_client(old_name, new_name):
    if old_name and new_name:
        client_id = get_client_id(old_name)
        client.table('clients').update({"name": new_name}).eq("id", client_id).execute()
        st.success(f"Renamed '{old_name}' to '{new_name}'")

# ✅ Delete Client
def delete_client(client_name):
    client_id = get_client_id(client_name)
    if client_id:
        client.table('clients').delete().eq("id", client_id).execute()
        st.success(f"Deleted client '{client_name}'")

# ✅ Create Portfolio (With Initial Stocks or Cash)
def create_portfolio(client_name, initial_stocks):
    client_id = get_client_id(client_name)
    if not client_id:
        st.error("Client not found.")
        return

    portfolio_rows = []
    for stock, qty in initial_stocks.items():
        if qty > 0:
            stock_price = stocks.loc[stocks["valeur"] == stock, "cours"].values[0]
            valorisation = qty * stock_price
            portfolio_rows.append({
                "client_id": client_id,
                "valeur": stock,
                "quantité": qty,
                "cours": stock_price,
                "valorisation": valorisation
            })
    
    if portfolio_rows:
        client.table('portfolios').upsert(portfolio_rows).execute()
        st.success(f"Portfolio created for '{client_name}' with initial holdings.")
    else:
        st.warning("No stocks or cash provided for portfolio creation.")

# ✅ Get Portfolio Data for Client
def get_portfolio(client_name):
    client_id = get_client_id(client_name)
    if not client_id:
        return pd.DataFrame()
    result = client.table('portfolios').select("*").eq("client_id", client_id).execute()
    return pd.DataFrame(result.data)

# ✅ Show Portfolio (With Inline Editing)
def show_portfolio(client_name):
    df = get_portfolio(client_name)
    if df.empty:
        st.warning(f"No portfolio found for '{client_name}'")
        return
    
    # Add Poids (Weight) Column
    total_value = df["valorisation"].sum()
    df["poids"] = ((df["valorisation"] / total_value) * 100).round(2).astype(str) + "%"

    # Display Portfolio with Editable Table
    st.subheader(f"📜 Portfolio for {client_name}")
    edited_df = st.data_editor(
        df[["valeur", "quantité", "valorisation", "poids"]],
        use_container_width=True,
        num_rows="dynamic"
    )

    # Save Changes Button
    if st.button("💾 Save Portfolio Changes"):
        for index, row in edited_df.iterrows():
            if row["valeur"] == "Cash" and row["quantité"] < 0:
                st.error("Cash cannot be negative!")
                return
            updated_valorisation = row["quantité"] * (stocks.loc[stocks["valeur"] == row["valeur"], "cours"].values[0] if row["valeur"] != "Cash" else 1)
            client.table('portfolios').update({
                "quantité": row["quantité"],
                "valorisation": updated_valorisation
            }).eq("client_id", get_client_id(client_name)).eq("valeur", row["valeur"]).execute()
        st.success("Portfolio updated successfully!")

    # Show Total Portfolio Value
    total_portfolio_value = df["valorisation"].sum()
    st.write(f"**💰 Valorisation totale du portefeuille:** {total_portfolio_value:.2f}")

# ✅ Show All Clients' Portfolios
def show_all_portfolios():
    clients = get_all_clients()
    if not clients:
        st.warning("No clients found.")
        return

    for client_name in clients:
        st.write("---")
        show_portfolio(client_name)

# ✅ Streamlit Sidebar Navigation
page = st.sidebar.selectbox("📂 Navigation", [
    "Manage Clients",
    "Create Portfolio",
    "View Client Portfolio",
    "View All Portfolios"
])

# ----------------------------- Main Pages -------------------------------- #

if page == "Manage Clients":
    st.title("👤 Manage Clients")
    existing_clients = get_all_clients()

    # Add New Client
    with st.form("add_client_form"):
        new_client = st.text_input("New Client Name")
        submitted = st.form_submit_button("➕ Add Client")
        if submitted:
            create_client(new_client)

    # Rename Client
    with st.form("rename_client_form"):
        old_name = st.selectbox("Select Client to Rename", options=existing_clients, placeholder="Select...")
        new_name = st.text_input("New Client Name")
        rename_submitted = st.form_submit_button("✏️ Rename Client")
        if rename_submitted:
            rename_client(old_name, new_name)

    # Delete Client
    with st.form("delete_client_form"):
        delete_name = st.selectbox("Select Client to Delete", options=existing_clients, placeholder="Select...")
        delete_submitted = st.form_submit_button("🗑️ Delete Client")
        if delete_submitted:
            delete_client(delete_name)

elif page == "Create Portfolio":
    st.title("📊 Create Client Portfolio")
    existing_clients = get_all_clients()
    client_name = st.selectbox(
        "Select or Enter Client Name",
        options=[""] + existing_clients,
        placeholder="Select or type..."
    )

    st.subheader("📈 Add Initial Holdings")
    initial_stocks = {}
    for stock_name in stocks["valeur"].values:
        qty = st.number_input(f"Quantity of {stock_name}", min_value=0, value=0, key=stock_name)
        if qty > 0:
            initial_stocks[stock_name] = qty

    if st.button("💾 Create Portfolio"):
        if client_name:
            create_portfolio(client_name, initial_stocks)
        else:
            st.error("Please enter or select a client name!")

elif page == "View Client Portfolio":
    st.title("📜 View Client Portfolio")
    existing_clients = get_all_clients()
    client_name = st.selectbox(
        "Select Client",
        options=existing_clients,
        placeholder="Choose a client"
    )
    if client_name:
        show_portfolio(client_name)

elif page == "View All Portfolios":
    st.title("📊 All Clients' Portfolios")
    show_all_portfolios()
