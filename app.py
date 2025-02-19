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
        # Add CASH row
        cash_row = pd.DataFrame([{"valeur": "Cash", "cours": 1}])
        return pd.concat([df, cash_row], ignore_index=True)
    except Exception as e:
        st.error(f"Failed to fetch stock data: {e}")
        return pd.DataFrame(columns=["valeur", "cours"])

stocks = get_stock_list()

# ===================== Load Instruments for Poids Masi =====================
def get_instruments():
    """
    Return a DataFrame [instrument_name, nombre_de_titres, facteur_flottant]
    from the 'instruments' table in Supabase.
    """
    res = client.table("instruments").select("*").execute()
    if not res.data:
        return pd.DataFrame(columns=["instrument_name","nombre_de_titres","facteur_flottant"])
    df = pd.DataFrame(res.data)
    needed_cols = ["instrument_name","nombre_de_titres","facteur_flottant"]
    for col in needed_cols:
        if col not in df.columns:
            df[col] = None
    return df[needed_cols].copy()

def compute_poids_masi():
    """
    Builds a dictionary: { valeur_name: {"capitalisation":X, "poids_masi":Y}, ... }
      - "capitalisation" = cours * nombre_de_titres
      - "poids_masi" = (cours * nombre_de_titres * facteur_flottant) / sum_of_all(...) * 100
    We rely on the 'instruments' table + your 'stocks' (API).
    """
    instruments_df = get_instruments()
    if instruments_df.empty:
        return {}

    # rename instrument_name to 'valeur' to merge with the 'stocks' DataFrame
    instr_renamed = instruments_df.rename(columns={"instrument_name":"valeur"})
    # merge on 'valeur'
    merged = pd.merge(instr_renamed, stocks, on="valeur", how="left")
    # fill missing if no match
    merged["cours"] = merged["cours"].fillna(0.0).astype(float)
    merged["nombre_de_titres"] = merged["nombre_de_titres"].astype(float)
    merged["facteur_flottant"] = merged["facteur_flottant"].astype(float)

    merged["capitalisation"] = merged["cours"] * merged["nombre_de_titres"]
    # floated portion for Poids Masi
    merged["floated_cap"] = merged["capitalisation"] * merged["facteur_flottant"]
    total_floated_cap = merged["floated_cap"].sum()

    if total_floated_cap <= 0:
        merged["poids_masi"] = 0.0
    else:
        merged["poids_masi"] = (merged["floated_cap"] / total_floated_cap)*100.0

    outdict = {}
    for _, row in merged.iterrows():
        val = row["valeur"]
        outdict[val] = {
            "capitalisation": row["capitalisation"],
            "poids_masi": row["poids_masi"]
        }
    return outdict

# We'll compute once globally. Recompute if you prefer each time:
poids_masi_map = compute_poids_masi()

# ===================== Helper Functions ========================
def get_all_clients():
    res = client.table("clients").select("*").execute()
    return [r["name"] for r in res.data] if res.data else []

def get_client_info(client_name):
    res = client.table("clients").select("*").eq("name", client_name).execute()
    if res.data:
        return res.data[0]
    return None

def get_client_id(client_name):
    cinfo = get_client_info(client_name)
    if not cinfo:
        return None
    return int(cinfo["id"])

def client_has_portfolio(client_name):
    cid = get_client_id(client_name)
    if cid is None:
        return False
    port = client.table("portfolios").select("*").eq("client_id", cid).execute()
    return len(port.data) > 0

def get_portfolio(client_name):
    cid = get_client_id(client_name)
    if cid is None:
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
    if cid is None:
        st.error("Client not found.")
        return
    try:
        client.table("clients").update({"name": new_name}).eq("id", cid).execute()
        st.success(f"Renamed '{old_name}' to '{new_name}'")
        st.experimental_rerun()
    except Exception as e:
        st.error(f"Error renaming client: {e}")

