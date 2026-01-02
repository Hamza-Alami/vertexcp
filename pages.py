import io
import json
import tempfile
from collections import defaultdict
from datetime import date

import pandas as pd
import streamlit as st
import plotly.express as px

import db_utils
from db_utils import (
    get_all_clients,
    get_client_id,
    get_client_info,
    create_client,
    rename_client,
    delete_client,
    update_client_rates,
    client_has_portfolio,
    get_portfolio,
    get_supabase,
    get_performance_periods_for_client,
    create_performance_period,
    get_latest_performance_period_for_all_clients,
    fetch_stocks,
    get_transactions,
)

from logic import (
    buy_shares,
    sell_shares,
    new_portfolio_creation_ui,
    get_poids_masi_map,
    get_current_masi,
)


########################################
# 1) Manage Clients Page
########################################
def page_manage_clients():
    st.title("Gestion des Clients")
    existing = get_all_clients()

    with st.form("add_client_form", clear_on_submit=True):
        new_client_name = st.text_input("Nom du nouveau client", key="new_client_input")
        if st.form_submit_button("➕ Créer le client"):
            create_client(new_client_name)

    if existing:
        with st.form("rename_client_form", clear_on_submit=True):
            rename_choice = st.selectbox("Sélectionner le client à renommer", options=existing, key="rename_choice")
            rename_new = st.text_input("Nouveau nom du client", key="rename_text")
            if st.form_submit_button("✏️ Renommer ce client"):
                rename_client(rename_choice, rename_new)

        with st.form("delete_client_form", clear_on_submit=True):
            delete_choice = st.selectbox("Sélectionner le client à supprimer", options=existing, key="delete_choice")
            if st.form_submit_button("🗑️ Supprimer ce client"):
                delete_client(delete_choice)


########################################
# 2) Create Portfolio Page
########################################
def page_create_portfolio():
    st.title("Création d'un Portefeuille Client")
    clist = get_all_clients()
    if not clist:
        st.warning("Aucun client trouvé. Veuillez d'abord créer un client.")
        return

    cselect = st.selectbox("Sélectionner un client", clist, key="create_pf_select")
    if not cselect:
        return

    if client_has_portfolio(cselect):
        st.warning(f"Le client '{cselect}' dispose déjà d'un portefeuille.")
    else:
        new_portfolio_creation_ui(cselect)


