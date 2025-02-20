# pages.py
import streamlit as st
import pandas as pd
from collections import defaultdict

from db_utils import (
    get_all_clients,
    create_client,
    rename_client,
    delete_client,
    update_client_rates,
    get_portfolio,
    get_client_info,
    get_client_id,
    client_has_portfolio,
)
from logic import (
    buy_shares,
    sell_shares,
    new_portfolio_creation_ui,
    poids_masi_map,  # global dict from logic
)
from db_utils import fetch_stocks
from db_utils import get_portfolio as db_get_portfolio

def page_manage_clients():
    st.title("👤 Manage Clients")
    existing= get_all_clients()

    with st.form("add_client_form", clear_on_submit=True):
        new_client_name= st.text_input("New Client Name", key="new_client_input")
        if st.form_submit_button("➕ Add Client"):
            create_client(new_client_name)
    if existing:
        # rename
        with st.form("rename_client_form", clear_on_submit=True):
            rename_choice= st.selectbox("Select Client to Rename", options=existing, key="rename_choice")
            rename_new= st.text_input("New Client Name", key="rename_text")
            if st.form_submit_button("✏️ Rename Client"):
                rename_client(rename_choice, rename_new)
        # delete
        with st.form("delete_client_form", clear_on_submit=True):
            delete_choice= st.selectbox("Select Client to Delete", options=existing, key="delete_choice")
            if st.form_submit_button("🗑️ Delete Client"):
                delete_client(delete_choice)

def page_create_portfolio():
    st.title("📊 Create Client Portfolio")
    clist= get_all_clients()
    if not clist:
        st.warning("No clients found. Please create a client first.")
    else:
        cselect= st.selectbox("Select Client", clist, key="create_pf_select")
        if cselect:
            if client_has_portfolio(cselect):
                st.warning(f"Client '{cselect}' already has a portfolio. Go to 'View Client Portfolio' to edit.")
            else:
                new_portfolio_creation_ui(cselect)

