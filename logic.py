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
    create_performance_period,
    get_performance_periods_for_client,
    get_latest_performance_period_for_all_clients,
)

######################################################
#     Real-time MASI Fetch
######################################################
def get_current_masi():
    """Return the real-time MASI index from Casablanca Bourse."""
    return db_utils.fetch_masi_from_cb()

######################################################
#  Compute Poids Masi for each "valeur"
######################################################
def compute_poids_masi():
    """
    Creates a dictionary { valeur: {"capitalisation": X, "poids_masi": Y}, ... }
    by merging instruments and stocks data.
    """
    instruments_df = fetch_instruments()
    if instruments_df.empty:
        return {}

    stocks_df = fetch_stocks()
    instr_renamed = instruments_df.rename(columns={"instrument_name": "valeur"})
    merged = pd.merge(instr_renamed, stocks_df, on="valeur", how="left")

    merged["cours"] = merged["cours"].fillna(0.0).astype(float)
    merged["nombre_de_titres"] = merged["nombre_de_titres"].fillna(0.0).astype(float)
    merged["facteur_flottant"] = merged["facteur_flottant"].fillna(0.0).astype(float)

    # Exclude rows with zero values
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
            "capitalisation": row["capitalisation"],
            "poids_masi": row["poids_masi"]
        }
    return outdict

# Global dictionary for Poids Masi
poids_masi_map = compute_poids_masi()

######################################################
#   Create a brand-new portfolio (and UI)
######################################################
def create_portfolio_rows(client_name: str, holdings: dict):
    """
    Upserts rows (valeur -> quantity) into 'portfolios' for a new portfolio.
    """
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client not found.")
        return

    if client_has_portfolio(client_name):
        st.warning(f"Le client '{client_name}' possède déjà un portefeuille.")
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
        st.warning("Aucun actif fourni pour la création du portefeuille.")
        return

    try:
        portfolio_table().upsert(rows, on_conflict="client_id,valeur").execute()
        st.success(f"Portefeuille créé pour '{client_name}'!")
        st.rerun()
    except Exception as e:
        st.error(f"Erreur création du portefeuille: {e}")

def new_portfolio_creation_ui(client_name: str):
    """
    UI to create a new portfolio via st.session_state.
    """
    st.subheader(f"➕ Définir les actifs initiaux pour {client_name}")
    if "temp_holdings" not in st.session_state:
        st.session_state.temp_holdings = {}
    all_stocks = fetch_stocks()
    chosen_val = st.selectbox(f"Choisir une valeur ou 'Cash'", all_stocks["valeur"].tolist(), key=f"new_stock_{client_name}")
    qty = st.number_input(f"Quantité pour {client_name}", min_value=1.0, value=1.0, step=1.0, key=f"new_qty_{client_name}")
    if st.button(f"➕ Ajouter {chosen_val}", key=f"add_btn_{client_name}"):
        st.session_state.temp_holdings[chosen_val] = float(qty)
        st.success(f"Ajouté {qty} de {chosen_val}")
    if st.session_state.temp_holdings:
        df_hold = pd.DataFrame([{"valeur": k, "quantité": v} for k, v in st.session_state.temp_holdings.items()])
        df_hold.reset_index(drop=True, inplace=True)
        st.dataframe(df_hold, use_container_width=True)
        if st.button(f"💾 Créer le Portefeuille pour {client_name}", key=f"create_pf_btn_{client_name}"):
            create_portfolio_rows(client_name, st.session_state.temp_holdings)
            del st.session_state.temp_holdings

