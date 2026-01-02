import json
from datetime import date

import streamlit as st
import pandas as pd

import db_utils
from db_utils import (
    get_portfolio,
    get_client_info,
    get_client_id,
    portfolio_table,
    fetch_instruments,
    fetch_stocks,
    client_has_portfolio,
)


######################################################
#     Real-time MASI Fetch (safe)
######################################################

def get_current_masi():
    try:
        return float(db_utils.fetch_masi_from_cb())
    except Exception as e:
        st.error(f"Erreur récupération MASI: {e}")
        return 0.0


######################################################
#  Poids MASI
######################################################

def compute_poids_masi():
    try:
        instruments_df = fetch_instruments()
    except Exception as e:
        st.error(f"Erreur récupération instruments Supabase: {e}")
        return {}

    if instruments_df.empty:
        return {}

    try:
        stocks_df = fetch_stocks()
    except Exception as e:
        st.error(f"Erreur récupération des cours: {e}")
        return {}

    instr_renamed = instruments_df.rename(columns={"instrument_name": "valeur"})
    merged = pd.merge(instr_renamed, stocks_df, on="valeur", how="left")

    merged["cours"] = merged["cours"].fillna(0.0).astype(float)
    merged["nombre_de_titres"] = merged["nombre_de_titres"].fillna(0.0).astype(float)
    merged["facteur_flottant"] = merged["facteur_flottant"].fillna(0.0).astype(float)

    merged = merged[(merged["cours"] != 0.0) & (merged["nombre_de_titres"] != 0.0)].copy()

    merged["capitalisation"] = merged["cours"] * merged["nombre_de_titres"]
    merged["floated_cap"] = merged["capitalisation"] * merged["facteur_flottant"]
    tot_floated = merged["floated_cap"].sum()

    if tot_floated <= 0:
        merged["poids_masi"] = 0.0
    else:
        merged["poids_masi"] = (merged["floated_cap"] / tot_floated) * 100.0

    outdict = {}
    for _, row in merged.iterrows():
        val = row["valeur"]
        outdict[val] = {
            "capitalisation": float(row["capitalisation"]),
            "poids_masi": float(row["poids_masi"])
        }
    return outdict


@st.cache_data(ttl=300)
def get_poids_masi_map():
    return compute_poids_masi()


######################################################
#   Create a brand-new portfolio
######################################################

def create_portfolio_rows(client_name: str, holdings: dict):
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client not found.")
        return

    if client_has_portfolio(client_name):
        st.warning(f"Le client '{client_name}' possède déjà un portefeuille.")
        return

    rows = []
    for stock, qty in holdings.items():
        if float(qty) > 0:
            rows.append({
                "client_id": cid,
                "valeur": str(stock),
                "quantité": float(qty),
                "vwap": 0.0,
                "cours": 0.0,
                "valorisation": 0.0
            })

    if not rows:
        st.warning("Aucun actif fourni pour la création du portefeuille.")
        return

    try:
        portfolio_table().upsert(rows, on_conflict="client_id,valeur").execute()
        st.success(f"Portefeuille créé pour '{client_name}'!")
        st.rerun()
    except Exception as e:
        st.error(f"Erreur création du portefeuille: {e}")


def new_portfolio_creation_ui(client_name: str):
    st.subheader(f"➕ Définir les actifs initiaux pour {client_name}")

    if "temp_holdings" not in st.session_state:
        st.session_state.temp_holdings = {}

    try:
        all_stocks = fetch_stocks()
    except Exception as e:
        st.error(f"Erreur chargement stocks: {e}")
        return

    options = all_stocks["valeur"].tolist()
    if "Cash" not in options:
        options = options + ["Cash"]

    chosen_val = st.selectbox(
        "Choisir une valeur",
        options,
        key=f"new_stock_{client_name}"
    )

    qty = st.number_input(
        f"Quantité pour {client_name}",
        min_value=0.0,
        value=1.0,
        step=1.0,
        key=f"new_qty_{client_name}"
    )

    if st.button(f"➕ Ajouter {chosen_val}", key=f"add_btn_{client_name}"):
        st.session_state.temp_holdings[chosen_val] = float(qty)
        st.success(f"Ajouté {qty} de {chosen_val}")

    if st.session_state.temp_holdings:
        st.write("### Actifs Sélectionnés :")
        df_hold = pd.DataFrame([
            {"valeur": k, "quantité": v} for k, v in st.session_state.temp_holdings.items()
        ])
        st.dataframe(df_hold, use_container_width=True)

        if st.button(f"💾 Créer le Portefeuille pour {client_name}", key=f"create_pf_btn_{client_name}"):
            create_portfolio_rows(client_name, st.session_state.temp_holdings)
            del st.session_state.temp_holdings


