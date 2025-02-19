import streamlit as st
import pandas as pd
import requests
from supabase import create_client
from collections import defaultdict

# ===================== Supabase Connection =====================
supabase_url = st.secrets["supabase"]["url"]
supabase_key = st.secrets["supabase"]["key"]
client = create_client(supabase_url, supabase_key)

# ===================== Fetch Stock Data (auto-refresh every minute) =====================
@st.cache_data(ttl=60)
def get_stock_list():
    """
    Fetch the latest stock/cash prices from IDBourse.
    Caches for 60 seconds, so it's up to date each minute.
    """
    try:
        response = requests.get("https://backend.idbourse.com/api_2/get_all_data", timeout=10)
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(
            [(s.get("name", "N/A"), s.get("dernier_cours", 0)) for s in data],
            columns=["valeur", "cours"]
        )
        # Add Cash as a stock with a price of 1
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
    """
    Actually create the portfolio rows for multiple stocks/cash.
    We store 'quantité' in DB, but we'll recompute 'cours' & 'valorisation' dynamically later.
    """
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
            # We won't rely on old stored cours/valorisation in the DB
            # We'll store them as 0 or placeholders
            rows.append({
                "client_id": cid,
                "valeur": stock,
                "quantité": qty,
                "cours": 0.0,           # placeholder
                "valorisation": 0.0     # placeholder
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
    """
    Lets user add multiple stocks/cash before final creation.
    We'll store only 'quantité' in DB for each stock. 'cours' & 'valorisation' are placeholders.
    """
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
    We dynamically compute 'cours' and 'valorisation' from the fresh 'stocks' data each time.
    If read_only=True, we show a read-only table.
    """
    df = get_portfolio(client_name)
    if df.empty:
        st.warning(f"No portfolio found for '{client_name}'")
        return

    # Recompute 'cours' & 'valorisation' for each row using the current 'stocks' data
    for i, row in df.iterrows():
        current_price_row = stocks.loc[stocks["valeur"] == row["valeur"]]
        if not current_price_row.empty:
            live_price = current_price_row["cours"].values[0]
        else:
            # fallback if not found
            live_price = 0.0
        df.at[i, "cours"] = live_price
        df.at[i, "valorisation"] = row["quantité"] * live_price

    total_value = df["valorisation"].sum()

    # Store 'poids' as numeric float
    df["poids"] = ((df["valorisation"] / total_value) * 100).round(2) if total_value else 0

    st.subheader(f"📜 Portfolio for {client_name}")
    st.write(f"**Valorisation totale du portefeuille:** {total_value:.2f}")

    if read_only:
        # Read-only
        st.dataframe(df[["valeur", "quantité", "cours", "valorisation", "poids"]], use_container_width=True)
    else:
        # data_editor for editing quantity
        edited_df = st.data_editor(
            df[["valeur", "quantité", "cours", "valorisation", "poids"]],
            use_container_width=True,
            column_config={
                "poids": st.column_config.NumberColumn("Poids (%)", format="%.2f", step=0.01),
                "valorisation": st.column_config.NumberColumn("Valorisation", format="%.2f"),
                "cours": st.column_config.NumberColumn("Cours", format="%.2f"),
                "quantité": st.column_config.NumberColumn("Quantité")
            },
            key=f"pf_editor_{client_name}"
        )

        # Save changes
        if st.button(f"💾 Save Portfolio Changes ({client_name})", key=f"save_btn_{client_name}"):
            # Only 'quantité' is stored in DB. 'cours' & 'valorisation' are always recalculated.
            for index, row in edited_df.iterrows():
                # Update the DB with the new 'quantité' only
                client.table("portfolios").update({
                    "quantité": row["quantité"]
                }).eq("client_id", get_client_id(client_name)).eq("valeur", row["valeur"]).execute()
            st.success(f"Portfolio updated for '{client_name}'!")
            st.experimental_rerun()

        # Add Stock/Cash
        add_stock = st.selectbox(f"Select Stock/Cash to Add ({client_name})", stocks["valeur"].tolist(), key=f"add_s_{client_name}")
        add_qty = st.number_input(f"Quantity for {client_name}", min_value=1, value=1, key=f"qty_s_{client_name}")
        if st.button(f"➕ Add {add_stock} to {client_name}", key=f"btn_add_{client_name}"):
            # We'll store 'cours'/'valorisation' as placeholders; we always recalc from 'stocks'
            client.table("portfolios").insert({
                "client_id": get_client_id(client_name),
                "valeur": add_stock,
                "quantité": add_qty,
                "cours": 0.0,
                "valorisation": 0.0
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
    """
    For each client, we re-fetch their portfolio and dynamically compute
    each row's cours & valorisation from 'stocks', then display read-only.
    """
    clients = get_all_clients()
    if not clients:
        st.warning("No clients found.")
        return

    for cname in clients:
        st.write(f"### Client: {cname}")
        df = get_portfolio(cname)
        if df.empty:
            st.write("No portfolio found for this client.")
            st.write("---")
            continue

        # Recompute using current 'stocks' data
        for i, row in df.iterrows():
            # find current price
            matching_price = stocks.loc[stocks["valeur"] == row["valeur"]]
            price = matching_price["cours"].values[0] if not matching_price.empty else 0.0
            df.at[i, "cours"] = price
            df.at[i, "valorisation"] = row["quantité"] * price

        total_val = df["valorisation"].sum()
        df["poids"] = ((df["valorisation"] / total_val) * 100).round(2) if total_val else 0

        st.dataframe(df[["valeur", "quantité", "cours", "valorisation", "poids"]], use_container_width=True)
        st.write(f"**Valorisation totale du portefeuille:** {total_val:.2f}")
        st.write("---")

# ===================== Inventory Page =====================
def show_inventory():
    """
    Displays a table with:
      - valeur
      - quantité total
      - valorisation ( aggregated across all clients using the current 'stocks' data )
      - poids ( fraction of total sum )
      - portefeuille ( list of clients who hold it )
    Then shows total assets under management.
    """
    clients = get_all_clients()
    if not clients:
        st.warning("No clients found. Please create a client first.")
        return

    master_data = defaultdict(lambda: {"quantity": 0, "clients": set()})
    overall_portfolio_sum = 0.0

    # Accumulate data from all clients' portfolios
    for c in clients:
        df = get_portfolio(c)
        if not df.empty:
            # We'll recalc using 'stocks'
            # sum of this portfolio's dynamic valorisation
            portfolio_val = 0.0
            for _, row in df.iterrows():
                val = row["valeur"]
                qty = row["quantité"]
                # find the up-to-date price
                matching = stocks.loc[stocks["valeur"] == val]
                price = matching["cours"].values[0] if not matching.empty else 0.0
                val_agg = qty * price
                portfolio_val += val_agg

                # Merge quantity
                master_data[val]["quantity"] += qty
                master_data[val]["clients"].add(c)

            overall_portfolio_sum += portfolio_val

    if not master_data:
        st.title("🗃️ Global Inventory")
        st.write("No stocks or cash found in any portfolio.")
        return

    # Build table
    rows_data = []
    sum_of_all_stocks_val = 0.0
    for val, info in master_data.items():
        matching_price = stocks.loc[stocks["valeur"] == val]
        price = matching_price["cours"].values[0] if not matching_price.empty else 0.0
        agg_val = info["quantity"] * price
        sum_of_all_stocks_val += agg_val
        rows_data.append({
            "valeur": val,
            "quantité total": info["quantity"],
            "valorisation": agg_val,
            "portefeuille": ", ".join(sorted(info["clients"]))
        })

    # Now compute poids
    for row in rows_data:
        if sum_of_all_stocks_val > 0:
            row["poids"] = round(row["valorisation"] / sum_of_all_stocks_val * 100, 2)
        else:
            row["poids"] = 0.0

    st.title("🗃️ Global Inventory")
    inv_df = pd.DataFrame(rows_data)
    st.dataframe(
        inv_df[["valeur", "quantité total", "valorisation", "poids", "portefeuille"]],
        use_container_width=True
    )

    st.write(f"### Actif sous gestion: {overall_portfolio_sum:.2f}")

# ===================== Market Page =====================
def show_market():
    """
    Displays the real-time stock/cash data from IDBourse API as a read-only table.
    Refreshes automatically every minute (cached with ttl=60).
    """
    st.title("📈 Market")
    st.write("Below are the current stocks/cash with their real-time prices (refreshed every minute).")
    market_df = get_stock_list()
    st.dataframe(market_df, use_container_width=True)

# ===================== Pages =====================
page = st.sidebar.selectbox(
    "📂 Navigation",
    [
        "Manage Clients",
        "Create Portfolio",
        "View Client Portfolio",
        "View All Portfolios",
        "Inventory",
        "Market"
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

elif page == "Inventory":
    show_inventory()

elif page == "Market":
    show_market()
