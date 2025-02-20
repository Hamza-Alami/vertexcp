# logic.py
import streamlit as st
import pandas as pd
from db_utils import get_portfolio, get_client_info, get_client_id, portfolio_table, fetch_instruments, fetch_stocks
from db_utils import client_has_portfolio  # maybe needed
import math

def compute_poids_masi():
    """
    Creates a dictionary { valeur: { "capitalisation": X, "poids_masi": Y }, ...}
    skipping instruments not found in the JSON (cours=0).
    """
    import numpy as np
    instruments_df = fetch_instruments()
    if instruments_df.empty:
        return {}
    stocks = fetch_stocks()

    instr_renamed = instruments_df.rename(columns={"instrument_name":"valeur"})
    merged = pd.merge(instr_renamed, stocks, on="valeur", how="left")
    merged["cours"] = merged["cours"].fillna(0.0).astype(float)

    # Exclude cours=0
    merged = merged[merged["cours"]!=0.0].copy()

    merged["nombre_de_titres"] = merged["nombre_de_titres"].astype(float)
    merged["facteur_flottant"] = merged["facteur_flottant"].astype(float)

    merged["capitalisation"] = merged["cours"]*merged["nombre_de_titres"]
    merged["floated_cap"] = merged["capitalisation"]*merged["facteur_flottant"]
    total_floated = merged["floated_cap"].sum()
    if total_floated<=0:
        merged["poids_masi"] = 0.0
    else:
        merged["poids_masi"] = (merged["floated_cap"]/total_floated)*100.0

    outdict={}
    for _, row in merged.iterrows():
        val = row["valeur"]
        outdict[val] = {
            "capitalisation": row["capitalisation"],
            "poids_masi": row["poids_masi"]
        }
    return outdict

# We'll store a global map for Masi
poids_masi_map = compute_poids_masi()

def create_portfolio_rows(client_name, holdings):
    from db_utils import portfolio_table, get_client_id
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client not found.")
        return

    if client_has_portfolio(client_name):
        st.warning(f"Client '{client_name}' already has a portfolio.")
        return

    rows = []
    for stock, qty in holdings.items():
        if qty>0:
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
        portfolio_table().upsert(rows, on_conflict="client_id,valeur").execute()
        st.success(f"Portfolio created for '{client_name}'!")
        st.rerun()
    except Exception as e:
        st.error(f"Error creating portfolio: {e}")

def new_portfolio_creation_ui(client_name):
    """
    Lets the user pick stocks & quantities for a brand-new portfolio for 'client_name'.
    """
    from db_utils import fetch_stocks
    stocks = fetch_stocks()

    st.subheader(f"➕ Add Initial Holdings for {client_name}")
    if "temp_holdings" not in st.session_state:
        st.session_state.temp_holdings={}
    new_stock = st.selectbox(f"Select Stock/Cash for {client_name}", stocks["valeur"].tolist(), key=f"new_stock_{client_name}")
    qty = st.number_input(f"Quantity for {client_name}", min_value=1.0, value=1.0, step=0.01, key=f"new_qty_{client_name}")

    if st.button(f"➕ Add {new_stock}", key=f"add_btn_{client_name}"):
        st.session_state.temp_holdings[new_stock]=float(qty)
        st.success(f"Added {qty} of {new_stock}")

    if st.session_state.temp_holdings:
        st.write("### Current Selections:")
        df_hold = pd.DataFrame([
            {"valeur":k, "quantité":v} for k,v in st.session_state.temp_holdings.items()
        ])
        st.dataframe(df_hold, use_container_width=True)

        if st.button(f"💾 Create Portfolio for {client_name}", key=f"create_pf_btn_{client_name}"):
            create_portfolio_rows(client_name, st.session_state.temp_holdings)
            del st.session_state.temp_holdings

