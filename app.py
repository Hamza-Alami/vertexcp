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
    client_id = get_client_id(old_name)
    if client_id:
        client.table('clients').update({"name": new_name}).eq("id", client_id).execute()
        st.success(f"Renamed '{old_name}' to '{new_name}'")
    else:
        st.error("Client not found.")

# ✅ Delete Client
def delete_client(client_name):
    client_id = get_client_id(client_name)
    if client_id:
        client.table('clients').delete().eq("id", client_id).execute()
        st.success(f"Deleted client '{client_name}'")
    else:
        st.error("Client not found.")

# ✅ Check if Client Already Has a Portfolio
def client_has_portfolio(client_name):
    client_id = get_client_id(client_name)
    if not client_id:
        return False
    result = client.table('portfolios').select("*").eq("client_id", client_id).execute()
    return len(result.data) > 0

# ✅ Create Portfolio (Fresh Start)
def create_portfolio_rows(client_name, holdings):
    """Helper to create the actual portfolio rows in DB."""
    client_id = get_client_id(client_name)
    portfolio_rows = []
    for stock, qty in holdings.items():
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

# ✅ Show Portfolio (View & Edit)
def show_portfolio(client_name):
    df = get_portfolio(client_name)
    if df.empty:
        st.warning(f"No portfolio found for '{client_name}'")
        return
    
    total_value = df["valorisation"].sum()
    df["poids"] = ((df["valorisation"] / total_value) * 100).round(2).astype(str) + "%"

    st.subheader(f"📜 Portfolio for {client_name}")
    edited_df = st.data_editor(df[["valeur", "quantité", "valorisation", "poids"]], use_container_width=True)

    # Add Stock/Cash
    new_stock = st.selectbox(f"Select Stock/Cash to Add for {client_name}", stocks["valeur"].tolist(), key=f"add_{client_name}")
    quantity = st.number_input(f"Quantity for {client_name}", min_value=1, value=1, key=f"qty_{client_name}")
    if st.button(f"➕ Add to {client_name}", key=f"btn_add_{client_name}"):
        client.table('portfolios').insert({
            "client_id": get_client_id(client_name),
            "valeur": new_stock,
            "quantité": quantity,
            "cours": stocks.loc[stocks["valeur"] == new_stock, "cours"].values[0],
            "valorisation": quantity * stocks.loc[stocks["valeur"] == new_stock, "cours"].values[0]
        }).execute()
        st.success(f"Added {quantity} units of {new_stock} to {client_name}'s portfolio")

    # Delete Stock/Cash
    if not df.empty:
        stock_to_delete = st.selectbox(f"Select Stock to Remove from {client_name}", df["valeur"].tolist(), key=f"del_{client_name}")
        if st.button(f"🗑️ Delete {stock_to_delete}", key=f"del_btn_{client_name}"):
            client.table('portfolios').delete().eq("client_id", get_client_id(client_name)).eq("valeur", stock_to_delete).execute()
            st.success(f"Removed {stock_to_delete}")

    # Save Changes
    if st.button(f"💾 Save Portfolio Changes for {client_name}", key=f"save_{client_name}"):
        for index, row in edited_df.iterrows():
            client.table('portfolios').update({
                "quantité": row["quantité"],
                "valorisation": row["quantité"] * stocks.loc[stocks["valeur"] == row["valeur"], "cours"].values[0]
            }).eq("client_id", get_client_id(client_name)).eq("valeur", row["valeur"]).execute()
        st.success(f"Portfolio updated successfully for {client_name}!")

# ✅ Show All Clients' Portfolios
def show_all_portfolios():
    clients = get_all_clients()
    if not clients:
        st.warning("No clients found.")
        return
    for i, client_name in enumerate(clients):
        st.write("---")
        show_portfolio(client_name)

