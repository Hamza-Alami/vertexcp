import streamlit as st
import pandas as pd
import requests
from supabase import create_client
from collections import defaultdict

# ===================== Supabase Connection =====================
supabase_url = st.secrets["supabase"]["url"]
supabase_key = st.secrets["supabase"]["key"]
client = create_client(supabase_url, supabase_key)

# ===================== Fetch Stock Data ========================
@st.cache_data
def get_stock_list():
    try:
        response = requests.get("https://backend.idbourse.com/api_2/get_all_data", timeout=10)
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(
            [(s.get("name", "N/A"), s.get("dernier_cours", 0)) for s in data],
            columns=["valeur", "cours"]
        )
        # Add CASH as a stock with a price of 1
        cash_row = pd.DataFrame([{"valeur": "Cash", "cours": 1}])
        return pd.concat([df, cash_row], ignore_index=True)
    except Exception as e:
        st.error(f"Failed to fetch stock data: {e}")
        return pd.DataFrame(columns=["valeur", "cours"])

stocks = get_stock_list()

# ===================== Helper Functions ========================
def get_all_clients():
    res = client.table("clients").select("*").execute()
    return [r["name"] for r in res.data] if res.data else []

def get_client_id(client_name):
    res = client.table("clients").select("id").eq("name", client_name).execute()
    return res.data[0]["id"] if res.data else None

def client_has_portfolio(client_name):
    cid = get_client_id(client_name)
    if not cid:
        return False
    port = client.table("portfolios").select("*").eq("client_id", cid).execute()
    return len(port.data) > 0

# ===================== Client Management =======================
def create_client(name):
    if not name:
        st.error("Client name cannot be empty.")
        return
    try:
        client.table("clients").insert({"name": name}).execute()
        st.success(f"Client '{name}' added!")
        st.experimental_rerun()
    except Exception as e:
        st.error(f"Error adding client: {e}")

def rename_client(old_name, new_name):
    cid = get_client_id(old_name)
    if cid:
        client.table("clients").update({"name": new_name}).eq("id", cid).execute()
        st.success(f"Renamed '{old_name}' to '{new_name}'")
        st.experimental_rerun()
    else:
        st.error("Client not found.")

def delete_client(cname):
    cid = get_client_id(cname)
    if cid:
        client.table("clients").delete().eq("id", cid).execute()
        st.success(f"Deleted client '{cname}'")
        st.experimental_rerun()
    else:
        st.error("Client not found.")

# ===================== Portfolio Management =====================
def create_portfolio_rows(client_name, holdings):
    """Actually create the portfolio rows for multiple stocks/cash."""
    cid = get_client_id(client_name)
    if not cid:
        st.error("Client not found.")
        return

    if client_has_portfolio(client_name):
        st.warning(f"Client '{client_name}' already has a portfolio. Go to 'View Client Portfolio' to edit it.")
        return

    rows = []
    for stock, qty in holdings.items():
        if qty > 0:
            price = stocks.loc[stocks["valeur"] == stock, "cours"].values[0]
            val = qty * price
            rows.append({
                "client_id": cid,
                "valeur": stock,
                "quantité": qty,
                "cours": price,
                "valorisation": val
            })
    if rows:
        client.table("portfolios").upsert(rows).execute()
        st.success(f"Portfolio created for '{client_name}'!")
        st.experimental_rerun()
    else:
        st.warning("No stocks or cash provided for portfolio creation.")

def get_portfolio(client_name):
    cid = get_client_id(client_name)
    if not cid:
        return pd.DataFrame()
    res = client.table("portfolios").select("*").eq("client_id", cid).execute()
    return pd.DataFrame(res.data)

