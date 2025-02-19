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
    Fetch the latest stock/cash prices from IDBourse API every minute.
    """
    try:
        response = requests.get("https://backend.idbourse.com/api_2/get_all_data", timeout=10)
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(
            [(s.get("name", "N/A"), s.get("dernier_cours", 0)) for s in data],
            columns=["valeur", "cours"]
        )
        # Add Cash as a stock with price=1
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

def get_client_info(client_name):
    """Return the entire row from 'clients' for the chosen client."""
    res = client.table("clients").select("*").eq("name", client_name).execute()
    if res.data:
        return res.data[0]
    return None

def get_client_id(client_name):
    cinfo = get_client_info(client_name)
    return cinfo["id"] if cinfo else None

def client_has_portfolio(client_name):
    cid = get_client_id(client_name)
    if not cid:
        return False
    port = client.table("portfolios").select("*").eq("client_id", cid).execute()
    return len(port.data) > 0

def get_portfolio(client_name):
    cid = get_client_id(client_name)
    if not cid:
        return pd.DataFrame()
    res = client.table("portfolios").select("*").eq("client_id", cid).execute()
    return pd.DataFrame(res.data)

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

def update_client_rates(client_name, exchange_comm, is_pea, custom_tax, mgmt_fee):
    """Update the client's rates in DB, converting to float to avoid TypeError."""
    cid = get_client_id(client_name)
    if cid:
        final_tax = 0.0 if is_pea else float(custom_tax)
        client.table("clients").update({
            "exchange_commission_rate": float(exchange_comm),
            "tax_on_gains_rate": final_tax,
            "is_pea": is_pea,
            "management_fee_rate": float(mgmt_fee)
        }).eq("id", cid).execute()
        st.success(f"Updated rates for {client_name}")
        st.experimental_rerun()
    else:
        st.error("Client not found to update rates.")

# ===================== Portfolio Management =====================
def create_portfolio_rows(client_name, holdings):
    cid = get_client_id(client_name)
    if not cid:
        st.error("Client not found.")
        return

    if client_has_portfolio(client_name):
        st.warning(f"Client '{client_name}' already has a portfolio. Go to 'View Client Portfolio' to edit.")
        return

    rows = []
    for stock, qty in holdings.items():
        if qty > 0:
            rows.append({
                "client_id": cid,
                "valeur": stock,
                "quantité": float(qty),
                "vwap": 0.0,
                "cours": 0.0,
                "valorisation": 0.0
            })
    if rows:
        client.table("portfolios").upsert(rows).execute()
        st.success(f"Portfolio created for '{client_name}'!")
        st.experimental_rerun()
    else:
        st.warning("No stocks or cash provided for portfolio creation.")

# ===================== Create Portfolio UI =====================
def new_portfolio_creation_ui(client_name):
    st.subheader(f"➕ Add Initial Holdings for {client_name}")
    if "temp_holdings" not in st.session_state:
        st.session_state.temp_holdings = {}

    new_stock = st.selectbox(f"Select Stock/Cash for {client_name}", stocks["valeur"].tolist(), key=f"new_stock_{client_name}")
    qty = st.number_input(f"Quantity for {client_name}", min_value=1, value=1, key=f"new_qty_{client_name}")

    if st.button(f"➕ Add {new_stock}", key=f"add_btn_{client_name}"):
        st.session_state.temp_holdings[new_stock] = float(qty)
        st.success(f"Added {qty} of {new_stock}")

    if st.session_state.temp_holdings:
        st.write("### Current Selections:")
        holdings_df = pd.DataFrame([
            {"valeur": k, "quantité": v} for k, v in st.session_state.temp_holdings.items()
        ])
        st.dataframe(holdings_df, use_container_width=True)

        if st.button(f"💾 Create Portfolio for {client_name}", key=f"create_pf_btn_{client_name}"):
            create_portfolio_rows(client_name, st.session_state.temp_holdings)
            del st.session_state.temp_holdings