######################################################
#        Buy / Sell + Transactions log (TPCVM)
######################################################

def buy_shares(client_name: str, stock_name: str, transaction_price: float, quantity: float):
    cinfo = get_client_info(client_name)
    if not cinfo:
        st.error("Informations du client introuvables.")
        return

    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client introuvable.")
        return

    dfp = get_portfolio(client_name)
    snap_before = dfp.to_dict(orient="records") if not dfp.empty else []

    exchange_rate = float(cinfo.get("exchange_commission_rate") or 0.0)

    raw_cost = float(transaction_price) * float(quantity)
    commission = raw_cost * (exchange_rate / 100.0)
    cost_with_comm = raw_cost + commission

    cash_match = dfp[dfp["valeur"].astype(str) == "Cash"]
    current_cash = float(cash_match["quantité"].values[0]) if not cash_match.empty else 0.0
    if cost_with_comm > current_cash:
        st.error(f"Montant insuffisant en Cash: {current_cash:,.2f} < {cost_with_comm:,.2f}")
        return

    match = dfp[dfp["valeur"].astype(str) == stock_name]
    if match.empty:
        new_vwap = cost_with_comm / float(quantity) if quantity > 0 else 0.0
        try:
            portfolio_table().upsert([{
                "client_id": cid,
                "valeur": stock_name,
                "quantité": float(quantity),
                "vwap": float(new_vwap),
                "cours": 0.0,
                "valorisation": 0.0
            }], on_conflict="client_id,valeur").execute()
        except Exception as e:
            st.error(f"Erreur lors de l'ajout de {stock_name}: {e}")
            return
    else:
        old_qty = float(match["quantité"].values[0])
        old_vwap = float(match["vwap"].values[0])
        old_cost = old_qty * old_vwap
        new_cost = old_cost + cost_with_comm
        new_qty = old_qty + float(quantity)
        new_vwap = new_cost / new_qty if new_qty > 0 else 0.0
        try:
            portfolio_table().update({
                "quantité": float(new_qty),
                "vwap": float(new_vwap)
            }).eq("client_id", cid).eq("valeur", stock_name).execute()
        except Exception as e:
            st.error(f"Erreur mise à jour stock {stock_name}: {e}")
            return

    new_cash = current_cash - cost_with_comm
    try:
        portfolio_table().upsert([{
            "client_id": cid,
            "valeur": "Cash",
            "quantité": float(new_cash),
            "vwap": 1.0,
            "cours": 0.0,
            "valorisation": 0.0
        }], on_conflict="client_id,valeur").execute()
    except Exception as e:
        st.error(f"Erreur mise à jour Cash: {e}")
        return

    dfp_after = get_portfolio(client_name)
    snap_after = dfp_after.to_dict(orient="records") if not dfp_after.empty else []

    try:
        db_utils.log_transaction({
            "client_id": cid,
            "trade_date": str(date.today()),
            "side": "BUY",
            "symbol": stock_name,
            "quantity": float(quantity),
            "price": float(transaction_price),
            "gross_amount": float(raw_cost),
            "fees": float(commission),
            "tax_rate_used": 0.0,
            "tpcvm": 0.0,
            "realized_pl": 0.0,
            "net_cash_flow": float(-cost_with_comm),
            "portfolio_snapshot_before": json.dumps(snap_before),
            "portfolio_snapshot_after": json.dumps(snap_after),
        })
    except Exception as e:
        st.warning(f"Achat OK mais log transaction impossible: {e}")

    st.success(
        f"Achat {quantity:.0f} '{stock_name}' @ {transaction_price:,.2f} | "
        f"Total {cost_with_comm:,.2f} (comm: {commission:,.2f})."
    )
    st.rerun()


