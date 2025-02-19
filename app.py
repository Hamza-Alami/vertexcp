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
    Fetch the latest stock/cash prices from IDBourse API, 
    and add 'Cash' with cours=1. 
    """
    try:
        response = requests.get("https://backend.idbourse.com/api_2/get_all_data", timeout=10)
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(
            [(s.get("name", "N/A"), s.get("dernier_cours", 0)) for s in data],
            columns=["valeur", "cours"]
        )
        # Add Cash
        cash_row = pd.DataFrame([{"valeur": "Cash", "cours": 1}])
        return pd.concat([df, cash_row], ignore_index=True)
    except Exception as e:
        st.error(f"Failed to fetch stock data: {e}")
        return pd.DataFrame(columns=["valeur", "cours"])

stocks = get_stock_list()

# ===================== Helpers =====================
def get_all_clients():
    res = client.table("clients").select("*").execute()
    return [r["name"] for r in res.data] if res.data else []

def get_client_info(client_name):
    """Return the entire row from 'clients' for the chosen client, including commission & tax rates."""
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

# ===================== Client Management =====================
def create_client(name):
    if not name:
        st.error("Client name cannot be empty.")
        return
    try:
        client.table("clients").insert({
            "name": name
        }).execute()
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

def update_client_rates(client_name, exchange_comm_rate, is_pea, custom_tax_rate, mgmt_fee):
    """Update client's exchange commission, tax_on_gains_rate, mgmt_fee_rate, etc."""
    cid = get_client_id(client_name)
    if cid:
        # Determine final tax rate: if is_pea, then 0, else custom_tax_rate
        final_tax = 0.0 if is_pea else custom_tax_rate
        client.table("clients").update({
            "exchange_commission_rate": exchange_comm_rate,
            "tax_on_gains_rate": final_tax,
            "is_pea": is_pea,
            "management_fee_rate": mgmt_fee
        }).eq("id", cid).execute()
        st.success(f"Updated rates for {client_name}")
        st.experimental_rerun()
    else:
        st.error("Client not found to update rates.")

# ===================== Portfolio Creation & Storage =====================
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
                "quantité": qty,
                # We'll store vwap, but user can manually set or edit it later
                "vwap": 0.0,
                # We'll store cours/valorisation as placeholders. We'll recalc on the fly
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
            del st.session_state.temp_holdings

# ===================== "BUY" Transaction Helper =====================
def buy_shares(client_name, stock_name, transaction_price, quantity):
    """
    * Recompute cost = (transaction_price * quantity) + (exchange_commission_rate * cost)
    * If stock doesn't exist in portfolio, add it with new vwap
    * If exists, recalc new VWAP
    * Subtract cost from "Cash"
    """
    cinfo = get_client_info(client_name)
    if not cinfo:
        st.error("Client info not found.")
        return

    exchange_rate = cinfo.get("exchange_commission_rate", 0.0) or 0.0

    df = get_portfolio(client_name)
    # cost before commission
    raw_cost = transaction_price * quantity
    # add commission
    commission_cost = raw_cost * (exchange_rate / 100.0)
    total_cost = raw_cost + commission_cost

    # find existing row for the stock
    match = df[df["valeur"] == stock_name]
    if match.empty:
        # new stock position
        new_vwap = transaction_price  # user can override in the data editor
        # insert row
        client.table("portfolios").insert({
            "client_id": get_client_id(client_name),
            "valeur": stock_name,
            "quantité": quantity,
            "vwap": new_vwap,
            "cours": 0.0,
            "valorisation": 0.0
        }).execute()
    else:
        # recalc VWAP
        old_qty = match["quantité"].values[0]
        old_vwap = match["vwap"].values[0]
        old_cost_total = old_qty * old_vwap
        new_cost_total = old_cost_total + total_cost
        new_qty = old_qty + quantity
        new_vwap = new_cost_total / new_qty

        # update DB with new quantity & new vwap
        client.table("portfolios").update({
            "quantité": new_qty,
            "vwap": new_vwap
        }).eq("client_id", get_client_id(client_name)).eq("valeur", stock_name).execute()

    # Subtract from "Cash"
    # If "Cash" doesn't exist, create it
    cash_row = df[df["valeur"] == "Cash"]
    if cash_row.empty:
        # create with negative quantity as placeholders?
        client.table("portfolios").insert({
            "client_id": get_client_id(client_name),
            "valeur": "Cash",
            "quantité": -total_cost,  # negative indicates we used that much
            "vwap": 1.0
        }).execute()
    else:
        old_cash_qty = cash_row["quantité"].values[0]
        new_cash_qty = old_cash_qty - total_cost
        client.table("portfolios").update({
            "quantité": new_cash_qty
        }).eq("client_id", get_client_id(client_name)).eq("valeur", "Cash").execute()

    st.success(f"Bought {quantity} of {stock_name} at {transaction_price:.2f} + comm => total {total_cost:.2f}")
    st.experimental_rerun()

