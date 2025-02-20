# pages.py

import streamlit as st
import pandas as pd
import numpy as np
from collections import defaultdict

# Import db_utils as a module (rather than from ... import get_client_id)
import db_utils
from db_utils import (
    get_all_clients,
    create_client,
    rename_client,
    delete_client,
    update_client_rates,
    client_has_portfolio,   # we still want this one individually
)
from logic import (
    buy_shares,
    sell_shares,
    new_portfolio_creation_ui,
    poids_masi_map  # the global dict for Poids Masi
)

########################################
# 1) Manage Clients Page
########################################
def page_manage_clients():
    st.title("👤 Manage Clients")
    existing = get_all_clients()

    # Create Client form
    with st.form("add_client_form", clear_on_submit=True):
        new_client_name = st.text_input("New Client Name", key="new_client_input")
        if st.form_submit_button("➕ Add Client"):
            create_client(new_client_name)

    # If clients exist, allow rename/delete
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


########################################
# 2) Create Portfolio Page
########################################
def page_create_portfolio():
    st.title("📊 Create Client Portfolio")
    clist = get_all_clients()
    if not clist:
        st.warning("No clients found. Please create a client first.")
    else:
        cselect = st.selectbox("Select Client", clist, key="create_pf_select")
        if cselect:
            # check if client already has a portfolio
            if client_has_portfolio(cselect):
                st.warning(f"Client '{cselect}' already has a portfolio. Go to 'View Client Portfolio' to edit.")
            else:
                new_portfolio_creation_ui(cselect)