def delete_client(cname):
    cid = get_client_id(cname)
    if cid is None:
        st.error("Client not found.")
        return
    try:
        client.table("clients").delete().eq("id", cid).execute()
        st.success(f"Deleted client '{cname}'")
        st.experimental_rerun()
    except Exception as e:
        st.error(f"Error deleting client: {e}")

def update_client_rates(client_name, exchange_comm, is_pea, custom_tax, mgmt_fee):
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client not found to update rates.")
        return
    try:
        final_tax = 0.0 if is_pea else float(custom_tax)
        client.table("clients").update({
            "exchange_commission_rate": float(exchange_comm),
            "tax_on_gains_rate": final_tax,
            "is_pea": is_pea,
            "management_fee_rate": float(mgmt_fee)
        }).eq("id", cid).execute()
        st.success(f"Updated rates for {client_name}")
        st.experimental_rerun()
    except Exception as e:
        st.error(f"Error updating client rates: {e}")

# ===================== Portfolio Creation =====================
def create_portfolio_rows(client_name, holdings):
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client not found.")
        return

    if client_has_portfolio(client_name):
        st.warning(f"Client '{client_name}' already has a portfolio.")
        return

    rows = []
    for stock, qty in holdings.items():
        if qty > 0:
            rows.append({
                "client_id": cid,
                "valeur": str(stock),
                "quantité": float(qty),
                "vwap": 0.0,
                "cours": 0.0,
                "valorisation": 0.0
            })
    if not rows:
        st.warning("No stocks or cash provided.")
        return

    try:
        client.table("portfolios").upsert(rows, on_conflict="client_id,valeur").execute()
        st.success(f"Portfolio created for '{client_name}'!")
        st.experimental_rerun()
    except Exception as e:
        st.error(f"Error creating portfolio: {e}")

def new_portfolio_creation_ui(client_name):
    st.subheader(f"➕ Add Initial Holdings for {client_name}")
    if "temp_holdings" not in st.session_state:
        st.session_state.temp_holdings = {}

    new_stock = st.selectbox(f"Select Stock/Cash for {client_name}", stocks["valeur"].tolist(), key=f"new_stock_{client_name}")
    qty = st.number_input(f"Quantity for {client_name}", min_value=1.0, value=1.0, step=0.01, key=f"new_qty_{client_name}")

    if st.button(f"➕ Add {new_stock}", key=f"add_btn_{client_name}"):
        st.session_state.temp_holdings[new_stock] = float(qty)
        st.success(f"Added {qty} of {new_stock}")

    if st.session_state.temp_holdings:
        st.write("### Current Selections:")
        df_hold = pd.DataFrame([
            {"valeur": k, "quantité": v} for k, v in st.session_state.temp_holdings.items()
        ])
        st.dataframe(df_hold, use_container_width=True)

        if st.button(f"💾 Create Portfolio for {client_name}", key=f"create_pf_btn_{client_name}"):
            create_portfolio_rows(client_name, st.session_state.temp_holdings)
            del st.session_state.temp_holdings