def show_portfolio(client_name, read_only=False):
    """
    The single portfolio display logic from your original code.
    """
    cid= get_client_id(client_name)
    if cid is None:
        st.warning("Client not found.")
        return
    df= db_get_portfolio(client_name)
    if df.empty:
        st.warning(f"No portfolio found for '{client_name}'")
        return

    stocks= fetch_stocks()
    df= df.copy()
    if "quantité" in df.columns:
        df["quantité"] = df["quantité"].astype(float)

    # Recompute columns
    for i, row in df.iterrows():
        val= str(row["valeur"])
        match= stocks[stocks["valeur"]==val]
        live_price= float(match["cours"].values[0]) if not match.empty else 0.0
        df.at[i,"cours"]= live_price
        qty_= float(row["quantité"])
        vw_= float(row.get("vwap",0.0))
        val_ = round(qty_* live_price,2)
        df.at[i,"valorisation"]= val_
        cost_= round(qty_* vw_,2)
        df.at[i,"cost_total"]= cost_
        df.at[i,"performance_latente"]= round(val_ - cost_,2)
        # Poids masi
        if val=="Cash":
            df.at[i,"poids_masi"]= 0.0
        else:
            info= poids_masi_map.get(val, {"poids_masi":0.0})
            df.at[i,"poids_masi"]= info["poids_masi"]

    total_val= df["valorisation"].sum()
    if total_val>0:
        df["poids"]= ((df["valorisation"]/ total_val)*100).round(2)
    else:
        df["poids"]= 0.0

    df["__cash_marker"]= df["valeur"].apply(lambda x: 1 if x=="Cash" else 0)
    df.sort_values("__cash_marker", inplace=True, ignore_index=True)

    st.subheader(f"📜 Portfolio for {client_name}")
    st.write(f"**Valorisation totale du portefeuille:** {total_val:.2f}")

    if read_only:
        drop_cols=["id","client_id","is_cash","__cash_marker"]
        for c in drop_cols:
            if c in df.columns:
                df.drop(columns=c, inplace=True)
        columns_display=["valeur","quantité","vwap","cours","cost_total","valorisation","performance_latente","poids","poids_masi"]
        avail_cols= [x for x in columns_display if x in df.columns]
        df_display= df[avail_cols].copy()

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
        df_styled= df_display.style.format(
            "{:.2f}",
            subset=["quantité","vwap","cours","cost_total","valorisation","performance_latente","poids","poids_masi"]
        ).applymap(color_perf, subset=["performance_latente"]) \
         .apply(bold_cash, axis=1)
        st.dataframe(df_styled, use_container_width=True)
        return

    # not read_only => show advanced
    with st.expander(f"Edit Commission/Taxes/Fees for {client_name}", expanded=False):
        from db_utils import get_client_info, update_client_rates
        cinfo= get_client_info(client_name)
        if cinfo:
            exch= float(cinfo.get("exchange_commission_rate") or 0.0)
            mgf= float(cinfo.get("management_fee_rate") or 0.0)
            pea= bool(cinfo.get("is_pea") or False)
            tax= float(cinfo.get("tax_on_gains_rate") or 15.0)
            new_exch= st.number_input(f"Exchange Commission Rate (%) - {client_name}", min_value=0.0, value=exch, step=0.01, key=f"exch_{client_name}")
            new_mgmt= st.number_input(f"Management Fee Rate (%) - {client_name}", min_value=0.0, value=mgf, step=0.01, key=f"mgf_{client_name}")
            new_pea= st.checkbox(f"Is {client_name} PEA (Tax Exempt)?", value=pea, key=f"pea_{client_name}")
            new_tax= st.number_input(f"Tax on Gains (%) - {client_name}", min_value=0.0, value=tax, step=0.01, key=f"tax_{client_name}")
            if st.button(f"Update Client Rates - {client_name}", key=f"update_rates_{client_name}"):
                update_client_rates(client_name, new_exch, new_pea, new_tax, new_mgmt)

    columns_display=["valeur","quantité","vwap","cours","cost_total","valorisation","performance_latente","poids_masi","poids","__cash_marker"]
    df= df[columns_display].copy()

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

    df_styled= df.drop(columns="__cash_marker").style.format(
        "{:.2f}",
        subset=["quantité","vwap","cours","cost_total","valorisation","performance_latente","poids_masi","poids"]
    ).applymap(color_perf, subset=["performance_latente"]) \
     .apply(bold_cash, axis=1)

    st.write("#### Current Holdings (Poids Masi shown, 0% if Cash)")
    st.dataframe(df_styled, use_container_width=True)

    # Manual Edits
    with st.expander("Manual Edits (Quantity / VWAP)", expanded=False):
        edit_cols=["valeur","quantité","vwap"]
        edf= df[edit_cols].drop(columns="__cash_marker", errors="ignore").copy()
        updated_df= st.data_editor(
            edf,
            use_container_width=True,
            key=f"portfolio_editor_{client_name}",
        )
        if st.button(f"💾 Save Edits (Quantity / VWAP) for {client_name}", key=f"save_edits_btn_{client_name}"):
            from db_utils import portfolio_table
            for idx,row2 in updated_df.iterrows():
                valn= str(row2["valeur"])
                qn= float(row2["quantité"])
                vw= float(row2["vwap"])
                from db_utils import get_client_id
                cid2= get_client_id(client_name)
                try:
                    portfolio_table().update({
                        "quantité":qn,
                        "vwap":vw
                    }).eq("client_id", cid2).eq("valeur", valn).execute()
                except Exception as e:
                    st.error(f"Error saving edits for {valn}: {e}")
            st.success(f"Portfolio updated for '{client_name}'!")
            st.experimental_rerun()

    # BUY
    st.write("### Buy Transaction")
    from logic import buy_shares
    from db_utils import fetch_stocks
    _stocks= fetch_stocks()
    buy_stock= st.selectbox(f"Stock to BUY for {client_name}", _stocks["valeur"].tolist(), key=f"buy_s_{client_name}")
    buy_price= st.number_input(f"Buy Price for {buy_stock}", min_value=0.0, value=0.0, step=0.01, key=f"buy_price_{client_name}")
    buy_qty= st.number_input(f"Buy Quantity for {buy_stock}", min_value=1.0, value=1.0, step=0.01, key=f"buy_qty_{client_name}")
    if st.button(f"BUY {buy_stock}", key=f"buy_btn_{client_name}"):
        buy_shares(client_name, buy_stock, buy_price, buy_qty)

    # SELL
    st.write("### Sell Transaction")
    import numpy as np
    existing_stocks= df[df["valeur"]!="Cash"]["valeur"].unique().tolist()
    sell_stock= st.selectbox(f"Stock to SELL for {client_name}", existing_stocks, key=f"sell_s_{client_name}")
    sell_price= st.number_input(f"Sell Price for {sell_stock}", min_value=0.0, value=0.0, step=0.01, key=f"sell_price_{client_name}")
    sell_qty= st.number_input(f"Sell Quantity for {sell_stock}", min_value=1.0, value=1.0, step=0.01, key=f"sell_qty_{client_name}")
    from logic import sell_shares
    if st.button(f"SELL {sell_stock}", key=f"sell_btn_{client_name}"):
        sell_shares(client_name, sell_stock, sell_price, sell_qty)