# ===================== "SELL" Transaction Helper =====================
def sell_shares(client_name, stock_name, transaction_price, quantity):
    """
    * If user holds that stock in portfolio with vwap, 
      net proceed = (transaction_price * quantity) - commission - taxesIfProfit
    * Commission = exchange_comm_rate * proceed
    * If net profit, tax it at tax_on_gains_rate
    * Update stock quantity & possibly remove if zero
    * Add net proceed to "Cash"
    """
    cinfo = get_client_info(client_name)
    if not cinfo:
        st.error("Client info not found.")
        return

    exchange_rate = cinfo.get("exchange_commission_rate", 0.0) or 0.0
    tax_rate = cinfo.get("tax_on_gains_rate", 15.0) or 15.0  # or 0 if is_pea

    df = get_portfolio(client_name)
    match = df[df["valeur"] == stock_name]
    if match.empty:
        st.error(f"Client does not hold {stock_name}. Can't sell.")
        return

    old_qty = match["quantité"].values[0]
    if quantity > old_qty:
        st.error(f"Cannot sell {quantity} shares. Only hold {old_qty}.")
        return

    old_vwap = match["vwap"].values[0]
    cost_total = old_vwap * old_qty  # total cost at old vwap
    # but we only sell part => cost portion = quantity * vwap ?

    # transaction proceeds before commission
    raw_proceeds = transaction_price * quantity
    # commission
    commission = raw_proceeds * (exchange_rate / 100.0)
    net_proceeds = raw_proceeds - commission

    # see if we have a net profit vs cost portion
    # cost portion for the shares being sold = quantity * old_vwap
    cost_of_those_shares = quantity * old_vwap
    potential_profit = net_proceeds - cost_of_those_shares

    if potential_profit > 0:
        # apply tax
        tax = potential_profit * (tax_rate / 100.0)
        net_proceeds_after_tax = net_proceeds - tax
        net_proceeds = net_proceeds_after_tax
    # if negative or zero, no tax

    # update the quantity of that stock
    new_qty = old_qty - quantity
    if new_qty == 0:
        # remove the row
        client.table("portfolios").delete().eq("client_id", get_client_id(client_name)).eq("valeur", stock_name).execute()
    else:
        # update quantity, vwap remains the same for the leftover shares
        client.table("portfolios").update({
            "quantité": new_qty
        }).eq("client_id", get_client_id(client_name)).eq("valeur", stock_name).execute()

    # add net proceeds to "Cash"
    cash_row = df[df["valeur"] == "Cash"]
    if cash_row.empty:
        # create row with the net proceeds
        client.table("portfolios").insert({
            "client_id": get_client_id(client_name),
            "valeur": "Cash",
            "quantité": net_proceeds,
            "vwap": 1.0
        }).execute()
    else:
        old_cash_qty = cash_row["quantité"].values[0]
        new_cash_qty = old_cash_qty + net_proceeds
        client.table("portfolios").update({
            "quantité": new_cash_qty
        }).eq("client_id", get_client_id(client_name)).eq("valeur", "Cash").execute()

    st.success(f"Sold {quantity} of {stock_name} at {transaction_price:.2f}. Net proceeds {net_proceeds:.2f}.")
    st.experimental_rerun()