# ===================== "Buy" Transaction =====================
def buy_shares(client_name, stock_name, transaction_price, quantity):
    cinfo = get_client_info(client_name)
    if not cinfo:
        st.error("Client info not found.")
        return
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client not found.")
        return

    df = get_portfolio(client_name)
    exchange_rate = float(cinfo.get("exchange_commission_rate", 0.0))

    raw_cost = transaction_price * quantity
    commission = raw_cost * (exchange_rate/100.0)
    cost_with_comm = raw_cost + commission

    # check Cash
    cash_match = df[df["valeur"]=="Cash"]
    current_cash = 0.0
    if not cash_match.empty:
        current_cash = float(cash_match["quantité"].values[0])
    if cost_with_comm>current_cash:
        st.error(f"Insufficient cash. You have {current_cash:.2f}, need {cost_with_comm:.2f}.")
        return

    match = df[df["valeur"]==stock_name]
    if match.empty:
        # new row
        new_vwap = cost_with_comm/quantity
        try:
            client.table("portfolios").upsert([{
                "client_id": cid,
                "valeur": str(stock_name),
                "quantité": quantity,
                "vwap": new_vwap,
                "cours": 0.0,
                "valorisation": 0.0
            }], on_conflict="client_id,valeur").execute()
        except Exception as e:
            st.error(f"Error adding new stock: {e}")
            return
    else:
        old_qty = float(match["quantité"].values[0])
        old_vwap = float(match["vwap"].values[0])
        old_cost = old_qty*old_vwap
        new_cost = old_cost+cost_with_comm
        new_qty = old_qty+quantity
        new_vwap = new_cost/new_qty if new_qty>0 else 0.0
        try:
            client.table("portfolios").update({
                "quantité": new_qty,
                "vwap": new_vwap
            }).eq("client_id", cid).eq("valeur", str(stock_name)).execute()
        except Exception as e:
            st.error(f"Error updating existing stock: {e}")
            return

    # update Cash
    if cash_match.empty:
        try:
            client.table("portfolios").upsert([{
                "client_id": cid,
                "valeur": "Cash",
                "quantité": current_cash-cost_with_comm,
                "vwap": 1.0,
                "cours": 0.0,
                "valorisation": 0.0
            }], on_conflict="client_id,valeur").execute()
        except Exception as e:
            st.error(f"Error creating cash row: {e}")
            return
    else:
        new_cash = current_cash-cost_with_comm
        try:
            client.table("portfolios").update({
                "quantité": new_cash,
                "vwap": 1.0
            }).eq("client_id", cid).eq("valeur", "Cash").execute()
        except Exception as e:
            st.error(f"Error updating cash: {e}")
            return

    st.success(f"Bought {quantity} of {stock_name} at {transaction_price:.2f}, total cost {cost_with_comm:.2f} (incl. commission)")
    st.experimental_rerun()

# ===================== "Sell" Transaction =====================
def sell_shares(client_name, stock_name, transaction_price, quantity):
    cinfo = get_client_info(client_name)
    if not cinfo:
        st.error("Client info not found.")
        return
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client not found.")
        return

    exchange_rate = float(cinfo.get("exchange_commission_rate", 0.0))
    tax_rate = float(cinfo.get("tax_on_gains_rate", 15.0))

    df = get_portfolio(client_name)
    match = df[df["valeur"]==stock_name]
    if match.empty:
        st.error(f"Client does not hold {stock_name}.")
        return

    old_qty = float(match["quantité"].values[0])
    if quantity>old_qty:
        st.error(f"Cannot sell {quantity}, only {old_qty} available.")
        return

    old_vwap = float(match["vwap"].values[0])
    raw_proceeds = transaction_price*quantity
    commission = raw_proceeds*(exchange_rate/100.0)
    net_proceeds = raw_proceeds-commission

    cost_of_shares = old_vwap*quantity
    profit = net_proceeds-cost_of_shares
    if profit>0:
        tax = profit*(tax_rate/100.0)
        net_proceeds-=tax

    new_qty = old_qty-quantity
    try:
        if new_qty<=0:
            client.table("portfolios").delete().eq("client_id", cid).eq("valeur", str(stock_name)).execute()
        else:
            client.table("portfolios").update({
                "quantité": new_qty
            }).eq("client_id", cid).eq("valeur", str(stock_name)).execute()
    except Exception as e:
        st.error(f"Error updating stock after sell: {e}")
        return

    # update Cash
    cash_match = df[df["valeur"]=="Cash"]
    old_cash = 0.0
    if not cash_match.empty:
        old_cash = float(cash_match["quantité"].values[0])
    new_cash = old_cash+net_proceeds

    try:
        if cash_match.empty:
            client.table("portfolios").upsert([{
                "client_id": cid,
                "valeur": "Cash",
                "quantité": new_cash,
                "vwap": 1.0,
                "cours": 0.0,
                "valorisation": 0.0
            }], on_conflict="client_id,valeur").execute()
        else:
            client.table("portfolios").update({
                "quantité": new_cash,
                "vwap": 1.0
            }).eq("client_id", cid).eq("valeur", "Cash").execute()
    except Exception as e:
        st.error(f"Error updating cash after sell: {e}")
        return

    st.success(f"Sold {quantity} of {stock_name} at {transaction_price:.2f}, net {net_proceeds:.2f}.")
    st.experimental_rerun()