########################################
# 3) Show / Manage Portfolio
########################################
def show_portfolio(client_name, read_only=False):
    cid = get_client_id(client_name)
    if cid is None:
        st.warning("Client introuvable.")
        return

    df = get_portfolio(client_name)
    if df.empty:
        st.warning(f"Aucun portefeuille trouvé pour « {client_name} ».")
        return

    stocks = fetch_stocks()
    df = df.copy()

    # Quantité integer display
    if "quantité" in df.columns:
        df["quantité"] = pd.to_numeric(df["quantité"], errors="coerce").fillna(0).astype(float)

    poids_masi_map = get_poids_masi_map()

    # Recalculate
    for i, row in df.iterrows():
        val = str(row["valeur"])

        if val.lower() == "cash":
            live_price = 1.0  # ✅ Cash always 1
        else:
            match = stocks[stocks["valeur"] == val]
            live_price = float(match["cours"].values[0]) if not match.empty else 0.0

        df.at[i, "cours"] = live_price

        qty_ = float(row.get("quantité", 0))
        vw_ = float(row.get("vwap", 0.0))
        val_ = round(qty_ * live_price, 2)
        df.at[i, "valorisation"] = val_

        cost_ = round(qty_ * vw_, 2)
        df.at[i, "cost_total"] = cost_
        df.at[i, "performance_latente"] = round(val_ - cost_, 2)

        if val.lower() == "cash":
            df.at[i, "poids_masi"] = 0.0
        else:
            info = poids_masi_map.get(val, {"poids_masi": 0.0})
            df.at[i, "poids_masi"] = float(info.get("poids_masi", 0.0))

    total_val = float(df["valorisation"].sum())
    if total_val > 0:
        df["poids"] = ((df["valorisation"] / total_val) * 100).round(2)
    else:
        df["poids"] = 0.0

    # Cash bottom
    df["__cash_marker"] = df["valeur"].astype(str).apply(lambda x: 1 if x.lower() == "cash" else 0)
    df.sort_values("__cash_marker", inplace=True, ignore_index=True)

    st.subheader(f"Portefeuille de {client_name}")
    st.write(f"**Valorisation totale du portefeuille :** {total_val:,.2f} MAD")

    drop_cols = ["id", "client_id", "is_cash", "__cash_marker"]
    for c in drop_cols:
        if c in df.columns:
            df.drop(columns=c, inplace=True)

    columns_display = [
        "valeur", "quantité", "vwap", "cours",
        "cost_total", "valorisation", "performance_latente",
        "poids", "poids_masi"
    ]
    df_disp = df[columns_display].copy()

    def color_perf(x):
        if isinstance(x, (float, int)) and x > 0:
            return "color:green;"
        elif isinstance(x, (float, int)) and x < 0:
            return "color:red;"
        return ""

    def bold_cash(row):
        if str(row["valeur"]).lower() == "cash":
            return ["font-weight:bold;"] * len(row)
        return ["" for _ in row]

    df_styled = df_disp.style.format(
        "{:,.2f}",
        subset=["quantité", "vwap", "cours", "cost_total", "valorisation", "performance_latente", "poids", "poids_masi"]
    ).applymap(color_perf, subset=["performance_latente"]) \
     .apply(bold_cash, axis=1)

    st.dataframe(df_styled, use_container_width=True)

    if read_only:
        return

    # Edit client params
    cinfo = get_client_info(client_name)
    if cinfo:
        with st.expander(f"Modifier Commissions / Taxes / Frais pour {client_name}", expanded=False):
            exch = float(cinfo.get("exchange_commission_rate") or 0.0)
            mgf = float(cinfo.get("management_fee_rate") or 0.0)
            pea = bool(cinfo.get("is_pea") or False)
            tax = float(cinfo.get("tax_on_gains_rate") or 15.0)
            bill_surf = bool(cinfo.get("bill_surperformance", False))

            new_exch = st.number_input("Commission d'intermédiation (%)", min_value=0.0, value=exch, step=0.01)
            new_mgmt = st.number_input("Frais de gestion (%)", min_value=0.0, value=mgf, step=0.01)
            new_pea = st.checkbox("Compte PEA ?", value=pea)
            new_tax = st.number_input("Taux d'imposition sur les gains (%)", min_value=0.0, value=tax, step=0.01)
            new_bill = st.checkbox("Facturer Surperformance ?", value=bill_surf)

            if st.button(f"Mettre à jour les paramètres pour {client_name}"):
                update_client_rates(client_name, new_exch, new_pea, new_tax, new_mgmt, new_bill)

    # Manual edit (qty/vwap)
    with st.expander("Édition manuelle (Quantité / VWAP)", expanded=False):
        edf = df_disp[["valeur", "quantité", "vwap"]].copy()
        edf["quantité"] = pd.to_numeric(edf["quantité"], errors="coerce").fillna(0).astype(int)

        updated_df = st.data_editor(edf, use_container_width=True)
        if st.button("💾 Enregistrer modifications"):
            cid2 = get_client_id(client_name)
            for _, row2 in updated_df.iterrows():
                valn = str(row2["valeur"])
                qn = int(row2["quantité"])
                vw = float(row2["vwap"])
                try:
                    db_utils.portfolio_table().update({
                        "quantité": qn,
                        "vwap": vw
                    }).eq("client_id", cid2).eq("valeur", valn).execute()
                except Exception as e:
                    st.error(f"Erreur sauvegarde pour {valn}: {e}")
            st.success(f"Portefeuille de « {client_name} » mis à jour.")
            st.rerun()

    # BUY
    st.write("### Opération d'Achat")
    _stocks = fetch_stocks()
    buy_stock = st.selectbox("Choisir la valeur à acheter", _stocks["valeur"].tolist(), key="buy_stock_sel")
    buy_price = st.number_input("Prix d'achat", min_value=0.0, value=0.0, step=0.01, key="buy_px")
    buy_qty = st.number_input("Quantité à acheter", min_value=1, value=1, step=1, key="buy_qty")
    if st.button("Acheter", key="buy_btn"):
        buy_shares(client_name, buy_stock, buy_price, float(buy_qty))

    # SELL
    st.write("### Opération de Vente")
    existing_stocks = df_disp[df_disp["valeur"].astype(str).str.lower() != "cash"]["valeur"].unique().tolist()
    if not existing_stocks:
        st.info("Aucune action à vendre.")
    else:
        sell_stock = st.selectbox("Choisir la valeur à vendre", existing_stocks, key="sell_stock_sel")
        sell_price = st.number_input("Prix de vente", min_value=0.0, value=0.0, step=0.01, key="sell_px")
        sell_qty = st.number_input("Quantité à vendre", min_value=1, value=1, step=1, key="sell_qty")
        if st.button("Vendre", key="sell_btn"):
            sell_shares(client_name, sell_stock, sell_price, float(sell_qty))

    # ✅ Transactions history + TPCVM
    with st.expander("📜 Historique des transactions + TPCVM", expanded=False):
        tx = get_transactions(cid)
        if tx.empty:
            st.info("Aucune transaction enregistrée.")
        else:
            keep = ["executed_at", "trade_date", "side", "symbol", "quantity", "price",
                    "gross_amount", "fees", "realized_pl", "tax_rate_used", "tpcvm", "net_cash_flow"]
            tx2 = tx[[c for c in keep if c in tx.columns]].copy()

            total_tpcvm = float(tx2["tpcvm"].sum()) if "tpcvm" in tx2.columns else 0.0
            st.write(f"**TPCVM total (historique) : {total_tpcvm:,.2f} MAD**")

            st.dataframe(
                tx2.style.format("{:,.2f}", subset=[c for c in tx2.columns if c not in ["executed_at","trade_date","side","symbol"]]),
                use_container_width=True
            )

            if "trade_date" in tx.columns and "tpcvm" in tx.columns:
                txm = tx.copy()
                txm["trade_date"] = pd.to_datetime(txm["trade_date"], errors="coerce")
                txm["mois"] = txm["trade_date"].dt.to_period("M").astype(str)
                tpcm = txm.groupby("mois", as_index=False)["tpcvm"].sum().sort_values("mois")
                st.write("**TPCVM par mois (ce client)**")
                st.dataframe(tpcm.style.format({"tpcvm": "{:,.2f}"}), use_container_width=True)


