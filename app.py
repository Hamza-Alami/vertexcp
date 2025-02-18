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

# ✅ Helper Functions
def get_all_clients():
    result = client.table('clients').select("*").execute()
    return [c["name"] for c in result.data] if result.data else []

def get_client_id(client_name):
    result = client.table('clients').select("id").eq("name", client_name).execute()
    return result.data[0]["id"] if result.data else None

# ✅ Portfolio Management Functions
def get_portfolio(client_name):
    client_id = get_client_id(client_name)
    if not client_id:
        return pd.DataFrame()
    result = client.table('portfolios').select("*").eq("client_id", client_id).execute()
    return pd.DataFrame(result.data)

def add_stock_to_portfolio(client_name, stock_name, quantity):
    client_id = get_client_id(client_name)
    if not client_id:
        return
    
    stock_price = stocks.loc[stocks["valeur"] == stock_name, "cours"].values[0]
    valorisation = quantity * stock_price
    
    client.table('portfolios').upsert({
        "client_id": client_id,
        "valeur": stock_name,
        "quantité": quantity,
        "cours": stock_price,
        "valorisation": valorisation
    }).execute()

    st.success(f"Added {quantity} units of {stock_name} to {client_name}'s portfolio!")

def delete_stock_from_portfolio(client_name, stock_name):
    client_id = get_client_id(client_name)
    if not client_id:
        return
    
    client.table('portfolios').delete().eq("client_id", client_id).eq("valeur", stock_name).execute()
    st.success(f"Deleted {stock_name} from {client_name}'s portfolio!")

# ✅ Show Portfolio (Now with Add & Delete Stock)
def show_portfolio(client_name):
    df = get_portfolio(client_name)
    if df.empty:
        st.warning(f"No portfolio found for '{client_name}'")
        return
    
    total_value = df["valorisation"].sum()
    df["poids"] = ((df["valorisation"] / total_value) * 100).round(2).astype(str) + "%"  

    st.subheader(f"📜 Portfolio for {client_name}")

    # Editable Table
    edited_df = st.data_editor(
        df[["valeur", "quantité", "valorisation", "poids"]],
        use_container_width=True,
        num_rows="dynamic",
        key=f"portfolio_table_{client_name}"
    )

    # Save Changes
    if st.button(f"💾 Save Portfolio Changes ({client_name})", key=f"save_{client_name}"):
        for index, row in edited_df.iterrows():
            updated_valorisation = row["quantité"] * stocks.loc[stocks["valeur"] == row["valeur"], "cours"].values[0]
            client.table('portfolios').update({
                "quantité": row["quantité"],
                "valorisation": updated_valorisation
            }).eq("client_id", get_client_id(client_name)).eq("valeur", row["valeur"]).execute()
        st.success(f"Portfolio updated successfully for {client_name}!")

    # Add Stock
    st.subheader("➕ Add Stock to Portfolio")
    selected_stock = st.selectbox(
        "Select Stock to Add",
        options=stocks["valeur"].tolist(),
        key=f"add_stock_{client_name}"
    )
    stock_quantity = st.number_input("Quantity", min_value=1, value=1, key=f"quantity_{client_name}")

    if st.button(f"➕ Add {selected_stock} to Portfolio", key=f"add_stock_btn_{client_name}"):
        add_stock_to_portfolio(client_name, selected_stock, stock_quantity)

    # Delete Stock
    st.subheader("🗑️ Delete Stock from Portfolio")
    if not df.empty:
        stock_to_delete = st.selectbox(
            "Select Stock to Delete",
            options=df["valeur"].tolist(),
            key=f"delete_stock_{client_name}"
        )
        if st.button(f"🗑️ Delete {stock_to_delete}", key=f"delete_stock_btn_{client_name}"):
            delete_stock_from_portfolio(client_name, stock_to_delete)

    st.write(f"**💰 Valorisation totale du portefeuille:** {total_value:.2f}")

# ✅ Show All Clients' Portfolios
def show_all_portfolios():
    clients = get_all_clients()
    if not clients:
        st.warning("No clients found.")
        return

    for i, client_name in enumerate(clients):
        st.write("---")
        show_portfolio(client_name)

# ✅ Streamlit Sidebar Navigation
page = st.sidebar.selectbox("📂 Navigation", [
    "Manage Clients",
    "Create Portfolio",
    "View Client Portfolio",
    "View All Portfolios"
])

if page == "Manage Clients":
    st.title("👤 Manage Clients")
    existing_clients = get_all_clients()

    with st.form("add_client_form"):
        new_client = st.text_input("New Client Name")
        submitted = st.form_submit_button("➕ Add Client")
        if submitted:
            create_client(new_client)

    with st.form("rename_client_form"):
        old_name = st.selectbox("Select Client to Rename", options=existing_clients)
        new_name = st.text_input("New Client Name")
        rename_submitted = st.form_submit_button("✏️ Rename Client")
        if rename_submitted:
            rename_client(old_name, new_name)

    with st.form("delete_client_form"):
        delete_name = st.selectbox("Select Client to Delete", options=existing_clients)
        delete_submitted = st.form_submit_button("🗑️ Delete Client")
        if delete_submitted:
            delete_client(delete_name)

elif page == "Create Portfolio":
    st.title("📊 Create Client Portfolio")
    client_name = st.selectbox("Select Client", options=get_all_clients())
    
    st.subheader("➕ Add Initial Holdings")
    initial_holdings = {}
    selected_stock = st.selectbox("Search and Add Stock or Cash", options=stocks["valeur"].tolist())
    quantity = st.number_input("Quantity", min_value=1, value=1)

    if st.button("➕ Add to Holdings"):
        if selected_stock in initial_holdings:
            st.warning(f"{selected_stock} already added. Adjust the quantity directly.")
        else:
            initial_holdings[selected_stock] = quantity

    if initial_holdings:
        st.write("### Current Holdings:")
        st.dataframe(pd.DataFrame([
            {"valeur": k, "quantité": v} for k, v in initial_holdings.items()
        ]), use_container_width=True)

    if st.button("💾 Create Portfolio"):
        create_portfolio(client_name, initial_holdings)

elif page == "View Client Portfolio":
    client_name = st.selectbox("Select Client", options=get_all_clients())
    if client_name:
        show_portfolio(client_name)

elif page == "View All Portfolios":
    show_all_portfolios()