# ===================== Show Single Portfolio =====================
def show_portfolio(client_name, read_only=False):
    global poids_masi_map  # from compute_poids_masi

    cid = get_client_id(client_name)
    if cid is None:
        st.warning("Client not found.")
        return
    df = get_portfolio(client_name)
    if df.empty:
        st.warning(f"No portfolio found for '{client_name}'")
        return

    df = df.copy()
    if "quantité" in df.columns:
        df["quantité"] = df["quantité"].astype(float)

    for i, row in df.iterrows():
        val = str(row["valeur"])
        match = stocks[stocks["valeur"]==val]
        live_price = float(match["cours"].values[0]) if not match.empty else 0.0
        df.at[i,"cours"] = live_price
        qty_ = float(row["quantité"])
        vw_ = float(row.get("vwap",0.0))
        val_ = round(qty_*live_price, 2)
        df.at[i,"valorisation"] = val_
        cost_ = round(qty_*vw_,2)
        df.at[i,"cost_total"] = cost_
        df.at[i,"performance_latente"] = round(val_-cost_,2)

        # Poids Masi: if "Cash" => 0, else from poids_masi_map
        if val=="Cash":
            df.at[i,"poids_masi"] = 0.0
        else:
            info = poids_masi_map.get(val, {"poids_masi":0.0})
            df.at[i,"poids_masi"] = info["poids_masi"]

    total_val = df["valorisation"].sum()
    if total_val>0:
        df["poids"] = ((df["valorisation"]/total_val)*100).round(2)
    else:
        df["poids"] = 0.0

    # put "Cash" at bottom
    df["__cash_marker"] = df["valeur"].apply(lambda x: 1 if x=="Cash" else 0)
    df.sort_values("__cash_marker", inplace=True, ignore_index=True)

    st.subheader(f"📜 Portfolio for {client_name}")
    st.write(f"**Valorisation totale du portefeuille:** {total_val:.2f}")

    if read_only:
        drop_cols = ["id","client_id","is_cash","__cash_marker"]
        for c in drop_cols:
            if c in df.columns:
                df.drop(columns=c, inplace=True)
        columns_display = ["valeur","quantité","vwap","cours","cost_total","valorisation","performance_latente","poids","poids_masi"]
        available_cols = [x for x in columns_display if x in df.columns]
        df_display = df[available_cols].copy()

        def color_perf(x):
            if isinstance(x,(float,int)) and x>0:
                return "color:green;"
            elif isinstance(x,(float,int)) and x<0:
                return "color:red;"
            return ""
        def bold_cash(row):
            if row["valeur"]=="Cash":
                return ["font-weight:bold;"]*len(row)
            return ["" for _ in row]

        df_styled = df_display.style.format(
            "{:.2f}",
            subset=["quantité","vwap","cours","cost_total","valorisation","performance_latente","poids","poids_masi"]
        ).applymap(color_perf, subset=["performance_latente"]) \
         .apply(bold_cash, axis=1)
        st.dataframe(df_styled, use_container_width=True)
        return

    # not read_only => same approach
    with st.expander(f"Edit Commission/Taxes/Fees for {client_name}", expanded=False):
        cinfo = get_client_info(client_name)
        if cinfo:
            exch = float(cinfo.get("exchange_commission_rate") or 0.0)
            mgf = float(cinfo.get("management_fee_rate") or 0.0)
            pea = bool(cinfo.get("is_pea") or False)
            tax = float(cinfo.get("tax_on_gains_rate") or 15.0)
            new_exch = st.number_input(f"Exchange Commission Rate (%) - {client_name}", min_value=0.0, value=exch, step=0.01, key=f"exch_{client_name}")
            new_mgmt = st.number_input(f"Management Fee Rate (%) - {client_name}", min_value=0.0, value=mgf, step=0.01, key=f"mgf_{client_name}")
            new_pea = st.checkbox(f"Is {client_name} PEA (Tax Exempt)?", value=pea, key=f"pea_{client_name}")
            new_tax = st.number_input(f"Tax on Gains (%) - {client_name}", min_value=0.0, value=tax, step=0.01, key=f"tax_{client_name}")
            if st.button(f"Update Client Rates - {client_name}", key=f"update_rates_{client_name}"):
                update_client_rates(client_name, new_exch, new_pea, new_tax, new_mgmt)

    columns_display = ["valeur","quantité","vwap","cours","cost_total","valorisation","performance_latente","poids_masi","poids","__cash_marker"]
    df = df[columns_display].copy()

    def color_perf(x):
        if isinstance(x, (float,int)) and x>0:
            return "color:green;"
        elif isinstance(x,(float,int)) and x<0:
            return "color:red;"
        return ""
    def bold_cash(row):
        if row["valeur"]=="Cash":
            return ["font-weight:bold;"]*len(row)
        return ["" for _ in row]

    df_styled = df.drop(columns="__cash_marker").style.format(
        "{:.2f}",
        subset=["quantité","vwap","cours","cost_total","valorisation","performance_latente","poids_masi","poids"]
    ).applymap(color_perf, subset=["performance_latente"]) \
     .apply(bold_cash, axis=1)

    st.write("#### Current Holdings (Poids Masi shown, 0% if Cash)")
    st.dataframe(df_styled, use_container_width=True)

    with st.expander("Manual Edits (Quantity / VWAP)", expanded=False):
        edit_cols = ["valeur","quantité","vwap"]
        edf = df[edit_cols].drop(columns="__cash_marker", errors="ignore").copy()
        updated_df = st.data_editor(
            edf,
            use_container_width=True,
            key=f"portfolio_editor_{client_name}",
            column_config={
                "quantité": st.column_config.NumberColumn("Quantité", format="%.2f", step=0.01),
                "vwap": st.column_config.NumberColumn("VWAP", format="%.4f", step=0.001),
            }
        )
        if st.button(f"💾 Save Edits (Quantity / VWAP) for {client_name}", key=f"save_edits_btn_{client_name}"):
            for idx, row2 in updated_df.iterrows():
                valn = str(row2["valeur"])
                qn = float(row2["quantité"])
                vw = float(row2["vwap"])
                try:
                    client.table("portfolios").update({
                        "quantité": qn,
                        "vwap": vw
                    }).eq("client_id", get_client_id(client_name)).eq("valeur", valn).execute()
                except Exception as e:
                    st.error(f"Error saving edits for {valn}: {e}")
            st.success(f"Portfolio updated for '{client_name}'!")
            st.experimental_rerun()

    # BUY
    st.write("### Buy Transaction")
    buy_stock = st.selectbox(f"Stock to BUY for {client_name}", stocks["valeur"].tolist(), key=f"buy_s_{client_name}")
    buy_price = st.number_input(f"Buy Price for {buy_stock}", min_value=0.0, value=0.0, step=0.01, key=f"buy_price_{client_name}")
    buy_qty = st.number_input(f"Buy Quantity for {buy_stock}", min_value=1.0, value=1.0, step=0.01, key=f"buy_qty_{client_name}")
    if st.button(f"BUY {buy_stock}", key=f"buy_btn_{client_name}"):
        buy_shares(client_name, buy_stock, buy_price, buy_qty)

    # SELL
    st.write("### Sell Transaction")
    existing_stocks = df[df["valeur"]!="Cash"]["valeur"].unique().tolist()
    sell_stock = st.selectbox(f"Stock to SELL for {client_name}", existing_stocks, key=f"sell_s_{client_name}")
    sell_price = st.number_input(f"Sell Price for {sell_stock}", min_value=0.0, value=0.0, step=0.01, key=f"sell_price_{client_name}")
    sell_qty = st.number_input(f"Sell Quantity for {sell_stock}", min_value=1.0, value=1.0, step=0.01, key=f"sell_qty_{client_name}")
    if st.button(f"SELL {sell_stock}", key=f"sell_btn_{client_name}"):
        sell_shares(client_name, sell_stock, sell_price, sell_qty)