########################################
# 3) Show Single Portfolio
########################################
def show_portfolio(client_name, read_only=False):
    """
    Displays a single client's portfolio, either read_only or in full editing mode.
    Moved from the original single-file code. 
    Now references db_utils.get_client_id, db_utils.get_portfolio to avoid overshadowing.
    """
    cid = db_utils.get_client_id(client_name)  # <--- fully-qualified call
    if cid is None:
        st.warning("Client not found.")
        return

    df = db_utils.get_portfolio(client_name)   # <--- fully-qualified call
    if df.empty:
        st.warning(f"No portfolio found for '{client_name}'")
        return

    # fetch current stock prices
    stocks = db_utils.fetch_stocks()

    df = df.copy()
    if "quantité" in df.columns:
        df["quantité"] = df["quantité"].astype(float)

    # Recompute columns 
    for i, row in df.iterrows():
        val = str(row["valeur"])
        match = stocks[stocks["valeur"] == val]
        live_price = float(match["cours"].values[0]) if not match.empty else 0.0
        df.at[i, "cours"] = live_price

        qty_ = float(row["quantité"])
        vw_  = float(row.get("vwap", 0.0))

        val_ = round(qty_ * live_price, 2)
        df.at[i, "valorisation"] = val_

        cost_ = round(qty_ * vw_, 2)
        df.at[i, "cost_total"] = cost_

        df.at[i, "performance_latente"] = round(val_ - cost_, 2)

        # Poids Masi: if "Cash" => 0, else from poids_masi_map
        if val == "Cash":
            df.at[i, "poids_masi"] = 0.0
        else:
            info = poids_masi_map.get(val, {"poids_masi": 0.0})
            df.at[i, "poids_masi"] = info["poids_masi"]

    total_val = df["valorisation"].sum()
    if total_val > 0:
        df["poids"] = ((df["valorisation"] / total_val) * 100).round(2)
    else:
        df["poids"] = 0.0

    # ensure "Cash" is at bottom
    df["__cash_marker"] = df["valeur"].apply(lambda x: 1 if x == "Cash" else 0)
    df.sort_values("__cash_marker", inplace=True, ignore_index=True)

    st.subheader(f"📜 Portfolio for {client_name}")
    st.write(f"**Valorisation totale du portefeuille:** {total_val:.2f}")

    # If read-only, display a styled table, no editing
    if read_only:
        drop_cols = ["id", "client_id", "is_cash", "__cash_marker"]
        for c in drop_cols:
            if c in df.columns:
                df.drop(columns=c, inplace=True)

        columns_display = [
            "valeur", "quantité", "vwap", "cours", 
            "cost_total", "valorisation", "performance_latente",
            "poids", "poids_masi"
        ]
        avail_cols = [x for x in columns_display if x in df.columns]
        df_display = df[avail_cols].copy()

        def color_perf(x):
            if isinstance(x, (float,int)) and x > 0:
                return "color:green;"
            elif isinstance(x, (float,int)) and x < 0:
                return "color:red;"
            return ""

        def bold_cash(row):
            if row["valeur"] == "Cash":
                return ["font-weight:bold;"] * len(row)
            return ["" for _ in row]

        df_styled = df_display.style.format(
            "{:.2f}",
            subset=["quantité","vwap","cours","cost_total","valorisation","performance_latente","poids","poids_masi"]
        ).applymap(color_perf, subset=["performance_latente"]) \
         .apply(bold_cash, axis=1)

        st.dataframe(df_styled, use_container_width=True)
        return

    # If not read_only => full editing features (commissions, buy/sell, etc.)
    with st.expander(f"Edit Commission/Taxes/Fees for {client_name}", expanded=False):
        cinfo = db_utils.get_client_info(client_name)
        if cinfo:
            exch = float(cinfo.get("exchange_commission_rate") or 0.0)
            mgf  = float(cinfo.get("management_fee_rate") or 0.0)
            pea  = bool(cinfo.get("is_pea") or False)
            tax  = float(cinfo.get("tax_on_gains_rate") or 15.0)

            new_exch = st.number_input(
                f"Exchange Commission Rate (%) - {client_name}", 
                min_value=0.0, value=exch, step=0.01, key=f"exch_{client_name}"
            )
            new_mgmt = st.number_input(
                f"Management Fee Rate (%) - {client_name}", 
                min_value=0.0, value=mgf, step=0.01, key=f"mgf_{client_name}"
            )
            new_pea  = st.checkbox(
                f"Is {client_name} PEA (Tax Exempt)?",
                value=pea, 
                key=f"pea_{client_name}"
            )
            new_tax = st.number_input(
                f"Tax on Gains (%) - {client_name}", 
                min_value=0.0, value=tax, step=0.01, key=f"tax_{client_name}"
            )

            if st.button(f"Update Client Rates - {client_name}", key=f"update_rates_{client_name}"):
                update_client_rates(client_name, new_exch, new_pea, new_tax, new_mgmt)

    columns_display = [
        "valeur","quantité","vwap","cours","cost_total",
        "valorisation","performance_latente","poids_masi","poids","__cash_marker"
    ]
    df = df[columns_display].copy()

    def color_perf(x):
        if isinstance(x, (float,int)) and x > 0:
            return "color:green;"
        elif isinstance(x, (float,int)) and x < 0:
            return "color:red;"
        return ""

    def bold_cash(row):
        if row["valeur"] == "Cash":
            return ["font-weight:bold;"] * len(row)
        return ["" for _ in row]

    df_styled = df.drop(columns="__cash_marker").style.format(
        "{:.2f}",
        subset=[
            "quantité","vwap","cours","cost_total",
            "valorisation","performance_latente","poids_masi","poids"
        ]
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
        )
        if st.button(f"💾 Save Edits (Quantity / VWAP) for {client_name}", key=f"save_edits_btn_{client_name}"):
            from db_utils import portfolio_table
            cid2 = db_utils.get_client_id(client_name)
            for idx, row2 in updated_df.iterrows():
                valn = str(row2["valeur"])
                qn   = float(row2["quantité"])
                vw   = float(row2["vwap"])
                try:
                    portfolio_table().update({
                        "quantité": qn,
                        "vwap": vw
                    }).eq("client_id", cid2).eq("valeur", valn).execute()
                except Exception as e:
                    st.error(f"Error saving edits for {valn}: {e}")
            st.success(f"Portfolio updated for '{client_name}'!")
            st.rerun()

    # BUY
    st.write("### Buy Transaction")
    from logic import buy_shares
    _stocks = db_utils.fetch_stocks()
    buy_stock = st.selectbox(f"Stock to BUY for {client_name}", _stocks["valeur"].tolist(), key=f"buy_s_{client_name}")
    buy_price = st.number_input(f"Buy Price for {buy_stock}", min_value=0.0, value=0.0, step=0.01, key=f"buy_price_{client_name}")
    buy_qty   = st.number_input(f"Buy Quantity for {buy_stock}", min_value=1.0, value=1.0, step=0.01, key=f"buy_qty_{client_name}")
    if st.button(f"BUY {buy_stock}", key=f"buy_btn_{client_name}"):
        buy_shares(client_name, buy_stock, buy_price, buy_qty)

    # SELL
    st.write("### Sell Transaction")
    existing_stocks = df[df["valeur"] != "Cash"]["valeur"].unique().tolist()
    sell_stock = st.selectbox(f"Stock to SELL for {client_name}", existing_stocks, key=f"sell_s_{client_name}")
    sell_price = st.number_input(f"Sell Price for {sell_stock}", min_value=0.0, value=0.0, step=0.01, key=f"sell_price_{client_name}")
    sell_qty   = st.number_input(f"Sell Quantity for {sell_stock}", min_value=1.0, value=1.0, step=0.01, key=f"sell_qty_{client_name}")
    from logic import sell_shares
    if st.button(f"SELL {sell_stock}", key=f"sell_btn_{client_name}"):
        sell_shares(client_name, sell_stock, sell_price, sell_qty)