# ✅ For Creating a Portfolio from Scratch
def new_portfolio_creation_ui(client_name):
    """ Lets user add multiple stocks/cash before saving. """
    st.subheader(f"➕ Add Holdings for {client_name}")

    # Keep track of additions in session state
    if "temp_holdings" not in st.session_state:
        st.session_state.temp_holdings = {}

    selected_stock = st.selectbox(f"Search & Add Stock/Cash ({client_name})", stocks["valeur"].tolist(), key=f"new_stock_{client_name}")
    quantity = st.number_input(f"Quantity for {client_name}", min_value=1, value=1, key=f"new_qty_{client_name}")

    if st.button(f"➕ Add {selected_stock} for {client_name}", key=f"add_temp_{client_name}"):
        st.session_state.temp_holdings[selected_stock] = quantity
        st.success(f"Added {quantity} of {selected_stock}")

    if st.session_state.temp_holdings:
        st.write("### Current Selections:")
        st.dataframe(pd.DataFrame([
            {"valeur": k, "quantité": v} for k, v in st.session_state.temp_holdings.items()
        ]), use_container_width=True)

        # Final Save Button
        if st.button(f"💾 Create Portfolio for {client_name}", key=f"save_portfolio_{client_name}"):
            create_portfolio_rows(client_name, st.session_state.temp_holdings)
            del st.session_state.temp_holdings  # Clear after creation

# ✅ Actually Create the rows in DB
def create_portfolio_rows(client_name, holdings):
    client_id = get_client_id(client_name)
    if not client_id:
        st.error("Client not found.")
        return

    # If client already has portfolio
    if client_has_portfolio(client_name):
        st.warning(f"Client '{client_name}' already has a portfolio. Go to 'View Client Portfolio' to edit it.")
        return

    rows = []
    for stock, qty in holdings.items():
        stock_price = stocks.loc[stocks["valeur"] == stock, "cours"].values[0]
        val = qty * stock_price
        rows.append({
            "client_id": client_id,
            "valeur": stock,
            "quantité": qty,
            "cours": stock_price,
            "valorisation": val
        })
    if rows:
        client.table('portfolios').upsert(rows).execute()
        st.success(f"Portfolio created for '{client_name}'!")
    else:
        st.warning("No stocks or cash provided for portfolio creation.")


# ================== Streamlit Pages ===================

page = st.sidebar.selectbox(
    "📂 Navigation",
    ["Manage Clients", "Create Portfolio", "View Client Portfolio", "View All Portfolios"]
)

if page == "Manage Clients":
    st.title("👤 Manage Clients")
    existing_clients = get_all_clients()

    # Create Client
    new_client = st.text_input("New Client Name")
    if st.button("➕ Add Client"):
        create_client(new_client)

    # Rename
    rename_choice = st.selectbox("Select Client to Rename", existing_clients)
    rename_to = st.text_input("New Client Name")
    if st.button("✏️ Rename Client"):
        rename_client(rename_choice, rename_to)

    # Delete
    del_choice = st.selectbox("Select Client to Delete", existing_clients)
    if st.button("🗑️ Delete Client"):
        delete_client(del_choice)

elif page == "Create Portfolio":
    st.title("📊 Create Client Portfolio")
    clients = get_all_clients()
    client_name = st.selectbox("Select Client", clients, key="create_portfolio_select")
    if client_name:
        # If client doesn't have portfolio, let them add multiple entries
        if not client_has_portfolio(client_name):
            new_portfolio_creation_ui(client_name)
        else:
            st.warning(f"Client '{client_name}' already has a portfolio. Go to 'View Client Portfolio' to edit.")

elif page == "View Client Portfolio":
    st.title("📜 View Client Portfolio")
    clients = get_all_clients()
    cl_name = st.selectbox("Select Client", clients, key="view_portfolio_select")
    if cl_name:
        show_portfolio(cl_name)

elif page == "View All Portfolios":
    st.title("📊 All Clients' Portfolios")
    show_all_portfolios()