# ===================== Show Single Portfolio =====================
def show_portfolio(client_name, read_only=False):
    """
    Display or edit a single portfolio. Now includes VWAP, cost_total, plus-value latente columns, 
    and 'Buy'/'Sell' buttons if not read_only.
    """
    df = get_portfolio(client_name)
    if df.empty:
        st.warning(f"No portfolio found for '{client_name}'")
        return

    # Recompute current "cours" from 'stocks' so user sees live prices
    for i, row in df.iterrows():
        match = stocks[stocks["valeur"] == row["valeur"]]
        live_price = match["cours"].values[0] if not match.empty else 0.0
        df.at[i, "cours"] = live_price
        # 'valorisation' = quantity * cours
        df.at[i, "valorisation"] = row["quantité"] * live_price
        # cost_total = quantity * vwap
        cost_total = row["quantité"] * row.get("vwap", 0.0)
        df.at[i, "cost_total"] = cost_total
        # plus-value latente = valorisation - cost_total
        plusv = (row["quantité"] * live_price) - cost_total
        df.at[i, "plus_value_latente"] = plusv

    total_value = df["valorisation"].sum()
    # 'poids' as numeric
    df["poids"] = ((df["valorisation"] / total_value) * 100).round(2) if total_value else 0

    st.subheader(f"📜 Portfolio for {client_name}")
    st.write(f"**Valorisation totale du portefeuille:** {total_value:.2f}")

    # Add columns for colorizing plus_value_latente
    def color_pl(val):
        """Return style color for plus-value latente."""
        if val > 0:
            return "color: green;"
        elif val < 0:
            return "color: red;"
        else:
            return ""

    if read_only:
        # read-only display
        st.dataframe(df[["valeur", "quantité", "vwap", "cours", "cost_total", "valorisation", "plus_value_latente", "poids"]], use_container_width=True)
    else:
        # editable data editor
        edited_df = st.data_editor(
            df[["valeur", "quantité", "vwap", "cours", "cost_total", "valorisation", "plus_value_latente", "poids"]],
            use_container_width=True,
            column_config={
                "poids": st.column_config.NumberColumn("Poids (%)", format="%.2f", step=0.01),
                "valorisation": st.column_config.NumberColumn("Valorisation", format="%.2f"),
                "cours": st.column_config.NumberColumn("Cours", format="%.2f"),
                "vwap": st.column_config.NumberColumn("VWAP", format="%.2f"),
                "cost_total": st.column_config.NumberColumn("Coût Total", format="%.2f"),
                "plus_value_latente": st.column_config.NumberColumn("Plus-Value Latente", format="%.2f")
            },
            key=f"pf_editor_{client_name}"
        )
        # "Save" the changes to the DB (for 'quantity', 'vwap') 
        # We'll recalc cost_total, plus_value latente, etc on the next refresh
        if st.button(f"💾 Save Portfolio Changes for {client_name}", key=f"save_btn_{client_name}"):
            for index, row in edited_df.iterrows():
                # update 'quantity', 'vwap' in DB
                client.table("portfolios").update({
                    "quantité": row["quantité"],
                    "vwap": row["vwap"]
                }).eq("client_id", get_client_id(client_name)).eq("valeur", row["valeur"]).execute()
            st.success(f"Portfolio updated for '{client_name}'!")
            st.experimental_rerun()

        # Buy button
        st.write("### Buy Transaction")
        buy_stock = st.selectbox(f"Stock to BUY for {client_name}", stocks["valeur"].tolist(), key=f"buy_s_{client_name}")
        buy_price = st.number_input(f"Buy Price for {buy_stock}", min_value=0.0, value=0.0, step=0.01, key=f"buy_price_{client_name}")
        buy_qty = st.number_input(f"Buy Quantity for {buy_stock}", min_value=1, value=1, key=f"buy_qty_{client_name}")
        if st.button(f"BUY {buy_stock}", key=f"buy_btn_{client_name}"):
            buy_shares(client_name, buy_stock, buy_price, buy_qty)

        # Sell button
        st.write("### Sell Transaction")
        # only allow selling stocks that exist in the portfolio (and are not "Cash")
        existing_stocks = df[df["valeur"] != "Cash"]["valeur"].unique().tolist()
        sell_stock = st.selectbox(f"Stock to SELL for {client_name}", existing_stocks, key=f"sell_s_{client_name}")
        sell_price = st.number_input(f"Sell Price for {sell_stock}", min_value=0.0, value=0.0, step=0.01, key=f"sell_price_{client_name}")
        sell_qty = st.number_input(f"Sell Quantity for {sell_stock}", min_value=1, value=1, key=f"sell_qty_{client_name}")
        if st.button(f"SELL {sell_stock}", key=f"sell_btn_{client_name}"):
            sell_shares(client_name, sell_stock, sell_price, sell_qty)

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
    Now also uses the dynamic approach. 
    We recalc 'valorisation' for each stock from the sum of 'quantity' * live price across all clients,
    then compute 'poids' from total.
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
            portfolio_val = 0.0
            for _, row in df.iterrows():
                val = row["valeur"]
                qty = row["quantité"]
                # find current price
                match = stocks[stocks["valeur"] == val]
                price = match["cours"].values[0] if not match.empty else 0.0
                val_agg = qty * price
                portfolio_val += val_agg

                master_data[val]["quantity"] += qty
                master_data[val]["clients"].add(c)

            overall_portfolio_sum += portfolio_val

    if not master_data:
        st.title("🗃️ Global Inventory")
        st.write("No stocks or cash found in any portfolio.")
        return

    # Build the inventory table
    rows_data = []
    sum_of_all_stocks_val = 0.0

    for val, info in master_data.items():
        match = stocks[stocks["valeur"] == val]
        price = match["cours"].values[0] if not match.empty else 0.0
        agg_val = info["quantity"] * price
        sum_of_all_stocks_val += agg_val

        rows_data.append({
            "valeur": val,
            "quantité total": info["quantity"],
            "valorisation": agg_val,
            "portefeuille": ", ".join(sorted(info["clients"]))
        })

    # now compute poids
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