# ===================== Create Portfolio UI =====================
def new_portfolio_creation_ui(client_name):
    """Lets user add multiple stocks/cash before final creation."""
    st.subheader(f"➕ Add Initial Holdings for {client_name}")
    if "temp_holdings" not in st.session_state:
        st.session_state.temp_holdings = {}

    new_stock = st.selectbox(f"Select Stock/Cash for {client_name}", stocks["valeur"].tolist(), key=f"new_stock_{client_name}")
    qty = st.number_input(f"Quantity for {client_name}", min_value=1, value=1, key=f"new_qty_{client_name}")

    if st.button(f"➕ Add {new_stock}", key=f"add_btn_{client_name}"):
        st.session_state.temp_holdings[new_stock] = qty
        st.success(f"Added {qty} of {new_stock}")

    if st.session_state.temp_holdings:
        st.write("### Current Selections:")
        holdings_df = pd.DataFrame([
            {"valeur": k, "quantité": v} for k, v in st.session_state.temp_holdings.items()
        ])
        st.dataframe(holdings_df, use_container_width=True)

        if st.button(f"💾 Create Portfolio for {client_name}", key=f"create_pf_btn_{client_name}"):
            create_portfolio_rows(client_name, st.session_state.temp_holdings)
            if "temp_holdings" in st.session_state:
                del st.session_state.temp_holdings

# ===================== Show Single Portfolio =====================
def show_portfolio(client_name, read_only=False):
    """
    Display or edit a single portfolio.
    If read_only=True, it shows a read-only table (like in All Portfolios).
    """
    df = get_portfolio(client_name)
    if df.empty:
        st.warning(f"No portfolio found for '{client_name}'")
        return

    total_value = df["valorisation"].sum()
    # Store 'poids' as a float for sorting
    df["poids"] = ((df["valorisation"] / total_value) * 100).round(2)

    st.subheader(f"📜 Portfolio for {client_name}")
    st.write(f"**Valorisation totale du portefeuille:** {total_value:.2f}")

    if read_only:
        # Read-only display
        st.dataframe(df[["valeur", "quantité", "valorisation", "poids"]], use_container_width=True)
    else:
        # Editable table
        edited_df = st.data_editor(
            df[["valeur", "quantité", "valorisation", "poids"]],
            use_container_width=True,
            column_config={
                "poids": st.column_config.NumberColumn("Poids (%)", format="%.2f", step=0.01),
                "valorisation": st.column_config.NumberColumn("Valorisation", format="%.2f"),
                "quantité": st.column_config.NumberColumn("Quantité")
            },
            key=f"pf_editor_{client_name}"
        )

        # Save changes
        if st.button(f"💾 Save Portfolio Changes ({client_name})", key=f"save_btn_{client_name}"):
            for index, row in edited_df.iterrows():
                price = stocks.loc[stocks["valeur"] == row["valeur"], "cours"].values[0]
                updated_val = row["quantité"] * price
                client.table("portfolios").update({
                    "quantité": row["quantité"],
                    "valorisation": updated_val
                }).eq("client_id", get_client_id(client_name)).eq("valeur", row["valeur"]).execute()
            st.success(f"Portfolio updated for '{client_name}'!")
            st.experimental_rerun()

        # Add Stock/Cash
        add_stock = st.selectbox(f"Select Stock/Cash to Add ({client_name})", stocks["valeur"].tolist(), key=f"add_s_{client_name}")
        add_qty = st.number_input(f"Quantity for {client_name}", min_value=1, value=1, key=f"qty_s_{client_name}")
        if st.button(f"➕ Add {add_stock} to {client_name}", key=f"btn_add_{client_name}"):
            price = stocks.loc[stocks["valeur"] == add_stock, "cours"].values[0]
            val = add_qty * price
            client.table("portfolios").insert({
                "client_id": get_client_id(client_name),
                "valeur": add_stock,
                "quantité": add_qty,
                "cours": price,
                "valorisation": val
            }).execute()
            st.success(f"Added {add_qty} of {add_stock}")
            st.experimental_rerun()

        # Delete Stock/Cash
        del_choice = st.selectbox(f"Select Stock to Remove ({client_name})", df["valeur"].tolist(), key=f"del_s_{client_name}")
        if st.button(f"🗑️ Delete {del_choice}", key=f"del_btn_{client_name}"):
            client.table("portfolios").delete().eq("client_id", get_client_id(client_name)).eq("valeur", del_choice).execute()
            st.success(f"Removed {del_choice}")
            st.experimental_rerun()