########################################
# 4) View Client Portfolio Page
########################################
def page_view_client_portfolio():
    st.title("📊 View Client Portfolio")
    c2 = get_all_clients()
    if not c2:
        st.warning("No clients found. Please create a client first.")
    else:
        client_selected = st.selectbox("Select Client", c2, key="view_portfolio_select")
        if client_selected:
            show_portfolio(client_selected, read_only=False)


########################################
# 5) View All Portfolios Page
########################################
def page_view_all_portfolios():
    st.title("📊 All Clients' Portfolios")
    clients = get_all_clients()
    if not clients:
        st.warning("No clients found.")
        return
    for cname in clients:
        st.write(f"### Client: {cname}")
        show_portfolio(cname, read_only=True)
        st.write("---")


########################################
# 6) Inventory Page
########################################
def page_inventory():
    st.title("🗃️ Global Inventory")

    from db_utils import get_all_clients, get_portfolio, fetch_stocks
    from collections import defaultdict

    clients = get_all_clients()
    if not clients:
        st.warning("No clients found. Please create a client first.")
        return

    master_data = defaultdict(lambda: {"quantity": 0.0, "clients": set()})
    overall_portfolio_sum = 0.0
    stocks = fetch_stocks()

    for c in clients:
        df = get_portfolio(c)
        if not df.empty:
            portfolio_val = 0.0
            for _, row in df.iterrows():
                val = str(row["valeur"])
                qty = float(row["quantité"])
                match = stocks[stocks["valeur"] == val]
                price = float(match["cours"].values[0]) if not match.empty else 0.0
                val_agg = qty * price
                portfolio_val += val_agg
                master_data[val]["quantity"] += qty
                master_data[val]["clients"].add(c)
            overall_portfolio_sum += portfolio_val

    if not master_data:
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
            row["poids"] = round((row["valorisation"] / sum_of_all_stocks_val) * 100, 2)
        else:
            row["poids"] = 0.0

    inv_df = pd.DataFrame(rows_data)
    st.dataframe(
        inv_df[["valeur","quantité total","valorisation","poids","portefeuille"]],
        use_container_width=True
    )
    st.write(f"### Actif sous gestion: {overall_portfolio_sum:.2f}")