def sell_shares(client_name: str, stock_name: str, transaction_price: float, quantity: float):
    cinfo = get_client_info(client_name)
    if not cinfo:
        st.error("Informations du client introuvables.")
        return

    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client introuvable.")
        return

    dfp = get_portfolio(client_name)
    snap_before = dfp.to_dict(orient="records") if not dfp.empty else []

    exchange_rate = float(cinfo.get("exchange_commission_rate") or 0.0)
    tax_rate_cfg = float(cinfo.get("tax_on_gains_rate") or 15.0)
    is_pea = bool(cinfo.get("is_pea") or False)

    match = dfp[dfp["valeur"].astype(str) == stock_name]
    if match.empty:
        st.error(f"Le client ne possède pas {stock_name}.")
        return

    old_qty = float(match["quantité"].values[0])
    if float(quantity) > old_qty:
        st.error(f"Quantité insuffisante: vend {quantity}, possède {old_qty}.")
        return

    old_vwap = float(match["vwap"].values[0])

    raw_proceeds = float(transaction_price) * float(quantity)
    commission = raw_proceeds * (exchange_rate / 100.0)
    net_before_tax = raw_proceeds - commission

    cost_basis = old_vwap * float(quantity)
    profit = net_before_tax - cost_basis  # profit réalisé AVANT taxe

    tax_rate_used = 0.0 if is_pea else float(tax_rate_cfg)
    tpcvm = max(0.0, profit) * (tax_rate_used / 100.0)
    net_after_tax = net_before_tax - tpcvm

    new_qty = old_qty - float(quantity)
    try:
        if new_qty <= 0:
            portfolio_table().delete().eq("client_id", cid).eq("valeur", stock_name).execute()
        else:
            portfolio_table().update({"quantité": float(new_qty)}).eq("client_id", cid).eq("valeur", stock_name).execute()
    except Exception as e:
        st.error(f"Erreur mise à jour après vente: {e}")
        return

    cash_match = dfp[dfp["valeur"].astype(str) == "Cash"]
    old_cash = float(cash_match["quantité"].values[0]) if not cash_match.empty else 0.0
    new_cash = old_cash + net_after_tax

    try:
        portfolio_table().upsert([{
            "client_id": cid,
            "valeur": "Cash",
            "quantité": float(new_cash),
            "vwap": 1.0,
            "cours": 0.0,
            "valorisation": 0.0
        }], on_conflict="client_id,valeur").execute()
    except Exception as e:
        st.error(f"Erreur mise à jour Cash: {e}")
        return

    dfp_after = get_portfolio(client_name)
    snap_after = dfp_after.to_dict(orient="records") if not dfp_after.empty else []

    try:
        db_utils.log_transaction({
            "client_id": cid,
            "trade_date": str(date.today()),
            "side": "SELL",
            "symbol": stock_name,
            "quantity": float(quantity),
            "price": float(transaction_price),
            "gross_amount": float(raw_proceeds),
            "fees": float(commission),
            "tax_rate_used": float(tax_rate_used),
            "tpcvm": float(tpcvm),
            "realized_pl": float(profit),
            "net_cash_flow": float(net_after_tax),
            "portfolio_snapshot_before": json.dumps(snap_before),
            "portfolio_snapshot_after": json.dumps(snap_after),
        })
    except Exception as e:
        st.warning(f"Vente OK mais log transaction impossible: {e}")

    st.success(
        f"Vendu {quantity:.0f} '{stock_name}' @ {transaction_price:,.2f} | "
        f"Net {net_after_tax:,.2f} (comm: {commission:,.2f}, TPCVM: {tpcvm:,.2f})."
    )
    st.rerun()