# ===================== "Buy" Transaction Helper =====================
def buy_shares(client_name, stock_name, transaction_price, quantity):
    """Recalc cost with commission, update or create the position, recalc VWAP, update 'Cash'."""
    cinfo = get_client_info(client_name)
    if not cinfo:
        st.error("Client info not found.")
        return

    exchange_rate = float(cinfo.get("exchange_commission_rate", 0.0))
    df = get_portfolio(client_name)

    raw_cost = float(transaction_price) * float(quantity)
    commission_cost = raw_cost * (exchange_rate / 100.0)
    total_cost = raw_cost + commission_cost

    match = df[df["valeur"] == stock_name]
    if match.empty:
        # new row
        new_vwap = float(transaction_price)
        client.table("portfolios").insert({
            "client_id": get_client_id(client_name),
            "valeur": stock_name,
            "quantité": float(quantity),
            "vwap": float(new_vwap),
            "cours": 0.0,
            "valorisation": 0.0
        }).execute()
    else:
        # recalc VWAP
        old_qty = float(match["quantité"].values[0])
        old_vwap = float(match["vwap"].values[0])
        old_cost_total = old_qty * old_vwap
        new_cost_total = old_cost_total + total_cost
        new_qty = old_qty + float(quantity)
        new_vwap = new_cost_total / new_qty if new_qty else 0.0

        client.table("portfolios").update({
            "quantité": float(new_qty),
            "vwap": float(new_vwap)
        }).eq("client_id", get_client_id(client_name)).eq("valeur", stock_name).execute()

    # update "Cash"
    cash_row = df[df["valeur"] == "Cash"]
    if cash_row.empty:
        # create row
        client.table("portfolios").insert({
            "client_id": get_client_id(client_name),
            "valeur": "Cash",
            "quantité": -float(total_cost),
            "vwap": 1.0,
            "cours": 0.0,
            "valorisation": 0.0
        }).execute()
    else:
        old_cash_qty = float(cash_row["quantité"].values[0])
        new_cash_qty = old_cash_qty - float(total_cost)
        client.table("portfolios").update({
            "quantité": float(new_cash_qty)
        }).eq("client_id", get_client_id(client_name)).eq("valeur", "Cash").execute()

    st.success(f"Bought {quantity} of {stock_name} at {transaction_price:.2f}, total cost {total_cost:.2f}")
    st.experimental_rerun()

# ===================== "Sell" Transaction Helper =====================
def sell_shares(client_name, stock_name, transaction_price, quantity):
    """
    Sell up to existing quantity. If there's net profit, apply tax_on_gains_rate. Always apply commission.
    Add net proceed to 'Cash'.
    """
    cinfo = get_client_info(client_name)
    if not cinfo:
        st.error("Client info not found.")
        return

    exchange_rate = float(cinfo.get("exchange_commission_rate", 0.0))
    tax_rate = float(cinfo.get("tax_on_gains_rate", 15.0))

    df = get_portfolio(client_name)
    match = df[df["valeur"] == stock_name]
    if match.empty:
        st.error(f"Client does not hold {stock_name}.")
        return

    old_qty = float(match["quantité"].values[0])
    if quantity > old_qty:
        st.error(f"Cannot sell {quantity}. Only {old_qty} available.")
        return

    old_vwap = float(match["vwap"].values[0])

    raw_proceeds = float(transaction_price) * float(quantity)
    commission = raw_proceeds * (exchange_rate / 100.0)
    net_proceeds = raw_proceeds - commission

    # cost portion for these shares
    cost_of_shares = float(quantity) * old_vwap
    potential_profit = net_proceeds - cost_of_shares

    if potential_profit > 0:
        # apply tax
        tax = potential_profit * (tax_rate / 100.0)
        net_proceeds -= tax

    # update new quantity
    new_qty = old_qty - float(quantity)
    if new_qty <= 0:
        # remove row
        client.table("portfolios").delete().eq("client_id", get_client_id(client_name)).eq("valeur", stock_name).execute()
    else:
        client.table("portfolios").update({
            "quantité": float(new_qty)
        }).eq("client_id", get_client_id(client_name)).eq("valeur", stock_name).execute()

    # add net proceeds to "Cash"
    cash_row = df[df["valeur"] == "Cash"]
    if cash_row.empty:
        client.table("portfolios").insert({
            "client_id": get_client_id(client_name),
            "valeur": "Cash",
            "quantité": float(net_proceeds),
            "vwap": 1.0,
            "cours": 0.0,
            "valorisation": 0.0
        }).execute()
    else:
        old_cash_qty = float(cash_row["quantité"].values[0])
        new_cash_qty = old_cash_qty + float(net_proceeds)
        client.table("portfolios").update({
            "quantité": float(new_cash_qty)
        }).eq("client_id", get_client_id(client_name)).eq("valeur", "Cash").execute()

    st.success(f"Sold {quantity} of {stock_name} at {transaction_price:.2f}, net {net_proceeds:.2f} after commission/tax.")
    st.experimental_rerun()