########################################
# 7) Market Page
########################################
def page_market():
    st.title("📈 Market")
    st.write("Below are the current stocks/cash with real-time prices, plus Capitalisation & Poids Masi.")

    from logic import compute_poids_masi
    from db_utils import fetch_stocks

    m = compute_poids_masi()
    if not m:
        st.warning("No instruments found or no matching data. Please check DB.")
        return

    rows = []
    stocks = fetch_stocks()
    for val, info in m.items():
        rows.append({
            "valeur": val,
            "Capitalisation": info["capitalisation"],
            "Poids Masi": info["poids_masi"]
        })
    df_market = pd.DataFrame(rows)
    df_market = pd.merge(df_market, stocks, on="valeur", how="left")
    df_market.rename(columns={"cours":"Cours"}, inplace=True)
    df_market = df_market[["valeur","Cours","Capitalisation","Poids Masi"]]

    df_styled = df_market.style.format(
        subset=["Cours","Capitalisation","Poids Masi"],
        formatter="{:.2f}"
    )
    st.dataframe(df_styled, use_container_width=True)

########################################
#  Performance & Fees Page
########################################

def page_performance_fees():
    """
    This page manages performance tracking:
      - You can select a client, add start_date + start_value
      - The code fetches current portfolio value
      - Compares => performance% => fees
      - Also shows a collapsible summary of all clients (their most recent period).
    """
    st.title("📈 Performance & Fees")

    clients = get_all_clients()
    if not clients:
        st.warning("No clients found. Create a client first.")
        return

    client_name = st.selectbox("Select Client", clients, key="perf_fee_select")
    if not client_name:
        st.info("Pick a client to continue.")
        return

    cid = db_utils.get_client_id(client_name)
    if cid is None:
        st.error("No valid client selected.")
        return

    # 1) Let user add / update a performance period
    with st.expander("Add or Update Start Date / Start Value")

    with st.form("perf_period_form", clear_on_submit=True):
        start_date_input = st.date_input("Start Date")
        start_value_input = st.number_input("Start Value", min_value=0.0, step=0.01, value=0.0)
        submitted = st.form_submit_button("Save Performance Period")
        if submitted:
            # Insert a row in performance_periods
            # Convert date_input to string 'YYYY-MM-DD'
            start_date_str = str(start_date_input)
            db_utils.create_performance_period(cid, start_date_str, float(start_value_input))

    # 2) Show all performance_period rows for that client
    st.write("### Existing Performance Periods")
    df_periods = db_utils.get_performance_periods_for_client(cid)
    if df_periods.empty:
        st.info("No performance periods found for this client yet.")
    else:
        # we can display them in descending date order
        st.dataframe(df_periods[["start_date","start_value","created_at"]], use_container_width=True)

    # 3) Let user pick which "start_date" row to compare for the performance
    st.subheader("Compute Performance & Fees for a Chosen Start Date")
    if not df_periods.empty:
        # sort by start_date descending
        df_periods = df_periods.sort_values("start_date", ascending=False)
        start_options = df_periods["start_date"].unique().tolist()
        selected_start_date = st.selectbox("Select a Start Date for Performance Calculation",
                                          start_options, key="calc_perf_startdate")
        row_chosen = df_periods[df_periods["start_date"] == selected_start_date].iloc[0]
        chosen_start_value = float(row_chosen["start_value"])
        
        # 4) fetch client's current total portfolio value
        df_portfolio = db_utils.get_portfolio(client_name)
        if df_portfolio.empty:
            st.warning("Client has no portfolio.")
        else:
            # sum up 'valorisation' if you have it, or compute as in show_portfolio
            # We'll do a simpler approach: just reuse code or logic:
            from db_utils import fetch_stocks
            stocks_df = fetch_stocks()

            # compute total_value
            total_val = 0.0
            for _, prow in df_portfolio.iterrows():
                val = str(prow["valeur"])
                match = stocks_df[stocks_df["valeur"]==val]
                live_price = float(match["cours"].values[0]) if not match.empty else 0.0
                qty_ = float(prow["quantité"])
                val_ = qty_ * live_price
                total_val += val_

            # 5) performance% = (total_val - chosen_start_value) / chosen_start_value * 100
            if chosen_start_value>0:
                gains = total_val - chosen_start_value
                performance_pct = (gains / chosen_start_value)*100.0
            else:
                gains = 0.0
                performance_pct = 0.0

            # 6) mgmt_fee = Gains * mgmt_fee_rate, where mgmt_fee_rate is from client info
            cinfo = db_utils.get_client_info(client_name)
            mgmt_rate = float(cinfo.get("management_fee_rate",0.0))/100.0
            # If you want fees only if gains>0, you can do max(gains,0).
            fees_owed = gains * mgmt_rate
            if fees_owed<0:
                # you can set to 0 if you don't charge negative fees
                fees_owed = 0.0

            # display results
            st.write(f"**Start Value**: {chosen_start_value:,.2f}")
            st.write(f"**Current Value**: {total_val:,.2f}")
            st.write(f"**Performance %**: {performance_pct:,.2f}%")
            st.write(f"**Gains**: {gains:,.2f}")
            st.write(f"**Mgmt Fee Rate**: {cinfo.get('management_fee_rate',0)}%")
            st.write(f"**Fees Owed**: {fees_owed:,.2f}")

    # 7) Collapsible summary => all clients' most recent start date
    with st.expander("Résumé de Performance (all clients)"):
        # We want the "latest" row from performance_periods for each client
        df_latest = db_utils.get_latest_performance_period_for_all_clients()
        if df_latest.empty:
            st.info("No performance data found for any client.")
        else:
            # We'll build a small table: client_name, start_date, start_value, current_value, performance%, fees
            # We'll do a loop over each row in df_latest
            # or gather in a list
            summary_rows = []
            from db_utils import fetch_stocks

            stocks_df = fetch_stocks()

            for _, rrow in df_latest.iterrows():
                c_id = rrow["client_id"]
                start_val = float(rrow["start_value"])
                ddate = str(rrow["start_date"])
                # find client name
                # you may want an inverse mapping or a function
                # but we can do a cheap approach with get_client_info
                cinfo2 = None
                for cname2 in clients:
                    if db_utils.get_client_id(cname2) == c_id:
                        cinfo2 = cname2
                        break
                if not cinfo2:
                    continue

                # compute currentValue
                pdf = db_utils.get_portfolio(cinfo2)
                cur_val = 0.0
                if not pdf.empty:
                    for _, prow2 in pdf.iterrows():
                        val2 = str(prow2["valeur"])
                        mm = stocks_df[stocks_df["valeur"]==val2]
                        lp = float(mm["cours"].values[0]) if not mm.empty else 0.0
                        cur_val += float(prow2["quantité"])* lp

                if start_val>0:
                    gains2 = cur_val - start_val
                    perf2 = (gains2 / start_val)*100.0
                else:
                    gains2 = 0.0
                    perf2 = 0.0

                cinfo_db = db_utils.get_client_info(cinfo2)
                mgmtr = float(cinfo_db.get("management_fee_rate",0))/100.0
                fees2 = gains2* mgmtr
                if fees2<0:
                    fees2=0.0

                summary_rows.append({
                    "Client": cinfo2,
                    "Start Date": ddate,
                    "Start Value": start_val,
                    "Current Value": cur_val,
                    "Performance %": perf2,
                    "Fees": fees2
                })

            if not summary_rows:
                st.info("No valid data to show.")
            else:
                df_sum = pd.DataFrame(summary_rows)
                st.dataframe(df_sum, use_container_width=True)