def page_view_client_portfolio():
    st.title("📊 View Client Portfolio")
    c2= get_all_clients()
    if not c2:
        st.warning("No clients found. Please create a client first.")
    else:
        client_selected= st.selectbox("Select Client", c2, key="view_portfolio_select")
        if client_selected:
            show_portfolio(client_selected, read_only=False)

def page_view_all_portfolios():
    st.title("📊 All Clients' Portfolios")
    clients= get_all_clients()
    if not clients:
        st.warning("No clients found.")
        return
    for cname in clients:
        st.write(f"### Client: {cname}")
        show_portfolio(cname, read_only=True)
        st.write("---")

def page_inventory():
    st.title("🗃️ Global Inventory")
    from db_utils import get_all_clients, get_portfolio, fetch_stocks
    import math

    clients= get_all_clients()
    if not clients:
        st.warning("No clients found.")
        return

    from collections import defaultdict
    master_data= defaultdict(lambda: {"quantity":0.0,"clients":set()})
    overall_portfolio_sum= 0.0
    stocks= fetch_stocks()

    for c in clients:
        df= get_portfolio(c)
        if not df.empty:
            portfolio_val= 0.0
            for _, row in df.iterrows():
                val= str(row["valeur"])
                qty= float(row["quantité"])
                match= stocks[stocks["valeur"]== val]
                price= float(match["cours"].values[0]) if not match.empty else 0.0
                val_agg= qty*price
                portfolio_val+= val_agg
                master_data[val]["quantity"]+= qty
                master_data[val]["clients"].add(c)
            overall_portfolio_sum+= portfolio_val

    if not master_data:
        st.write("No stocks or cash found in any portfolio.")
        return

    rows_data=[]
    sum_of_all_stocks_val=0.0
    for val,info in master_data.items():
        match= stocks[stocks["valeur"]==val]
        price= float(match["cours"].values[0]) if not match.empty else 0.0
        agg_val= info["quantity"]*price
        sum_of_all_stocks_val+= agg_val
        rows_data.append({
            "valeur": val,
            "quantité total": info["quantity"],
            "valorisation": agg_val,
            "portefeuille": ", ".join(sorted(info["clients"]))
        })
    for row in rows_data:
        if sum_of_all_stocks_val>0:
            row["poids"]= round((row["valorisation"]/sum_of_all_stocks_val)*100,2)
        else:
            row["poids"]= 0.0
    inv_df= pd.DataFrame(rows_data)
    st.dataframe(inv_df[["valeur","quantité total","valorisation","poids","portefeuille"]], use_container_width=True)
    st.write(f"### Actif sous gestion: {overall_portfolio_sum:.2f}")

def page_market():
    st.title("📈 Market")
    from logic import compute_poids_masi, poids_masi_map
    from db_utils import fetch_stocks
    st.write("Below are the current stocks/cash with real-time prices, plus Capitalisation & Poids Masi.")
    m= compute_poids_masi()
    if not m:
        st.warning("No instruments found or no matching data. Please check DB.")
        return
    rows=[]
    stocks= fetch_stocks()
    for val,info in m.items():
        rows.append({
            "valeur": val,
            "Capitalisation": info["capitalisation"],
            "Poids Masi": info["poids_masi"]
        })
    df_market= pd.DataFrame(rows)
    df_market= pd.merge(df_market, stocks, on="valeur", how="left")
    df_market.rename(columns={"cours":"Cours"}, inplace=True)
    df_market= df_market[["valeur","Cours","Capitalisation","Poids Masi"]]
    df_styled= df_market.style.format(
        subset=["Cours","Capitalisation","Poids Masi"], formatter="{:.2f}"
    )
    st.dataframe(df_styled, use_container_width=True)