# ===================== Show All Portfolios =====================
def show_all_portfolios():
    clients = get_all_clients()
    if not clients:
        st.warning("No clients found.")
        return
    for cname in clients:
        st.write(f"### Client: {cname}")
        show_portfolio(cname, read_only=True)
        st.write("---")

# ===================== Inventory Page =====================
def show_inventory():
    """
    Displays:
    1) A table of all stocks & cash across all portfolios,
       with a total quantity column and a 'portefeuille' column listing which clients hold it.
    2) The total assets under management = sum of all clients' portfolio values.
    """
    clients = get_all_clients()
    if not clients:
        st.warning("No clients found. Please create a client first.")
        return

    # Summation data structure: {valeur: {"quantity": 0, "clients": set()}}
    from collections import defaultdict
    master = defaultdict(lambda: {"quantity": 0, "clients": set()})

    total_assets = 0

    for c in clients:
        df = get_portfolio(c)
        if not df.empty:
            # Sum up the total for this client
            total_val = df["valorisation"].sum()
            total_assets += total_val
            # Merge stock quantities
            for _, row in df.iterrows():
                val = row["valeur"]
                q = row["quantité"]
                master[val]["quantity"] += q
                master[val]["clients"].add(c)

    # Build table
    data_rows = []
    for val, info in master.items():
        data_rows.append({
            "valeur": val,
            "quantité total": info["quantity"],
            "portefeuille": ", ".join(sorted(info["clients"]))
        })

    st.title("🗃️ Global Inventory")
    if data_rows:
        inv_df = pd.DataFrame(data_rows)
        st.dataframe(inv_df, use_container_width=True)
    else:
        st.write("No stocks or cash found in any portfolio.")

    st.write(f"### Actif sous gestion: {total_assets:.2f}")

# ===================== Pages =====================
page = st.sidebar.selectbox(
    "📂 Navigation",
    [
        "Manage Clients",
        "Create Portfolio",
        "View Client Portfolio",
        "View All Portfolios",
        "Inventory"  # <-- New Page
    ]
)

if page == "Manage Clients":
    st.title("👤 Manage Clients")
    existing = get_all_clients()

    with st.form("add_client_form", clear_on_submit=True):
        new_client_name = st.text_input("New Client Name", key="new_client_input")
        if st.form_submit_button("➕ Add Client"):
            create_client(new_client_name)

    if existing:
        # Rename
        with st.form("rename_client_form", clear_on_submit=True):
            rename_choice = st.selectbox("Select Client to Rename", options=existing, key="rename_choice")
            rename_new = st.text_input("New Client Name", key="rename_text")
            if st.form_submit_button("✏️ Rename Client"):
                rename_client(rename_choice, rename_new)

        # Delete
        with st.form("delete_client_form", clear_on_submit=True):
            delete_choice = st.selectbox("Select Client to Delete", options=existing, key="delete_choice")
            if st.form_submit_button("🗑️ Delete Client"):
                delete_client(delete_choice)

elif page == "Create Portfolio":
    st.title("📊 Create Client Portfolio")
    clist = get_all_clients()
    if not clist:
        st.warning("No clients found. Please create a client first.")
    else:
        cselect = st.selectbox("Select Client", clist, key="create_pf_select")
        if cselect:
            if client_has_portfolio(cselect):
                st.warning(f"Client '{cselect}' already has a portfolio. Go to 'View Client Portfolio' to edit.")
            else:
                new_portfolio_creation_ui(cselect)

elif page == "View Client Portfolio":
    st.title("📊 View Client Portfolio")
    c2 = get_all_clients()
    if not c2:
        st.warning("No clients found. Please create a client first.")
    else:
        client_selected = st.selectbox("Select Client", c2, key="view_portfolio_select")
        if client_selected:
            show_portfolio(client_selected, read_only=False)

elif page == "View All Portfolios":
    st.title("📊 All Clients' Portfolios")
    show_all_portfolios()

elif page == "Inventory":  # New Page
    show_inventory()