########################################
# 4) View Single Portfolio
########################################
def page_view_client_portfolio():
    st.title("Portefeuille d'un Client")
    c2 = get_all_clients()
    if not c2:
        st.warning("Aucun client trouvé.")
        return

    client_selected = st.selectbox("Sélectionner un client", c2)
    if client_selected:
        show_portfolio(client_selected, read_only=False)


########################################
# 5) View All Portfolios
########################################
def page_view_all_portfolios():
    st.title("Vue Globale de Tous les Portefeuilles")
    clients = get_all_clients()
    if not clients:
        st.warning("Aucun client n'est disponible.")
        return
    for cname in clients:
        st.write(f"### Client: {cname}")
        show_portfolio(cname, read_only=True)
        st.write("---")


########################################
# 6) Inventory
########################################
def page_inventory():
    st.title("Inventaire des Actifs")

    stocks = fetch_stocks()
    clients = get_all_clients()
    if not clients:
        st.warning("Aucun client n'est disponible.")
        return

    master_data = defaultdict(lambda: {"quantity": 0.0, "clients": set()})
    overall_val = 0.0

    for c in clients:
        dfp = get_portfolio(c)
        if dfp.empty:
            continue

        portf_val = 0.0
        for _, row in dfp.iterrows():
            val = str(row["valeur"])
            qty = float(row["quantité"])

            if val.lower() == "cash":
                price = 1.0
            else:
                match = stocks[stocks["valeur"] == val]
                price = float(match["cours"].values[0]) if not match.empty else 0.0

            total_ = qty * price
            portf_val += total_
            master_data[val]["quantity"] += qty
            master_data[val]["clients"].add(c)

        overall_val += portf_val

    if not master_data:
        st.write("Aucun actif trouvé dans les portefeuilles.")
        return

    rows = []
    sum_stocks_val = 0.0

    for val, info in master_data.items():
        if val.lower() == "cash":
            price = 1.0
        else:
            match = stocks[stocks["valeur"] == val]
            price = float(match["cours"].values[0]) if not match.empty else 0.0

        agg_val = info["quantity"] * price
        sum_stocks_val += agg_val
        rows.append({
            "valeur": val,
            "quantité total": info["quantity"],
            "valorisation": agg_val,
            "portefeuille": ", ".join(sorted(info["clients"]))
        })

    for row in rows:
        row["poids"] = round((row["valorisation"] / sum_stocks_val) * 100, 2) if sum_stocks_val > 0 else 0.0

    df_inv = pd.DataFrame(rows)
    styled_inv = df_inv.style.format({
        "quantité total": "{:,.0f}",
        "valorisation": "{:,.2f}",
        "poids": "{:,.2f}"
    })

    st.dataframe(styled_inv, use_container_width=True)
    st.write(f"### Actif sous gestion: {overall_val:,.2f} MAD")


