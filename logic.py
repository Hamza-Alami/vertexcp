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
    transactions_table,
)

######################################################
#     Real-time MASI Fetch
######################################################

def get_current_masi():
    """Return the real-time MASI index from Casablanca Bourse."""
    try:
        return db_utils.fetch_masi_from_cb()
    except Exception as e:
        st.error(f"Erreur récupération MASI: {e}")
        return 0.0

######################################################
#  Compute Poids Masi for each "valeur"
######################################################

def compute_poids_masi():
    """
    Creates a dictionary { valeur: {"capitalisation": X, "poids_masi": Y}, ... }
    by merging instruments + stocks => capitalisation => floated_cap => sum => percentage.
    """
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

    merged["cours"] = pd.to_numeric(merged["cours"], errors='coerce').fillna(0.0)
    merged["nombre_de_titres"] = pd.to_numeric(merged["nombre_de_titres"], errors='coerce').fillna(0.0)
    merged["facteur_flottant"] = pd.to_numeric(merged["facteur_flottant"], errors='coerce').fillna(0.0)

    # exclude zero
    merged = merged[(merged["cours"] != 0.0) & (merged["nombre_de_titres"] != 0.0)].copy()

    merged["capitalisation"] = merged["cours"] * merged["nombre_de_titres"]
    merged["floated_cap"]    = merged["capitalisation"] * merged["facteur_flottant"]
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


# ❌ Removed the heavy query at import time
# poids_masi_map = compute_poids_masi()

# ✅ Replace with cached function to load lazily
@st.cache_data(ttl=300)
def get_poids_masi_map():
    return compute_poids_masi()

######################################################
#   Create a brand-new portfolio
######################################################