def buy_shares(client_name, stock_name, transaction_price, quantity):
    from db_utils import get_portfolio, get_client_info, get_client_id, portfolio_table
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

    raw_cost = transaction_price*quantity
    commission = raw_cost*(exchange_rate/100.0)
    cost_with_comm = raw_cost+commission

    # check Cash
    cash_match = df[df["valeur"]=="Cash"]
    current_cash = 0.0
    if not cash_match.empty:
        current_cash = float(cash_match["quantité"].values[0])
    if cost_with_comm>current_cash:
        st.error(f"Insufficient cash: Have {current_cash:.2f}, need {cost_with_comm:.2f}.")
        return

    match = df[df["valeur"]==stock_name]
    if match.empty:
        new_vwap = cost_with_comm/quantity
        try:
            portfolio_table().upsert([{
                "client_id": cid,
                "valeur": str(stock_name),
                "quantité": quantity,
                "vwap": new_vwap,
                "cours":0.0,
                "valorisation":0.0
            }], on_conflict="client_id,valeur").execute()
        except Exception as e:
            st.error(f"Error adding new stock: {e}")
            return
    else:
        old_qty = float(match["quantité"].values[0])
        old_vwap= float(match["vwap"].values[0])
        old_cost = old_qty*old_vwap
        new_cost = old_cost+cost_with_comm
        new_qty = old_qty+quantity
        new_vwap= new_cost/new_qty if new_qty>0 else 0.0
        try:
            portfolio_table().update({
                "quantité": new_qty,
                "vwap": new_vwap
            }).eq("client_id", cid).eq("valeur",str(stock_name)).execute()
        except Exception as e:
            st.error(f"Error updating existing stock: {e}")
            return

    # update Cash
    if cash_match.empty:
        try:
            portfolio_table().upsert([{
                "client_id": cid,
                "valeur":"Cash",
                "quantité": current_cash-cost_with_comm,
                "vwap":1.0,
                "cours":0.0,
                "valorisation":0.0
            }], on_conflict="client_id,valeur").execute()
        except Exception as e:
            st.error(f"Error creating cash row: {e}")
            return
    else:
        new_cash = current_cash-cost_with_comm
        try:
            portfolio_table().update({
                "quantité": new_cash,
                "vwap":1.0
            }).eq("client_id", cid).eq("valeur","Cash").execute()
        except Exception as e:
            st.error(f"Error updating cash: {e}")
            return
    st.success(f"Bought {quantity} of {stock_name} @ {transaction_price:.2f} => cost {cost_with_comm:.2f}")
    st.rerun()

def sell_shares(client_name, stock_name, transaction_price, quantity):
    from db_utils import get_portfolio, get_client_info, get_client_id, portfolio_table
    cinfo= get_client_info(client_name)
    if not cinfo:
        st.error("Client info not found.")
        return
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client not found.")
        return
    exchange_rate= float(cinfo.get("exchange_commission_rate",0.0))
    tax_rate= float(cinfo.get("tax_on_gains_rate",15.0))
    df= get_portfolio(client_name)
    match= df[df["valeur"]==stock_name]
    if match.empty:
        st.error(f"Client does not hold {stock_name}.")
        return
    old_qty= float(match["quantité"].values[0])
    if quantity> old_qty:
        st.error(f"Cannot sell {quantity}, only {old_qty} available.")
        return
    old_vwap= float(match["vwap"].values[0])
    raw_proceeds= transaction_price*quantity
    commission= raw_proceeds*(exchange_rate/100.0)
    net_proceeds= raw_proceeds-commission
    cost_of_shares= old_vwap*quantity
    profit= net_proceeds-cost_of_shares
    if profit>0:
        tax= profit*(tax_rate/100.0)
        net_proceeds-=tax
    new_qty= old_qty-quantity
    try:
        if new_qty<=0:
            portfolio_table().delete().eq("client_id",cid).eq("valeur", str(stock_name)).execute()
        else:
            portfolio_table().update({"quantité":new_qty}).eq("client_id",cid).eq("valeur",str(stock_name)).execute()
    except Exception as e:
        st.error(f"Error updating stock after sell: {e}")
        return

    # update Cash
    cash_match= df[df["valeur"]=="Cash"]
    old_cash= 0.0
    if not cash_match.empty:
        old_cash= float(cash_match["quantité"].values[0])
    new_cash= old_cash+ net_proceeds

    try:
        if cash_match.empty:
            portfolio_table().upsert([{
                "client_id":cid,
                "valeur":"Cash",
                "quantité": new_cash,
                "vwap":1.0,
                "cours":0.0,
                "valorisation":0.0
            }], on_conflict="client_id,valeur").execute()
        else:
            portfolio_table().update({
                "quantité": new_cash,
                "vwap":1.0
            }).eq("client_id", cid).eq("valeur","Cash").execute()
    except Exception as e:
        st.error(f"Error updating cash after sell: {e}")
        return
    st.success(f"Sold {quantity} of {stock_name} => net {net_proceeds:.2f}")
    st.rerun()