########################################
# 7) Market Page
########################################
def page_market():
    st.title("Marché Boursier")
    st.write("Les cours affichés peuvent avoir un décalage (~15 min).")

    mm = get_poids_masi_map()
    if not mm:
        st.warning("Aucun instrument trouvé / BD vide.")
        return

    stx = fetch_stocks()

    rows = []
    for val, info in mm.items():
        rows.append({
            "valeur": val,
            "Capitalisation": info.get("capitalisation", 0.0),
            "Poids Masi": info.get("poids_masi", 0.0)
        })
    df_mkt = pd.DataFrame(rows)
    df_mkt = pd.merge(df_mkt, stx, on="valeur", how="left")
    df_mkt.rename(columns={"cours": "Cours"}, inplace=True)
    df_mkt = df_mkt[["valeur", "Cours", "Capitalisation", "Poids Masi"]]

    st.dataframe(
        df_mkt.style.format({
            "Cours": "{:,.2f}",
            "Capitalisation": "{:,.2f}",
            "Poids Masi": "{:,.2f}"
        }),
        use_container_width=True
    )


########################################
# 8) Performance & Fees
########################################
def page_performance_fees():
    st.title("Performance et Frais")

    clients = get_all_clients()
    if not clients:
        st.warning("Aucun client trouvé. Veuillez créer un client.")
        return

    client_name = st.selectbox("Sélectionner un client", clients)
    if not client_name:
        return

    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client non valide.")
        return

    # Existing periods (editable)
    with st.expander("Périodes de Performance Existantes", expanded=False):
        df_periods = get_performance_periods_for_client(cid)
        if df_periods.empty:
            st.info("Aucune période n'existe pour ce client.")
        else:
            df_periods = df_periods.copy()
            df_periods["start_date"] = pd.to_datetime(df_periods["start_date"], errors="coerce").dt.date

            col_cfg = {
                "start_date": st.column_config.DateColumn("Date de Début", required=True),
                "start_value": st.column_config.NumberColumn("Portefeuille Départ", format="%.2f"),
                "masi_start_value": st.column_config.NumberColumn("MASI Départ", format="%.2f"),
                "id": st.column_config.Column("id", disabled=True),
                "client_id": st.column_config.Column("client_id", disabled=True),
            }

            updated = st.data_editor(df_periods, use_container_width=True, column_config=col_cfg)

            if st.button("Enregistrer modifications sur ces périodes"):
                for _, row_new in updated.iterrows():
                    try:
                        row_data = {
                            "start_date": str(row_new["start_date"]),
                            "start_value": float(row_new.get("start_value", 0) or 0),
                            "masi_start_value": float(row_new.get("masi_start_value", 0) or 0)
                        }
                        db_utils.performance_table().update(row_data).eq("id", row_new["id"]).execute()
                    except Exception as e:
                        st.error(f"Erreur mise à jour: {e}")
                st.success("Périodes mises à jour.")
                st.rerun()

    # Add new period
    with st.expander("Ajouter une nouvelle période de performance", expanded=False):
        with st.form("add_perf_period_form", clear_on_submit=True):
            start_date_input = st.date_input("Date de Début")
            start_val_port = st.number_input("Portefeuille Départ", min_value=0.0, step=0.01, value=0.0)
            start_val_masi = st.number_input("MASI Départ", min_value=0.0, step=0.01, value=0.0)
            if st.form_submit_button("Enregistrer"):
                create_performance_period(cid, str(start_date_input), start_val_port, start_val_masi)
                st.rerun()

    # Calculate perf on period
    with st.expander("Calculer la Performance sur une Période", expanded=False):
        df_periods2 = get_performance_periods_for_client(cid)
        if df_periods2.empty:
            st.info("Aucune période n'existe.")
        else:
            df_periods2 = df_periods2.copy()
            df_periods2["start_date"] = pd.to_datetime(df_periods2["start_date"], errors="coerce").dt.date
            df_periods2 = df_periods2.sort_values("start_date", ascending=False)

            pick = st.selectbox("Choisir la date de début", df_periods2["start_date"].unique().tolist())
            row_chosen = df_periods2[df_periods2["start_date"] == pick].iloc[0]
            portfolio_start = float(row_chosen.get("start_value", 0))
            masi_start = float(row_chosen.get("masi_start_value", 0))

            pdf = get_portfolio(client_name)
            if pdf.empty:
                st.warning("Pas de portefeuille pour ce client.")
            else:
                stx = fetch_stocks()
                cur_val = 0.0
                for _, prow in pdf.iterrows():
                    val = str(prow["valeur"])
                    qty = float(prow["quantité"])
                    if val.lower() == "cash":
                        px = 1.0
                    else:
                        m = stx[stx["valeur"] == val]
                        px = float(m["cours"].values[0]) if not m.empty else 0.0
                    cur_val += qty * px

                gains_port = cur_val - portfolio_start
                perf_port = (gains_port / portfolio_start) * 100.0 if portfolio_start > 0 else 0.0

                masi_now = get_current_masi()
                gains_masi = masi_now - masi_start
                perf_masi = (gains_masi / masi_start) * 100.0 if masi_start > 0 else 0.0

                surp_pct = perf_port - perf_masi
                surp_abs = (surp_pct / 100.0) * portfolio_start

                cinfo_ = get_client_info(client_name)
                mgmt_rate = float(cinfo_.get("management_fee_rate", 0)) / 100.0

                if cinfo_.get("bill_surperformance", False):
                    base_ = max(0.0, surp_abs)
                else:
                    base_ = max(0.0, gains_port)
                fees_ = base_ * mgmt_rate

                results_df = pd.DataFrame([{
                    "Portf Départ": portfolio_start,
                    "Portf Actuel": cur_val,
                    "Gains Portf": gains_port,
                    "Perf Portf %": perf_port,
                    "MASI Départ": masi_start,
                    "MASI Actuel": masi_now,
                    "Perf MASI %": perf_masi,
                    "Surperf %": surp_pct,
                    "Surperf Abs.": surp_abs,
                    "Frais": fees_,
                }])

                st.dataframe(results_df.style.format("{:,.2f}"), use_container_width=True)

    # Summary all clients
    with st.expander("Résumé de Performance (tous les clients)", expanded=False):
        all_latest = get_latest_performance_period_for_all_clients()
        if all_latest.empty:
            st.info("Aucune donnée globale de performance.")
        else:
            stx2 = fetch_stocks()
            masi_now2 = get_current_masi()
            all_cs = get_all_clients()

            # map ids -> names
            id_to_name = {}
            for nm in all_cs:
                id_to_name[get_client_id(nm)] = nm

            all_list = []
            for _, rowL in all_latest.iterrows():
                c_id = int(rowL["client_id"])
                name_ = id_to_name.get(c_id)
                if not name_:
                    continue

                st_val = float(rowL.get("start_value", 0))
                ms_val = float(rowL.get("masi_start_value", 0))
                ddate = str(rowL.get("start_date", ""))

                pdf2 = get_portfolio(name_)
                cur_val2 = 0.0
                if not pdf2.empty:
                    for _, prow2 in pdf2.iterrows():
                        v2 = str(prow2["valeur"])
                        q2 = float(prow2["quantité"])
                        if v2.lower() == "cash":
                            px2 = 1.0
                        else:
                            mt2 = stx2[stx2["valeur"] == v2]
                            px2 = float(mt2["cours"].values[0]) if not mt2.empty else 0.0
                        cur_val2 += q2 * px2

                gains_port2 = cur_val2 - st_val
                perf_port2 = (gains_port2 / st_val) * 100.0 if st_val > 0 else 0.0

                gains_masi2 = masi_now2 - ms_val
                perf_masi2 = (gains_masi2 / ms_val) * 100.0 if ms_val > 0 else 0.0

                surp_pct2 = perf_port2 - perf_masi2
                surp_abs2 = (surp_pct2 / 100.0) * st_val

                cinfo2 = get_client_info(name_)
                mgmtr2 = float(cinfo2.get("management_fee_rate", 0)) / 100.0
                if cinfo2.get("bill_surperformance", False):
                    base2 = max(0.0, surp_abs2)
                else:
                    base2 = max(0.0, gains_port2)
                fee2 = base2 * mgmtr2

                all_list.append({
                    "Client": name_,
                    "Date Début": ddate,
                    "Portf Départ": st_val,
                    "Portf Actuel": cur_val2,
                    "Perf Portf %": perf_port2,
                    "Perf MASI %": perf_masi2,
                    "Surperf %": surp_pct2,
                    "Surperf Abs.": surp_abs2,
                    "Frais": fee2
                })

            df_sum = pd.DataFrame(all_list)
            if df_sum.empty:
                st.info("Aucune info dispo.")
            else:
                st.dataframe(df_sum.style.format("{:,.2f}"), use_container_width=True)