# ===================== "Manage Client's Commission & Fees" Page? (Inside Manage Clients) =====================
# We'll add an inline form inside Manage Clients that sets exchange_commission_rate, tax, mgmt_fee, is_pea
def set_client_rates_page():
    st.write("### Set Commissions / Taxes / Fees for a Client")
    existing = get_all_clients()
    if not existing:
        st.warning("No clients to set rates for. Create one first.")
        return

    with st.form("set_rates_form", clear_on_submit=True):
        client_choice = st.selectbox("Select Client to Set Rates", existing, key="set_rates_client_choice")
        exch_comm = st.number_input("Exchange Commission Rate (%)", min_value=0.0, value=0.0, step=0.01)
        mgmt_fee = st.number_input("Management Fee Rate (%)", min_value=0.0, value=0.0, step=0.01)
        pea_option = st.checkbox("Is PEA (Tax exempt)?")
        custom_tax = st.number_input("Custom Tax on Gains (%)", min_value=0.0, value=15.0, step=0.01)
        if st.form_submit_button("Set Rates"):
            update_client_rates(client_choice, exch_comm, pea_option, custom_tax, mgmt_fee)

# ===================== PAGES =====================
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

    # 1) Create Clients
    with st.form("add_client_form", clear_on_submit=True):
        new_client_name = st.text_input("New Client Name", key="new_client_input")
        if st.form_submit_button("➕ Add Client"):
            create_client(new_client_name)

    # 2) If clients exist, we rename / delete
    if existing:
        with st.form("rename_client_form", clear_on_submit=True):
            rename_choice = st.selectbox("Select Client to Rename", options=existing, key="rename_choice")
            rename_new = st.text_input("New Client Name", key="rename_text")
            if st.form_submit_button("✏️ Rename Client"):
                rename_client(rename_choice, rename_new)

        with st.form("delete_client_form", clear_on_submit=True):
            delete_choice = st.selectbox("Select Client to Delete", options=existing, key="delete_choice")
            if st.form_submit_button("🗑️ Delete Client"):
                delete_client(delete_choice)

        # 3) Set client rates
        set_client_rates_page()

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