# ===================== Show All Portfolios =====================
def show_all_portfolios():
    """
    We show each client's portfolio in read_only mode,
    removing columns if present, sorting so that Cash is at bottom, etc.
    """
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

    master_data = defaultdict(lambda: {"quantity":0.0,"clients":set()})
    overall_portfolio_sum = 0.0

    for c in clients:
        df = get_portfolio(c)
        if not df.empty:
            portfolio_val = 0.0
            for _, row in df.iterrows():
                val = str(row["valeur"])
                qty = float(row["quantité"])
                match = stocks[stocks["valeur"]==val]
                price = float(match["cours"].values[0]) if not match.empty else 0.0
                val_agg = qty*price
                portfolio_val += val_agg
                master_data[val]["quantity"]+=qty
                master_data[val]["clients"].add(c)
            overall_portfolio_sum+=portfolio_val

    if not master_data:
        st.title("🗃️ Global Inventory")
        st.write("No stocks or cash found in any portfolio.")
        return

    rows_data=[]
    sum_of_all_stocks_val=0.0
    for val,info in master_data.items():
        match = stocks[stocks["valeur"]==val]
        price = float(match["cours"].values[0]) if not match.empty else 0.0
        agg_val = info["quantity"]*price
        sum_of_all_stocks_val += agg_val
        rows_data.append({
            "valeur": val,
            "quantité total": info["quantity"],
            "valorisation": agg_val,
            "portefeuille": ", ".join(sorted(info["clients"]))
        })
    for row in rows_data:
        if sum_of_all_stocks_val>0:
            row["poids"] = round((row["valorisation"]/sum_of_all_stocks_val)*100,2)
        else:
            row["poids"] = 0.0

    st.title("🗃️ Global Inventory")
    inv_df = pd.DataFrame(rows_data)
    st.dataframe(
        inv_df[["valeur","quantité total","valorisation","poids","portefeuille"]],
        use_container_width=True
    )
    st.write(f"### Actif sous gestion: {overall_portfolio_sum:.2f}")

# ===================== Market Page (with Capitalisation, Poids Masi) =====================
def show_market():
    st.title("📈 Market")
    st.write("Below are the current stocks/cash with real-time prices, plus Capitalisation & Poids Masi.")

    # Recompute if needed or use global
    market_map = compute_poids_masi()
    if not market_map:
        st.warning("No instruments found or no matching data. Please check DB.")
        return

    # Build rows
    rows=[]
    for val,info in market_map.items():
        rows.append({
            "valeur": val,
            "Capitalisation": info["capitalisation"],
            "Poids Masi": info["poids_masi"]
        })
    df_market = pd.DataFrame(rows)
    # Merge with 'stocks' to get cours
    df_market = pd.merge(df_market, stocks, on="valeur", how="left")
    df_market.rename(columns={"cours":"Cours"}, inplace=True)

    # reorder columns
    df_market = df_market[["valeur","Cours","Capitalisation","Poids Masi"]]

    def style_poids(x):
        return ""

    df_styled = df_market.style.format(
        subset=["Cours","Capitalisation","Poids Masi"],
        formatter="{:.2f}"
    ).applymap(style_poids, subset=["Poids Masi"])
    st.dataframe(df_styled, use_container_width=True)

# ===================== Page Routing =====================
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