######################################################
#        Buy / Sell functions
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
    exchange_rate = float(cinfo.get("exchange_commission_rate") or 0.0)
    raw_cost = transaction_price * quantity
    commission = raw_cost * (exchange_rate / 100.0)
    cost_with_comm = raw_cost + commission
    cash_match = dfp[dfp["valeur"] == "Cash"]
    current_cash = float(cash_match["quantité"].values[0]) if not cash_match.empty else 0.0
    if cost_with_comm > current_cash:
        st.error(f"Montant insuffisant en Cash: {current_cash:,.2f} < {cost_with_comm:,.2f}")
        return
    match = dfp[dfp["valeur"] == stock_name]
    if match.empty:
        new_vwap = cost_with_comm / quantity
        try:
            portfolio_table().upsert([{
                "client_id": cid,
                "valeur": stock_name,
                "quantité": quantity,
                "vwap": new_vwap,
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
        new_qty = old_qty + quantity
        new_vwap = new_cost / new_qty if new_qty > 0 else 0.0
        try:
            portfolio_table().update({
                "quantité": new_qty,
                "vwap": new_vwap
            }).eq("client_id", cid).eq("valeur", stock_name).execute()
        except Exception as e:
            st.error(f"Erreur mise à jour stock {stock_name}: {e}")
            return
    new_cash = current_cash - cost_with_comm
    if cash_match.empty:
        try:
            portfolio_table().upsert([{
                "client_id": cid,
                "valeur": "Cash",
                "quantité": new_cash,
                "vwap": 1.0,
                "cours": 0.0,
                "valorisation": 0.0
            }], on_conflict="client_id,valeur").execute()
        except Exception as e:
            st.error(f"Erreur insertion Cash: {e}")
            return
    else:
        try:
            portfolio_table().update({
                "quantité": new_cash,
                "vwap": 1.0
            }).eq("client_id", cid).eq("valeur", "Cash").execute()
        except Exception as e:
            st.error(f"Erreur mise à jour Cash: {e}")
            return
    st.success(f"Achat de {quantity:.0f} '{stock_name}' @ {transaction_price:,.2f}, coût total {cost_with_comm:,.2f} (commission incluse).")
    st.rerun()

def sell_shares(client_name: str, stock_name: str, transaction_price: float, quantity: float):
    cinfo = get_client_info(client_name)
    if not cinfo:
        st.error("Client introuvable.")
        return
    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client introuvable.")
        return
    exchange_rate = float(cinfo.get("exchange_commission_rate") or 0.0)
    tax_rate = float(cinfo.get("tax_on_gains_rate") or 15.0)
    dfp = get_portfolio(client_name)
    match = dfp[dfp["valeur"] == stock_name]
    if match.empty:
        st.error(f"Le client ne possède pas {stock_name}.")
        return
    old_qty = float(match["quantité"].values[0])
    if quantity > old_qty:
        st.error(f"Quantité insuffisante: vous vendez {quantity}, mais le client possède {old_qty}.")
        return
    old_vwap = float(match["vwap"].values[0])
    raw_proceeds = transaction_price * quantity
    commission = raw_proceeds * (exchange_rate / 100.0)
    net_proceeds = raw_proceeds - commission
    cost_of_shares = old_vwap * quantity
    profit = net_proceeds - cost_of_shares
    if profit > 0:
        tax = profit * (tax_rate / 100.0)
        net_proceeds -= tax
    new_qty = old_qty - quantity
    try:
        if new_qty <= 0:
            portfolio_table().delete().eq("client_id", cid).eq("valeur", stock_name).execute()
        else:
            portfolio_table().update({"quantité": new_qty}).eq("client_id", cid).eq("valeur", stock_name).execute()
    except Exception as e:
        st.error(f"Erreur mise à jour après vente: {e}")
        return
    cash_match = dfp[dfp["valeur"] == "Cash"]
    old_cash = float(cash_match["quantité"].values[0]) if not cash_match.empty else 0.0
    new_cash = old_cash + net_proceeds
    try:
        if cash_match.empty:
            portfolio_table().upsert([{
                "client_id": cid,
                "valeur": "Cash",
                "quantité": new_cash,
                "vwap": 1.0,
                "cours": 0.0,
                "valorisation": 0.0
            }], on_conflict="client_id,valeur").execute()
        else:
            portfolio_table().update({"quantité": new_cash, "vwap": 1.0}).eq("client_id", cid).eq("valeur", "Cash").execute()
    except Exception as e:
        st.error(f"Erreur mise à jour Cash: {e}")
        return
    st.success(f"Vente de {quantity:.0f} '{stock_name}' @ {transaction_price:,.2f}, net {net_proceeds:,.2f} (commission + taxe gains).")
    st.rerun()

######################################################
# SIMULATION FUNCTIONS AND HELPERS
######################################################
def simulation_for_client_updated(client_name):
    """
    Updated simulation for a single portfolio.
    Displays a table with columns:
    Valeur | Cours (Prix) | Quantité actuelle | Poids Actuel (%) | Quantité Cible | Poids Cible (%) | Écart
    (The Cash row is always placed at the bottom.)
    """
    client = get_client_info(client_name)
    if not client:
        st.error("Client non trouvé.")
        return
    strategies_df = get_strategies()
    if "strategy_id" in client and client["strategy_id"]:
        strat = strategies_df[strategies_df["id"] == client["strategy_id"]]
        targets = json.loads(strat.iloc[0]["targets"]) if not strat.empty else {}
    else:
        targets = {}
    pf = get_portfolio(client_name)
    if pf.empty:
        st.error("Portefeuille vide pour ce client.")
        return
    stocks_df = fetch_stocks()
    total_val = 0.0
    portfolio_assets = {}
    for _, row in pf.iterrows():
        asset = row["valeur"]
        qty = float(row["quantité"])
        match = stocks_df[stocks_df["valeur"] == asset]
        price = float(match["cours"].iloc[0]) if not match.empty else 0.0
        total_val += qty * price
        portfolio_assets[asset] = {"qty": qty, "price": price}
    for asset in targets.keys():
        if asset not in portfolio_assets:
            match = stocks_df[stocks_df["valeur"] == asset]
            price = float(match["cours"].iloc[0]) if not match.empty else 0.0
            portfolio_assets[asset] = {"qty": 0, "price": price}
    sim_rows = []
    assets_ordered = [a for a in portfolio_assets if a.lower() != "cash"] + (["Cash"] if "Cash" in portfolio_assets else [])
    for asset in assets_ordered:
        current_qty = portfolio_assets[asset]["qty"]
        price = portfolio_assets[asset]["price"]
        current_value = current_qty * price
        current_weight = (current_value / total_val * 100) if total_val > 0 else 0
        target_pct = targets.get(asset, 0)
        if asset.lower() == "cash":
            target_pct = 100 - sum(targets.values())
        target_value = total_val * (target_pct / 100)
        target_qty = round(target_value / price) if price > 0 else 0
        ecart = current_qty - target_qty
        sim_rows.append({
            "Valeur": asset,
            "Cours (Prix)": price,
            "Quantité actuelle": int(current_qty),
            "Poids Actuel (%)": round(current_weight, 2),
            "Quantité Cible": int(target_qty),
            "Poids Cible (%)": target_pct,
            "Écart": int(ecart)
        })
    sim_df = pd.DataFrame(sim_rows, columns=["Valeur", "Cours (Prix)", "Quantité actuelle", "Poids Actuel (%)", "Quantité Cible", "Poids Cible (%)", "Écart"])
    st.dataframe(sim_df, use_container_width=True)

def aggregate_portfolios(client_list):
    """
    Aggregate portfolios for a list of clients.
    Returns a DataFrame with aggregated quantities per asset.
    """
    agg = {}
    for client in client_list:
        pf = get_portfolio(client)
        if not pf.empty:
            for _, row in pf.iterrows():
                asset = row["valeur"]
                qty = float(row["quantité"])
                agg[asset] = agg.get(asset, 0) + qty
    return pd.DataFrame(list(agg.items()), columns=["valeur", "quantité"])

def simulation_for_aggregated(agg_pf, strategy):
    """
    Run simulation on an aggregated portfolio.
    Uses the same columns as the single portfolio simulation.
    """
    targets = json.loads(strategy["targets"])
    targets["Cash"] = 100 - sum(targets.values())
    stocks_df = fetch_stocks()
    total_val = 0.0
    portfolio_assets = {}
    for _, row in agg_pf.iterrows():
        asset = row["valeur"]
        qty = float(row["quantité"])
        match = stocks_df[stocks_df["valeur"] == asset]
        price = 1.0 if asset.lower() == "cash" else (float(match["cours"].iloc[0]) if not match.empty else 0.0)
        total_val += qty * price
        portfolio_assets[asset] = {"qty": qty, "price": price}
    assets_ordered = [a for a in portfolio_assets if a.lower() != "cash"] + (["Cash"] if "Cash" in portfolio_assets else [])
    sim_rows = []
    for asset in assets_ordered:
        current_qty = portfolio_assets[asset]["qty"]
        price = portfolio_assets[asset]["price"]
        current_value = current_qty * price
        current_weight = (current_value / total_val * 100) if total_val > 0 else 0
        target_pct = targets.get(asset, 0)
        if asset.lower() == "cash":
            target_pct = 100 - sum(targets[k] for k in targets if k.lower() != "cash")
        target_value = total_val * (target_pct / 100)
        target_qty = round(target_value / price) if price > 0 else 0
        ecart = current_qty - target_qty
        sim_rows.append({
            "Valeur": asset,
            "Cours (Prix)": price,
            "Quantité actuelle": int(current_qty),
            "Poids Actuel (%)": round(current_weight, 2),
            "Quantité Cible": int(target_qty),
            "Poids Cible (%)": target_pct,
            "Écart": int(ecart)
        })
    sim_df = pd.DataFrame(sim_rows, columns=["Valeur", "Cours (Prix)", "Quantité actuelle", "Poids Actuel (%)", "Quantité Cible", "Poids Cible (%)", "Écart"])
    st.dataframe(sim_df, use_container_width=True)

def simulation_stock_details(selected_stock, strategy, client_list):
    """
    For multiple portfolios, returns a detailed breakdown for a selected stock.
    Returns:
      1. An aggregated details dictionary with:
         - "Action": the selected stock.
         - "Prix": the stock price (MAD) rounded to 2 decimals.
         - "Quantité actuelle agrégée": aggregated current quantity (integer).
         - "Poids cible (%)": target percentage (2 decimals).
         - "Quantité cible agrégée": aggregated target quantity (integer).
         - "Ajustement (à acheter si positif, à vendre si négatif)": aggregated adjustment (integer).
         - "Valeur de l'ajustement (MAD)": adjustment value in MAD (rounded to 2 decimals).
         - "Cash disponible": total cash available across all portfolios (rounded to 2 decimals).
      2. A "Pré‑répartition" DataFrame with per‑client details including:
         - "Client"
         - "Quantité actuelle" (integer)
         - "Quantité Cible" (integer)
         - "Ajustement" (integer)
         - "Valeur de l'ajustement (MAD)" (rounded to 2 decimals)
         - "Cash disponible" (rounded to 2 decimals)
         - "Capacité d'achat" (integer)
    """
    stocks_df = fetch_stocks()
    match = stocks_df[stocks_df["valeur"].str.lower() == selected_stock.lower()]
    if not match.empty:
        price = round(float(match["cours"].iloc[0]), 2)
    else:
        price = 0.0

    strategy_targets = json.loads(strategy["targets"])
    target_pct = strategy_targets.get(selected_stock, 0)
    if selected_stock.lower() == "cash":
        target_pct = 100 - sum(strategy_targets.values())
    
    aggregated_qty = 0
    total_cash_available = 0
    total_value_all = 0.0
    per_client_details = []
    for client in client_list:
        pf = get_portfolio(client)
        client_value = 0.0
        current_qty = 0
        cash_available = 0
        client_info = get_client_info(client)
        commission_rate = float(client_info.get("exchange_commission_rate", 0)) if client_info else 0.0
        if not pf.empty:
            for _, row in pf.iterrows():
                asset = row["valeur"]
                qty = float(row["quantité"])
                m = stocks_df[stocks_df["valeur"].str.lower() == asset.lower()]
                p = 1.0 if asset.lower() == "cash" else (float(m["cours"].iloc[0]) if not m.empty else 0.0)
                client_value += qty * p
                if asset.lower() == selected_stock.lower():
                    current_qty = qty
                if asset.lower() == "cash":
                    cash_available = qty
        target_qty_client = round(client_value * (target_pct / 100) / price) if price > 0 else 0
        # Compute adjustment (target - current) and capacity d'achat (floor of cash_available divided by effective price with commission)
        adjustment_client = target_qty_client - current_qty
        capacity_achat = int(cash_available // (price * (1 + commission_rate/100))) if price > 0 else 0
        per_client_details.append({
            "Client": client,
            "Quantité actuelle": int(current_qty),
            "Quantité Cible": int(target_qty_client),
            "Ajustement": int(adjustment_client),
            "Valeur de l'ajustement (MAD)": round(adjustment_client * price, 2),
            "Cash disponible": round(cash_available, 2),
            "Capacité d'achat": capacity_achat
        })
        aggregated_qty += current_qty
        total_cash_available += cash_available
        total_value_all += client_value

    target_qty_agg = round(total_value_all * (target_pct / 100) / price) if price > 0 else 0
    adjustment_agg = target_qty_agg - aggregated_qty
    agg_details = {
        "Action": selected_stock,
        "Prix": round(price, 2),
        "Quantité actuelle agrégée": int(aggregated_qty),
        "Poids cible (%)": round(target_pct, 2),
        "Quantité cible agrégée": int(target_qty_agg),
        "Ajustement (à acheter si positif, à vendre si négatif)": int(adjustment_agg),
        "Valeur de l'ajustement (MAD)": round(adjustment_agg * price, 2),
        "Cash disponible": round(total_cash_available, 2)
    }
    repartition_df = pd.DataFrame(per_client_details)
    # Format specific columns to display 2 decimals where applicable.
    repartition_df["Valeur de l'ajustement (MAD)"] = repartition_df["Valeur de l'ajustement (MAD)"].map("{:,.2f}".format)
    repartition_df["Cash disponible"] = repartition_df["Cash disponible"].map("{:,.2f}".format)
    return agg_details, repartition_df