# ===================== Show Single Portfolio =====================
def show_portfolio(client_name, read_only=False):
    df = get_portfolio(client_name)
    if df.empty:
        st.warning(f"No portfolio found for '{client_name}'")
        return

    # Recompute cours & valorisation from 'stocks'
    for i, row in df.iterrows():
        match = stocks[stocks["valeur"] == row["valeur"]]
        live_price = float(match["cours"].values[0]) if not match.empty else 0.0
        df.at[i, "cours"] = live_price
        # valorisation = quantity * cours
        df.at[i, "valorisation"] = float(row["quantité"]) * live_price

        cost_tot = float(row["quantité"]) * float(row.get("vwap", 0.0))
        df.at[i, "cost_total"] = cost_tot
        df.at[i, "performance_latente"] = df.at[i, "valorisation"] - cost_tot

    total_value = df["valorisation"].sum()
    df["poids"] = ((df["valorisation"] / total_value) * 100).round(2) if total_value else 0

    st.subheader(f"📜 Portfolio for {client_name}")
    st.write(f"**Valorisation totale du portefeuille:** {total_value:.2f}")

    # Also show the client commissions/taxes so we can edit them here:
    cinfo = get_client_info(client_name)
    if cinfo:
        st.write("#### Client Commission & Fee Setup")
        exch_comm_default = float(cinfo.get("exchange_commission_rate", 0.0))
        mgmt_default = float(cinfo.get("management_fee_rate", 0.0))
        is_pea_default = bool(cinfo.get("is_pea", False))
        tax_default = float(cinfo.get("tax_on_gains_rate", 15.0))

        with st.form(f"client_rates_form_{client_name}", clear_on_submit=True):
            new_exch = st.number_input("Exchange Commission Rate (%)", min_value=0.0, value=exch_comm_default, step=0.01)
            new_mgmt = st.number_input("Management Fee Rate (%)", min_value=0.0, value=mgmt_default, step=0.01)
            new_pea = st.checkbox("Is PEA (Tax Exempt)?", value=is_pea_default)
            new_tax = st.number_input("Custom Tax on Gains (%)", min_value=0.0, value=tax_default, step=0.01)
            if st.form_submit_button("Update Rates"):
                update_client_rates(client_name, new_exch, new_pea, new_tax, new_mgmt)
    else:
        st.write("No client info found to display commissions/fees.")

    if read_only:
        st.dataframe(
            df[["valeur", "quantité", "vwap", "cours", "cost_total", "valorisation", "performance_latente", "poids"]],
            use_container_width=True
        )
    else:
        # data_editor with new columns
        edited_df = st.data_editor(
            df[["valeur", "quantité", "vwap", "cours", "cost_total", "valorisation", "performance_latente", "poids"]],
            use_container_width=True,
            column_config={
                "vwap": st.column_config.NumberColumn("VWAP", format="%.2f"),
                "cost_total": st.column_config.NumberColumn("Coût Total", format="%.2f"),
                "valorisation": st.column_config.NumberColumn("Valorisation", format="%.2f"),
                "performance_latente": st.column_config.NumberColumn("Performance Latente", format="%.2f"),
                "poids": st.column_config.NumberColumn("Poids (%)", format="%.2f", step=0.01)
            },
            key=f"pf_editor_{client_name}"
        )
        if st.button(f"💾 Save Portfolio Changes ({client_name})", key=f"save_btn_{client_name}"):
            for index, row in edited_df.iterrows():
                client.table("portfolios").update({
                    "quantité": float(row["quantité"]),
                    "vwap": float(row["vwap"])
                }).eq("client_id", get_client_id(client_name)).eq("valeur", row["valeur"]).execute()
            st.success(f"Portfolio updated for '{client_name}'!")
            st.experimental_rerun()

        # "Buy" transaction
        st.write("### Buy Transaction")
        buy_stock = st.selectbox(f"Stock to BUY for {client_name}", stocks["valeur"].tolist(), key=f"buy_s_{client_name}")
        buy_price = st.number_input(f"Buy Price for {buy_stock}", min_value=0.0, value=0.0, step=0.01, key=f"buy_price_{client_name}")
        buy_qty = st.number_input(f"Buy Quantity for {buy_stock}", min_value=1, value=1, key=f"buy_qty_{client_name}")
        if st.button(f"BUY {buy_stock}", key=f"buy_btn_{client_name}"):
            buy_shares(client_name, buy_stock, float(buy_price), float(buy_qty))

        # "Sell" transaction
        st.write("### Sell Transaction")
        existing_stocks = df[df["valeur"] != "Cash"]["valeur"].unique().tolist()
        sell_stock = st.selectbox(f"Stock to SELL for {client_name}", existing_stocks, key=f"sell_s_{client_name}")
        sell_price = st.number_input(f"Sell Price for {sell_stock}", min_value=0.0, value=0.0, step=0.01, key=f"sell_price_{client_name}")
        sell_qty = st.number_input(f"Sell Quantity for {sell_stock}", min_value=1, value=1, key=f"sell_qty_{client_name}")
        if st.button(f"SELL {sell_stock}", key=f"sell_btn_{client_name}"):
            sell_shares(client_name, sell_stock, float(sell_price), float(sell_qty))

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
    clients = get_all_clients()
    if not clients:
        st.warning("No clients found. Please create a client first.")
        return

    master_data = defaultdict(lambda: {"quantity": 0, "clients": set()})
    overall_portfolio_sum = 0.0

    for c in clients:
        df = get_portfolio(c)
        if not df.empty:
            portfolio_val = 0.0
            for _, row in df.iterrows():
                val = row["valeur"]
                qty = float(row["quantité"])
                # find current price
                match = stocks[stocks["valeur"] == val]
                price = float(match["cours"].values[0]) if not match.empty else 0.0
                val_agg = qty * price
                portfolio_val += val_agg
                master_data[val]["quantity"] += qty
                master_data[val]["clients"].add(c)
            overall_portfolio_sum += portfolio_val

    if not master_data:
        st.title("🗃️ Global Inventory")
        st.write("No stocks or cash found in any portfolio.")
        return

    rows_data = []
    sum_of_all_stocks_val = 0.0

    for val, info in master_data.items():
        match = stocks[stocks["valeur"] == val]
        price = float(match["cours"].values[0]) if not match.empty else 0.0
        agg_val = info["quantity"] * price
        sum_of_all_stocks_val += agg_val
        rows_data.append({
            "valeur": val,
            "quantité total": info["quantity"],
            "valorisation": agg_val,
            "portefeuille": ", ".join(sorted(info["clients"]))
        })

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

        # We can also set client rates here in an extra form if we want:
        st.write("### Set Client Commission / Tax / Fee")
        with st.form("set_commission_form", clear_on_submit=True):
            pick_client = st.selectbox("Pick Client to set rates", existing, key="pick_client_rates")
            cinfo = get_client_info(pick_client)
            exch = cinfo.get("exchange_commission_rate", 0.0) if cinfo else 0.0
            mgf = cinfo.get("management_fee_rate", 0.0) if cinfo else 0.0
            pea = cinfo.get("is_pea", False) if cinfo else False
            tax = cinfo.get("tax_on_gains_rate", 15.0) if cinfo else 15.0

            new_exch = st.number_input("Exchange Commission (%)", min_value=0.0, value=float(exch), step=0.01)
            new_mgmt = st.number_input("Management Fee Rate (%)", min_value=0.0, value=float(mgf), step=0.01)
            new_pea = st.checkbox("Is PEA (Tax Exempt)?", value=bool(pea))
            new_tax = st.number_input("Tax on Gains (%)", min_value=0.0, value=float(tax), step=0.01)
            if st.form_submit_button("Update Rates"):
                update_client_rates(pick_client, new_exch, new_pea, new_tax, new_mgmt)

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