def create_portfolio_rows(client_name: str, holdings: dict):
    """
    Upserts rows (valeur -> quantity) into 'portfolios' if the client has no portfolio.
    If they do, we do a warning.
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
    Lets the user pick stocks/cash to add to a brand-new portfolio via st.session_state.
    """
    st.subheader(f"➕ Définir les actifs initiaux pour {client_name}")

    if "temp_holdings" not in st.session_state:
        st.session_state.temp_holdings = {}

    try:
        all_stocks = fetch_stocks()
    except Exception as e:
        st.error(f"Erreur chargement stocks: {e}")
        return

    chosen_val = st.selectbox(f"Choisir une valeur ou 'Cash'", all_stocks["valeur"].tolist(), key=f"new_stock_{client_name}")
    qty = st.number_input(
        f"Quantité pour {client_name}",
        min_value=1.0,
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
#        Buy / Sell
######################################################

def _create_portfolio_snapshot(client_name: str) -> dict:
    """Create a snapshot of the current portfolio state."""
    dfp = get_portfolio(client_name)
    if dfp.empty:
        return {}
    snapshot = {}
    for _, row in dfp.iterrows():
        snapshot[str(row["valeur"])] = {
            "quantité": float(row.get("quantité", 0)),
            "vwap": float(row.get("vwap", 0))
        }
    return snapshot

def _record_transaction(client_id: int, side: str, symbol: str, quantity: float, price: float,
                       gross_amount: float, fees: float, tax_rate_used: float, tpcvm: float,
                       realized_pl: float, net_cash_flow: float, trade_date: str,
                       snapshot_before: dict, snapshot_after: dict, note: str = None):
    """Record a transaction in the database. Matches existing transactions table schema."""
    try:
        transaction_data = {
            "client_id": client_id,
            "side": side,
            "symbol": symbol,  # Using 'symbol' instead of 'valeur' to match DB
            "quantity": quantity,
            "price": price,
            "gross_amount": gross_amount,
            "fees": fees,
            "tax_rate_used": tax_rate_used,
            "tpcvm": tpcvm,
            "realized_pl": realized_pl,  # Single realized_pl field
            "net_cash_flow": net_cash_flow,
            "trade_date": trade_date,
            "portfolio_snapshot_before": snapshot_before,  # Using 'portfolio_snapshot_before'
            "portfolio_snapshot_after": snapshot_after,  # Using 'portfolio_snapshot_after'
        }
        if note:
            transaction_data["note"] = note  # Using 'note' instead of 'notes'
        transactions_table().insert(transaction_data).execute()
    except Exception as e:
        st.error(f"Erreur lors de l'enregistrement de la transaction: {e}")

def buy_shares(client_name: str, stock_name: str, transaction_price: float, quantity: float, trade_date: str = None):
    from datetime import date
    import json
    
    cinfo = get_client_info(client_name)
    if not cinfo:
        st.error("Informations du client introuvables.")
        return

    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client introuvable.")
        return

    # Create snapshot before transaction
    snapshot_before = _create_portfolio_snapshot(client_name)

    dfp = get_portfolio(client_name)
    exchange_rate = float(cinfo.get("exchange_commission_rate") or 0.0)
    is_pea = bool(cinfo.get("is_pea") or False)

    raw_cost = transaction_price * quantity
    commission = raw_cost * (exchange_rate / 100.0)
    cost_with_comm = raw_cost + commission

    # Check Cash
    cash_match = dfp[dfp["valeur"] == "Cash"]
    current_cash = float(cash_match["quantité"].values[0]) if not cash_match.empty else 0.0
    if cost_with_comm > current_cash:
        st.error(f"Montant insuffisant en Cash: {current_cash:,.2f} < {cost_with_comm:,.2f}")
        return

    # Check if stock exists
    match = dfp[dfp["valeur"] == stock_name]
    if match.empty:
        # Insert new
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
        # update
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

    # Update Cash - get fresh portfolio data after stock update
    dfp_updated = get_portfolio(client_name)
    cash_match_updated = dfp_updated[dfp_updated["valeur"] == "Cash"]
    current_cash_updated = float(cash_match_updated["quantité"].values[0]) if not cash_match_updated.empty else 0.0
    new_cash = current_cash_updated - cost_with_comm
    
    if cash_match_updated.empty:
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

    # Create snapshot after transaction
    snapshot_after = _create_portfolio_snapshot(client_name)

    # Calculate TPCVM (total paid) - sum of all cost_basis from previous transactions + this one
    from db_utils import calculate_tpcvm_for_client
    previous_tpcvm = calculate_tpcvm_for_client(cid)
    new_tpcvm = previous_tpcvm + cost_with_comm

    # Record transaction
    try:
        trade_date_str = trade_date if trade_date else str(date.today())
        _record_transaction(
            client_id=cid,
            side="BUY",
            symbol=stock_name,  # Using 'symbol' to match DB schema
            quantity=quantity,
            price=transaction_price,
            gross_amount=raw_cost,
            fees=commission,
            tax_rate_used=0.0,  # No tax on buy
            tpcvm=new_tpcvm,
            realized_pl=0.0,  # No P/L on buy
            net_cash_flow=-cost_with_comm,  # Negative for buy
            trade_date=trade_date_str,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after
        )
    except Exception as e:
        st.warning(f"⚠️ Transaction enregistrée mais erreur lors de la sauvegarde: {e}")
        # Don't fail the transaction, just warn

    # Show detailed breakdown
    st.success(f"✅ Achat réussi!")
    st.info(
        f"**Détails de l'achat:**\n"
        f"- Quantité: {quantity:.0f} {stock_name}\n"
        f"- Prix unitaire: {transaction_price:,.2f} MAD\n"
        f"- Montant brut: {raw_cost:,.2f} MAD\n"
        f"- Commission ({exchange_rate}%): {commission:,.2f} MAD\n"
        f"- **Coût total: {cost_with_comm:,.2f} MAD**"
    )
    st.rerun()

def sell_shares(client_name: str, stock_name: str, transaction_price: float, quantity: float, trade_date: str = None):
    from datetime import date
    
    cinfo = get_client_info(client_name)
    if not cinfo:
        st.error("Informations du client introuvables.")
        return

    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client introuvable.")
        return

    # Create snapshot before transaction
    snapshot_before = _create_portfolio_snapshot(client_name)

    exchange_rate = float(cinfo.get("exchange_commission_rate") or 0.0)
    tax_rate      = float(cinfo.get("tax_on_gains_rate") or 15.0)
    is_pea        = bool(cinfo.get("is_pea") or False)

    # Get fresh portfolio data to ensure we have current quantities
    dfp = get_portfolio(client_name)
    if dfp.empty:
        st.error(f"Le portefeuille est vide pour ce client.")
        return
    
    match = dfp[dfp["valeur"] == stock_name]
    if match.empty:
        st.error(f"Le client ne possède pas {stock_name}.")
        return

    old_qty = float(match["quantité"].values[0])
    if old_qty <= 0:
        st.error(f"Quantité insuffisante: le client ne possède plus {stock_name}.")
        return
        
    if quantity > old_qty:
        st.error(f"Quantité insuffisante: vous voulez vendre {quantity}, mais le client ne possède que {old_qty}.")
        return

    old_vwap      = float(match["vwap"].values[0])
    raw_proceeds  = transaction_price * quantity
    commission    = raw_proceeds * (exchange_rate / 100.0)
    net_proceeds  = raw_proceeds - commission

    cost_of_shares = old_vwap * quantity
    profit = net_proceeds - cost_of_shares
    tax = 0.0
    # PEA accounts are tax-free, so skip tax calculation if is_pea is True
    if profit > 0 and not is_pea:
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

    # Update Cash - get fresh portfolio data after stock update
    dfp_updated = get_portfolio(client_name)
    cash_match = dfp_updated[dfp_updated["valeur"] == "Cash"]
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
            portfolio_table().update({
                "quantité": new_cash,
                "vwap": 1.0
            }).eq("client_id", cid).eq("valeur", "Cash").execute()
    except Exception as e:
        st.error(f"Erreur mise à jour Cash: {e}")
        return

    # Create snapshot after transaction
    snapshot_after = _create_portfolio_snapshot(client_name)

    # Calculate TPCVM (total paid) - remains the same for sells (no new cost basis)
    # TPCVM is only updated on BUY transactions, so we use the current value
    # For PEA accounts, TPCVM should still track total paid, but tax is 0
    from db_utils import calculate_tpcvm_for_client
    current_tpcvm = calculate_tpcvm_for_client(cid)

    # Record transaction - MUST happen after portfolio update
    try:
        trade_date_str = trade_date if trade_date else str(date.today())
        realized_pl_after_tax = profit - tax
        # Tax rate used: 0 for PEA, otherwise the tax_rate (15% default)
        tax_rate_used = 0.0 if is_pea else (tax_rate if profit > 0 else 0.0)
        
        _record_transaction(
            client_id=cid,
            side="SELL",
            symbol=stock_name,  # Using 'symbol' to match DB schema
            quantity=quantity,
            price=transaction_price,
            gross_amount=raw_proceeds,
            fees=commission,
            tax_rate_used=tax_rate_used,
            tpcvm=current_tpcvm,  # TPCVM = total paid, doesn't change on sell
            realized_pl=realized_pl_after_tax,  # P/L after tax
            net_cash_flow=net_proceeds,  # Positive for sell
            trade_date=trade_date_str,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after
        )
    except Exception as e:
        st.error(f"❌ Erreur lors de l'enregistrement de la transaction: {e}")
        # Transaction happened but recording failed - this is a problem

    # Show detailed breakdown
    st.success(f"✅ Vente réussie!")
    breakdown_text = (
        f"**Détails de la vente:**\n"
        f"- Quantité: {quantity:.0f} {stock_name}\n"
        f"- Prix unitaire: {transaction_price:,.2f} MAD\n"
        f"- Montant brut: {raw_proceeds:,.2f} MAD\n"
        f"- Commission ({exchange_rate}%): {commission:,.2f} MAD\n"
    )
    
    if profit > 0:
        breakdown_text += (
            f"- Profit brut: {profit:,.2f} MAD\n"
        )
        if tax > 0:
            breakdown_text += (
                f"- Taxe ({tax_rate}%): {tax:,.2f} MAD\n"
            )
        else:
            breakdown_text += (
                f"- Taxe: 0.00 MAD (Compte PEA - exonéré)\n"
            )
        breakdown_text += (
            f"- **Net reçu: {net_proceeds:,.2f} MAD**"
        )
    else:
        breakdown_text += (
            f"- Perte: {abs(profit):,.2f} MAD\n"
            f"- **Net reçu: {net_proceeds:,.2f} MAD**"
        )
    
    st.info(breakdown_text)
    st.rerun()