########################################
# 9) Taxes (TPCVM) — ✅ NEW PAGE
########################################
def page_taxes_tpcvm():
    st.title("💰 Taxes (TPCVM)")
    st.caption("Basé sur la table public.transactions (SELL) — TPCVM calculée et loggée automatiquement.")

    clients = get_all_clients()
    if not clients:
        st.warning("Aucun client.")
        return

    mode = st.radio("Vue", ["Global (tous les clients)", "Par client"], horizontal=True)

    # date range
    col1, col2 = st.columns(2)
    with col1:
        d_from = st.date_input("Du", value=date(date.today().year, 1, 1))
    with col2:
        d_to = st.date_input("Au", value=date.today())

    # map ids -> names
    id_to_name = {get_client_id(n): n for n in clients}

    if mode == "Par client":
        client_name = st.selectbox("Client", clients)
        cid = get_client_id(client_name)
        tx = get_transactions(cid)
    else:
        tx = get_transactions(None)

    if tx.empty:
        st.info("Aucune transaction enregistrée.")
        return

    # Filter dates
    tx = tx.copy()
    tx["trade_date"] = pd.to_datetime(tx.get("trade_date"), errors="coerce")
    tx = tx[(tx["trade_date"] >= pd.to_datetime(d_from)) & (tx["trade_date"] <= pd.to_datetime(d_to))]

    if tx.empty:
        st.info("Aucune transaction sur la période.")
        return

    # Keep only SELL if you want strictly “tax on gains”
    only_sell = st.checkbox("Afficher uniquement les ventes (SELL)", value=True)
    if only_sell and "side" in tx.columns:
        tx = tx[tx["side"] == "SELL"]

    if tx.empty:
        st.info("Aucune vente (SELL) sur la période.")
        return

    # Total TPCVM
    total_tpcvm = float(pd.to_numeric(tx.get("tpcvm"), errors="coerce").fillna(0).sum())
    st.metric("TPCVM Totale sur la période", f"{total_tpcvm:,.2f} MAD")

    # Monthly
    if "tpcvm" in tx.columns:
        tx["mois"] = tx["trade_date"].dt.to_period("M").astype(str)
        monthly = tx.groupby("mois", as_index=False)["tpcvm"].sum().sort_values("mois")
        st.subheader("TPCVM par mois")
        st.dataframe(monthly.style.format({"tpcvm": "{:,.2f}"}), use_container_width=True)

        fig = px.bar(monthly, x="mois", y="tpcvm", title="TPCVM mensuelle")
        st.plotly_chart(fig, use_container_width=True)

    # By client (global mode)
    if mode.startswith("Global"):
        tx["client_name"] = tx["client_id"].map(id_to_name).fillna(tx["client_id"].astype(str))
        by_client = tx.groupby("client_name", as_index=False)["tpcvm"].sum().sort_values("tpcvm", ascending=False)
        st.subheader("TPCVM par client")
        st.dataframe(by_client.style.format({"tpcvm": "{:,.2f}"}), use_container_width=True)

    # Detailed table
    st.subheader("Détail")
    keep = ["executed_at","trade_date","client_id","side","symbol","quantity","price","fees","realized_pl","tax_rate_used","tpcvm","net_cash_flow"]
    view = tx[[c for c in keep if c in tx.columns]].copy()

    if mode.startswith("Global"):
        view["client"] = view["client_id"].map(id_to_name).fillna(view["client_id"].astype(str))
        # move client next to date
        cols = ["executed_at","trade_date","client","side","symbol","quantity","price","fees","realized_pl","tax_rate_used","tpcvm","net_cash_flow"]
        view = view[[c for c in cols if c in view.columns]]

    st.dataframe(
        view.style.format("{:,.2f}", subset=[c for c in view.columns if c not in ["executed_at","trade_date","side","symbol","client"]]),
        use_container_width=True
    )

    # Export CSV
    st.subheader("Exporter")
    csv = view.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Télécharger CSV", csv, file_name="tpcvm_taxes.csv", mime="text/csv")

