# pages.py

import streamlit as st
import pandas as pd
import numpy as np
from collections import defaultdict

# Import from db_utils
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
    fetch_stocks,
    get_performance_periods_for_client,
    create_performance_period,
    get_latest_performance_period_for_all_clients
)

# Import from logic
from logic import (
    buy_shares,
    sell_shares,
    new_portfolio_creation_ui,
    poids_masi_map,     # the global dict for Poids Masi
    get_current_masi,   # fetch the current MASI index from Casablanca Bourse
    compute_poids_masi
)

########################################
# 1) Manage Clients Page
########################################
def page_manage_clients():
    st.title("Gestion des Clients")
    existing = get_all_clients()

    # Créer un nouveau client
    with st.form("add_client_form", clear_on_submit=True):
        new_client_name = st.text_input("Nom du nouveau client", key="new_client_input")
        if st.form_submit_button("➕ Créer le client"):
            create_client(new_client_name)

    # Si des clients existent, permettre la modification/suppression
    if existing:
        # Renommer un client
        with st.form("rename_client_form", clear_on_submit=True):
            rename_choice = st.selectbox(
                "Sélectionner le client à renommer",
                options=existing,
                key="rename_choice"
            )
            rename_new = st.text_input("Nouveau nom du client", key="rename_text")
            if st.form_submit_button("✏️ Renommer ce client"):
                rename_client(rename_choice, rename_new)

        # Supprimer un client
        with st.form("delete_client_form", clear_on_submit=True):
            delete_choice = st.selectbox(
                "Sélectionner le client à supprimer",
                options=existing,
                key="delete_choice"
            )
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
    else:
        cselect = st.selectbox("Sélectionner un client", clist, key="create_pf_select")
        if cselect:
            # vérifier si le client a déjà un portefeuille
            if client_has_portfolio(cselect):
                st.warning(f"Le client '{cselect}' dispose déjà d'un portefeuille.")
            else:
                new_portfolio_creation_ui(cselect)


########################################
# 3) Afficher le portefeuille d'un client
########################################
def show_portfolio(client_name, read_only=False):
    """
    Affiche le portefeuille d'un client, 
    en mode lecture seule ou avec possibilités d'édition.
    """

    cid = db_utils.get_client_id(client_name)
    if cid is None:
        st.warning("Client introuvable.")
        return

    df = db_utils.get_portfolio(client_name)
    if df.empty:
        st.warning(f"Aucun portefeuille trouvé pour « {client_name} ».")
        return

    # Récupérer les cours
    stocks_df = db_utils.fetch_stocks()
    df = df.copy()

    # Convertir la colonne 'quantité' en entier (si c'est votre convention)
    if "quantité" in df.columns:
        df["quantité"] = df["quantité"].astype(int)

    # Recalculer colonnes: cours, valorisation, cost_total, performance_latente, poids_masi
    for i, row in df.iterrows():
        val   = str(row["valeur"])
        match = stocks_df[stocks_df["valeur"] == val]
        live_price = float(match["cours"].values[0]) if not match.empty else 0.0
        df.at[i, "cours"] = live_price

        qty_   = int(row["quantité"])
        vw_    = float(row.get("vwap", 0.0))
        val_   = round(qty_ * live_price, 2)
        cost_  = round(qty_ * vw_, 2)

        df.at[i, "valorisation"] = val_
        df.at[i, "cost_total"]   = cost_
        df.at[i, "performance_latente"] = round(val_ - cost_, 2)

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

    # Mettre "Cash" en bas
    df["__cash_marker"] = df["valeur"].apply(lambda x: 1 if x == "Cash" else 0)
    df.sort_values("__cash_marker", inplace=True, ignore_index=True)

    st.subheader(f"Portefeuille de {client_name}")
    st.write(f"**Valorisation totale du portefeuille :** {total_val:,.2f}")

    # Mode lecture seule
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
            if isinstance(x, (float, int)) and x > 0:
                return "color:green;"
            elif isinstance(x, (float, int)) and x < 0:
                return "color:red;"
            return ""

        def bold_cash(row):
            return (["font-weight:bold;"] * len(row)) if (row["valeur"] == "Cash") else [""] * len(row)

        df_styled = df_display.style.format(
            "{:,.2f}",
            subset=[
                "quantité","vwap","cours","cost_total",
                "valorisation","performance_latente","poids","poids_masi"
            ]
        ).applymap(color_perf, subset=["performance_latente"]) \
         .apply(bold_cash, axis=1)

        st.dataframe(df_styled, use_container_width=True)
        return

    # Mode édition
    with st.expander(f"Modifier Commissions / Taxes / Frais pour {client_name}", expanded=False):
        cinfo = get_client_info(client_name)
        if cinfo:
            exch = float(cinfo.get("exchange_commission_rate") or 0.0)
            mgf  = float(cinfo.get("management_fee_rate") or 0.0)
            pea  = bool(cinfo.get("is_pea") or False)
            tax  = float(cinfo.get("tax_on_gains_rate") or 15.0)
            surp = bool(cinfo.get("bill_surperformance", False))  # new

            new_exch = st.number_input(
                f"Commission d'intermédiation (%) - {client_name}",
                min_value=0.0, value=exch, step=0.01, key=f"exch_{client_name}"
            )
            new_mgmt = st.number_input(
                f"Frais de gestion (%) - {client_name}",
                min_value=0.0, value=mgf, step=0.01, key=f"mgf_{client_name}"
            )
            new_pea  = st.checkbox(
                f"Compte PEA pour {client_name} ?",
                value=pea,
                key=f"pea_{client_name}"
            )
            new_tax = st.number_input(
                f"Taux d'imposition sur les gains (%) - {client_name}",
                min_value=0.0, value=tax, step=0.01, key=f"tax_{client_name}"
            )
            new_surperf = st.checkbox(
                f"Facturer la Surperformance ?",
                value=surp,
                key=f"bill_surperf_{client_name}"
            )

            if st.button(f"Mettre à jour les paramètres pour {client_name}", key=f"update_rates_{client_name}"):
                update_client_rates(
                    client_name,
                    new_exch,
                    new_pea,
                    new_tax,
                    new_mgmt,
                    new_surperf
                )

    columns_display = [
        "valeur","quantité","vwap","cours","cost_total",
        "valorisation","performance_latente","poids_masi","poids","__cash_marker"
    ]
    df = df[columns_display].copy()

    def color_perf(x):
        if isinstance(x, (float,int)) and x>0:
            return "color:green;"
        elif isinstance(x,(float,int)) and x<0:
            return "color:red;"
        return ""

    def bold_cash(row):
        return (["font-weight:bold;"] * len(row)) if (row["valeur"] == "Cash") else [""] * len(row)

    df_styled = df.drop(columns="__cash_marker").style.format(
        "{:,.2f}",
        subset=[
            "quantité","vwap","cours","cost_total",
            "valorisation","performance_latente","poids_masi","poids"
        ]
    ).applymap(color_perf, subset=["performance_latente"]) \
     .apply(bold_cash, axis=1)

    st.write("#### Actifs actuels du portefeuille (Poids Masi à 0% pour Cash)")
    st.dataframe(df_styled, use_container_width=True)

    with st.expander("Édition manuelle du portefeuille (Quantité / VWAP)", expanded=False):
        edit_cols = ["valeur","quantité","vwap"]
        edf = df[edit_cols].drop(columns="__cash_marker", errors="ignore").copy()
        updated_df = st.data_editor(
            edf,
            use_container_width=True,
            key=f"portfolio_editor_{client_name}",
        )
        if st.button(f"💾 Enregistrer les modifications pour {client_name}", key=f"save_edits_btn_{client_name}"):
            from db_utils import portfolio_table
            cid2 = get_client_id(client_name)
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
                    st.error(f"Erreur lors de la sauvegarde pour {valn}: {e}")
            st.success(f"Portefeuille de « {client_name} » mis à jour avec succès!")
            st.experimental_rerun()

    # ACHAT
    st.write("### Opération d'Achat")
    all_stocks = fetch_stocks()
    buy_stock = st.selectbox(
        f"Choisir la valeur à acheter pour {client_name}",
        all_stocks["valeur"].tolist(),
        key=f"buy_s_{client_name}"
    )
    buy_price = st.number_input(
        f"Prix d'achat pour {buy_stock}",
        min_value=0.0,
        value=0.0,
        step=0.01,
        key=f"buy_price_{client_name}"
    )
    buy_qty   = st.number_input(
        f"Quantité à acheter pour {buy_stock}",
        min_value=1.0,
        value=1.0,
        step=1.0,   # For integer shares
        key=f"buy_qty_{client_name}"
    )
    if st.button(f"Acheter {buy_stock}", key=f"buy_btn_{client_name}"):
        buy_shares(client_name, buy_stock, buy_price, buy_qty)

    # VENTE
    st.write("### Opération de Vente")
    existing_stocks = df[df["valeur"] != "Cash"]["valeur"].unique().tolist()
    sell_stock = st.selectbox(
        f"Choisir la valeur à vendre pour {client_name}",
        existing_stocks,
        key=f"sell_s_{client_name}"
    )
    sell_price = st.number_input(
        f"Prix de vente pour {sell_stock}",
        min_value=0.0,
        value=0.0,
        step=0.01,
        key=f"sell_price_{client_name}"
    )
    sell_qty   = st.number_input(
        f"Quantité à vendre pour {sell_stock}",
        min_value=1.0,
        value=1.0,
        step=1.0,
        key=f"sell_qty_{client_name}"
    )
    if st.button(f"Vendre {sell_stock}", key=f"sell_btn_{client_name}"):
        sell_shares(client_name, sell_stock, sell_price, sell_qty)


########################################
# 4) Voir le portefeuille d'un client
########################################
def page_view_client_portfolio():
    st.title("Portefeuille d'un Client")
    c2 = get_all_clients()
    if not c2:
        st.warning("Aucun client trouvé. Veuillez créer un client.")
    else:
        client_selected = st.selectbox("Sélectionner un client", c2, key="view_portfolio_select")
        if client_selected:
            show_portfolio(client_selected, read_only=False)


########################################
# 5) Voir tous les portefeuilles
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
# 6) Inventaire
########################################
def page_inventory():
    st.title("Inventaire des Actifs")

    from collections import defaultdict

    clients = get_all_clients()
    if not clients:
        st.warning("Aucun client n'est disponible. Veuillez créer un client.")
        return

    stocks_df = fetch_stocks()
    master_data = defaultdict(lambda: {"quantity": 0.0, "clients": set()})
    overall_portfolio_sum = 0.0

    for c in clients:
        dfp = get_portfolio(c)
        if dfp.empty:
            continue
        portfolio_val = 0.0
        for _, row in dfp.iterrows():
            val = str(row["valeur"])
            qty = float(row["quantité"])
            match = stocks_df[stocks_df["valeur"] == val]
            live_price = float(match["cours"].values[0]) if not match.empty else 0.0
            val_agg = qty * live_price
            portfolio_val += val_agg
            master_data[val]["quantity"] += qty
            master_data[val]["clients"].add(c)

        overall_portfolio_sum += portfolio_val

    if not master_data:
        st.write("Aucun actif trouvé dans les portefeuilles clients.")
        return

    rows_data = []
    sum_of_all_stocks_val = 0.0
    for val, info in master_data.items():
        match = stocks_df[stocks_df["valeur"] == val]
        price = float(match["cours"].values[0]) if not match.empty else 0.0
        agg_val = info["quantity"] * price
        sum_of_all_stocks_val += agg_val
        rows_data.append({
            "valeur": val,
            "quantité total": info["quantity"],
            "valorisation": agg_val,
            "portefeuille": ", ".join(sorted(info["clients"]))
        })

    # Calcul du poids global
    for row in rows_data:
        if sum_of_all_stocks_val > 0:
            row["poids"] = round((row["valorisation"] / sum_of_all_stocks_val) * 100, 2)
        else:
            row["poids"] = 0.0

    inv_df = pd.DataFrame(rows_data)
    styled_inv = inv_df.style.format(
        {
            "quantité total": "{:,.2f}",
            "valorisation": "{:,.2f}",
            "poids": "{:,.2f}"
        }
    )
    st.dataframe(styled_inv, use_container_width=True)
    st.write(f"### Actif sous gestion: {overall_portfolio_sum:,.2f}")


########################################
# 7) Page du Marché
########################################
def page_market():
    st.title("Marché Boursier")
    st.write("Les cours affichés peuvent présenter un décalage d'environ 15 minutes.")

    from logic import compute_poids_masi
    from db_utils import fetch_stocks

    # Recompute or reuse the global map
    m = compute_poids_masi()
    if not m:
        st.warning("Aucun instrument trouvé, vérifiez la base de données et l'API.")
        return

    stocks_df = fetch_stocks()
    rows = []
    for val, info in m.items():
        rows.append({
            "valeur": val,
            "Capitalisation": info["capitalisation"],
            "Poids Masi": info["poids_masi"]
        })
    df_market = pd.DataFrame(rows)
    df_market = pd.merge(df_market, stocks_df, on="valeur", how="left")
    df_market.rename(columns={"cours": "Cours"}, inplace=True)
    df_market = df_market[["valeur", "Cours", "Capitalisation", "Poids Masi"]]

    df_styled = df_market.style.format(
        {
            "Cours": "{:,.2f}",
            "Capitalisation": "{:,.2f}",
            "Poids Masi": "{:,.2f}"
        }
    )
    st.dataframe(df_styled, use_container_width=True)


########################################
# 8) Page Performance & Fees
########################################
def page_performance_fees():
    """
    Page de gestion des performances et des frais,
    incluant l'édition des périodes existantes et
    l'ajout de la surperformance MASI.
    """

    st.title("Performance et Frais")

    # 1) Sélection du client
    clients = get_all_clients()
    if not clients:
        st.warning("Aucun client trouvé. Veuillez créer un client.")
        return

    client_name = st.selectbox("Sélectionner un client", clients, key="perf_fee_select")
    if not client_name:
        st.info("Veuillez choisir un client pour continuer.")
        return

    cid = get_client_id(client_name)
    if cid is None:
        st.error("Client non valide.")
        return

    # 2) Afficher et éditer (data_editor) les périodes existantes
    st.subheader("Périodes de Performance Existantes")
    df_periods = get_performance_periods_for_client(cid)
    # Make sure columns exist even if empty:
    for col in ["id", "start_date", "start_value", "masi_start_value", "bill_surperformance"]:
        if col not in df_periods.columns:
            df_periods[col] = None

    # Convert to correct dtypes:
    df_periods["start_date"] = pd.to_datetime(df_periods["start_date"], errors="coerce")
    df_periods["start_value"] = pd.to_numeric(df_periods["start_value"], errors="coerce")
    df_periods["masi_start_value"] = pd.to_numeric(df_periods["masi_start_value"], errors="coerce")

    # Fill missing boolean with False for `bill_surperformance` column
    df_periods["bill_surperformance"] = df_periods["bill_surperformance"].fillna(False).astype(bool)

    # Show them in descending order by date
    df_periods = df_periods.sort_values("start_date", ascending=False).reset_index(drop=True)

    st.write("Vous pouvez modifier les valeurs ci-dessous (date, valeur portefeuille, valeur MASI, surperformance?).")

    updated_periods = st.data_editor(
        df_periods,
        use_container_width=True,
        num_rows="dynamic",
        key=f"perf_periods_editor_{cid}",
        column_config={
            "id": st.column_config.TextColumn(
                "ID (read-only)",
                disabled=True
            ),
            "start_date": st.column_config.DateColumn(
                "Date de Début",  
                format="YYYY-MM-DD"
            ),
            "start_value": st.column_config.NumberColumn(
                "Valeur Portefeuille Départ",
                format="%.2f",
                step=0.01
            ),
            "masi_start_value": st.column_config.NumberColumn(
                "Valeur MASI Départ",
                format="%.2f",
                step=0.01
            ),
            "bill_surperformance": st.column_config.CheckboxColumn(
                "Facturer la Surperformance ?"
            )
        }
    )

    # Button to update DB with changes
    if st.button("Enregistrer les modifications sur les Périodes", key=f"save_periods_{cid}"):
        # For each row in updated_periods, update performance_periods table
        for idx, row in updated_periods.iterrows():
            row_id = row.get("id", None)
            if not row_id:
                # No ID => insert new row (or skip)
                # In your DB, 'id' might be serial PK. If you prefer insertion, do:
                perf_row = {
                    "client_id": cid,
                    "start_date": str(row["start_date"].date()) if pd.notnull(row["start_date"]) else None,
                    "start_value": float(row["start_value"] or 0),
                    "masi_start_value": float(row["masi_start_value"] or 0),
                    "bill_surperformance": bool(row["bill_surperformance"])
                }
                try:
                    get_supabase().table("performance_periods").insert(perf_row).execute()
                except Exception as e:
                    st.error(f"Erreur lors de l'insertion (ligne sans ID): {e}")
            else:
                # Update existing row
                perf_update = {
                    "start_date": str(row["start_date"].date()) if pd.notnull(row["start_date"]) else None,
                    "start_value": float(row["start_value"] or 0),
                    "masi_start_value": float(row["masi_start_value"] or 0),
                    "bill_surperformance": bool(row["bill_surperformance"])
                }
                try:
                    get_supabase().table("performance_periods").update(perf_update).eq("id", row_id).execute()
                except Exception as e:
                    st.error(f"Erreur lors de la mise à jour (ID={row_id}): {e}")

        st.success("Modifications enregistrées avec succès!")
        st.experimental_rerun()

    # 3) Form pour ajouter une nouvelle période
    with st.expander("Ajouter une Nouvelle Période"):
        with st.form("perf_period_form", clear_on_submit=True):
            start_date_input = st.date_input("Date de Début", key="new_start_date")
            start_value_input = st.number_input("Valeur de Départ du Portefeuille", min_value=0.0, step=0.01, value=0.0, key="new_portf_val")
            masi_start_input = st.number_input("Valeur de Départ du MASI", min_value=0.0, step=0.01, value=0.0, key="new_masi_val")
            surperf_checked = st.checkbox("Facturer surperformance ?", value=False, key="new_surperf_check")

            new_submitted = st.form_submit_button("Créer la nouvelle période")
            if new_submitted:
                try:
                    row_insert = {
                        "client_id": cid,
                        "start_date": str(start_date_input),
                        "start_value": float(start_value_input),
                        "masi_start_value": float(masi_start_input),
                        "bill_surperformance": bool(surperf_checked)
                    }
                    get_supabase().table("performance_periods").insert(row_insert).execute()
                    st.success("Nouvelle période créée!")
                    st.experimental_rerun()
                except Exception as e:
                    st.error(f"Erreur lors de la création de la nouvelle période: {e}")

    # 4) Calculer la performance pour la période sélectionnée
    st.subheader("Calculer la Performance & les Frais (Portefeuille vs. MASI)")
    if not updated_periods.empty:
        # Let user pick which row (by date) to compute
        date_options = updated_periods["start_date"].dropna().unique().tolist()
        if not date_options:
            st.info("Aucune date de début valide pour calculer la performance.")
            return

        sel_date = st.selectbox("Choisir la date de début de la période",
                                options=date_options,
                                format_func=lambda d: d.strftime("%Y-%m-%d") if pd.notnull(d) else "",
                                key=f"calc_perf_startdate_{cid}")
        if sel_date:
            # find that row
            row_sel = updated_periods.loc[updated_periods["start_date"] == sel_date]
            if row_sel.empty:
                st.warning("Aucune donnée pour cette date.")
                return
            row_sel = row_sel.iloc[0]  # pick first

            # Extract data
            st_val   = float(row_sel.get("start_value", 0))
            st_masi  = float(row_sel.get("masi_start_value", 0))
            # Is the user to be billed on surperformance or normal? We'll fetch from row or from client
            # This is stored either in row or in the clients table
            surperf_mode = bool(row_sel.get("bill_surperformance", False))

            # Récupérer la valeur du portefeuille
            df_portfolio = get_portfolio(client_name)
            if df_portfolio.empty:
                st.warning("Portefeuille vide pour ce client.")
            else:
                # Calculer la valeur courante
                stocks_df = fetch_stocks()
                portf_current_val = 0.0
                for _, prow in df_portfolio.iterrows():
                    val_ = str(prow["valeur"])
                    match_ = stocks_df[stocks_df["valeur"] == val_]
                    live_price_ = float(match_["cours"].values[0]) if not match_.empty else 0.0
                    qty_ = float(prow["quantité"])
                    portf_current_val += (qty_ * live_price_)

                gains_portf = portf_current_val - st_val
                perf_portf_pct = (gains_portf / st_val * 100.0) if (st_val > 0) else 0.0

                # MASI
                masi_now = get_current_masi()  # your function that fetches the CASABOURSE
                gains_masi = masi_now - st_masi
                perf_masi_pct = (gains_masi / st_masi * 100.0) if (st_masi>0) else 0.0

                # Surperformance
                surperf_abs = gains_portf - gains_masi
                surperf_pct = 0.0
                if st_val>0:
                    surperf_pct = surperf_abs / st_val * 100.0

                # Facturer
                cinfo = get_client_info(client_name)
                mgmt_rate = float(cinfo.get("management_fee_rate", 0.0))/100.0

                if surperf_mode:
                    # On facture la surperformance
                    base_amount = max(surperf_abs, 0)
                    fees_owed = base_amount * mgmt_rate
                else:
                    # On facture la performance standard du portefeuille
                    base_amount = max(gains_portf, 0)
                    fees_owed = base_amount * mgmt_rate

                # Afficher un tableau net
                results_data = [
                    {
                        "Portefeuille Départ": st_val,
                        "Portefeuille Actuel": portf_current_val,
                        "Gains (Abs.)": gains_portf,
                        "Performance Portf. %": perf_portf_pct,
                        "MASI Départ": st_masi,
                        "MASI Actuel": masi_now,
                        "Gains MASI": gains_masi,
                        "Perf. MASI %": perf_masi_pct,
                        "Surperformance Abs.": surperf_abs,
                        "Surperformance %": surperf_pct,
                        "Facturation (Surperf?)": str(surperf_mode),
                        "Frais Owed": fees_owed
                    }
                ]
                df_res = pd.DataFrame(results_data)
                # Style
                numeric_cols = df_res.columns.tolist()
                df_res_style = df_res.style.format(
                    subset=numeric_cols,
                    formatter="{:,.2f}"
                )
                st.dataframe(df_res_style, use_container_width=True)

    # 5) Résumé de Performance (tous les clients)
    st.subheader("Résumé de Performance (tous les clients)")
    df_latest = get_latest_performance_period_for_all_clients()
    if df_latest.empty:
        st.info("Aucune donnée de performance pour aucun client.")
    else:
        summary_rows = []
        stocks_df = fetch_stocks()
        masi_now = get_current_masi()
        all_cls = get_all_clients()

        for _, rrow in df_latest.iterrows():
            c_id = rrow["client_id"]
            s_val = float(rrow.get("start_value", 0))
            s_masi= float(rrow.get("masi_start_value", 0))
            ddate= str(rrow.get("start_date",""))
            surperf_bool = bool(rrow.get("bill_surperformance", False))

            # Retrouver le nom du client
            name_found = None
            for cxx in all_cls:
                if get_client_id(cxx) == c_id:
                    name_found = cxx
                    break
            if not name_found:
                continue

            # Valeur courante
            pdf = get_portfolio(name_found)
            cur_val = 0.0
            if not pdf.empty:
                for _, p2 in pdf.iterrows():
                    v2 = str(p2["valeur"])
                    mm = stocks_df[stocks_df["valeur"]==v2]
                    p2_price = float(mm["cours"].values[0]) if not mm.empty else 0.0
                    cur_val += (float(p2["quantité"]) * p2_price)

            gains_portf = cur_val - s_val
            perf_portf_pct = (gains_portf / s_val * 100) if s_val>0 else 0.0
            gains_masi = masi_now - s_masi
            perf_masi_pct = (gains_masi / s_masi * 100) if s_masi>0 else 0.0

            surperf_abs = gains_portf - gains_masi
            surperf_pct = (surperf_abs/s_val*100) if s_val>0 else 0.0

            # Frais
            cinfo_db = get_client_info(name_found)
            mgmtr = float(cinfo_db.get("management_fee_rate",0))/100.0
            if surperf_bool:
                base_amt = max(surperf_abs, 0)
            else:
                base_amt = max(gains_portf, 0)
            fees2 = base_amt * mgmtr

            summary_rows.append({
                "Client": name_found,
                "Date Début": ddate,
                "Portf. Départ": s_val,
                "MASI Départ": s_masi,
                "Portf. Actuel": cur_val,
                "Gains Portf.": gains_portf,
                "Perf. Portf. %": perf_portf_pct,
                "Gains MASI": gains_masi,
                "Perf. MASI %": perf_masi_pct,
                "Surperf. Abs": surperf_abs,
                "Surperf. %": surperf_pct,
                "Facture Surperf?": surperf_bool,
                "Frais": fees2
            })

        if not summary_rows:
            st.info("Aucune donnée valide à afficher.")
        else:
            df_sum = pd.DataFrame(summary_rows)
            format_dict = {
                "Portf. Départ": "{:,.2f}",
                "MASI Départ": "{:,.2f}",
                "Portf. Actuel": "{:,.2f}",
                "Gains Portf.": "{:,.2f}",
                "Perf. Portf. %": "{:,.2f}",
                "Gains MASI": "{:,.2f}",
                "Perf. MASI %": "{:,.2f}",
                "Surperf. Abs": "{:,.2f}",
                "Surperf. %": "{:,.2f}",
                "Frais": "{:,.2f}"
            }
            df_sum_style = df_sum.style.format(format_dict)
            st.dataframe(df_sum_style, use_container_width=True)

            # Totaux
            total_pstart = df_sum["Portf. Départ"].sum()
            total_pcur   = df_sum["Portf. Actuel"].sum()
            total_fees   = df_sum["Frais"].sum()

            totals_df = pd.DataFrame([{
                "Somme Départ": total_pstart,
                "Somme Actuel": total_pcur,
                "Total Frais": total_fees
            }])
            st.write("#### Totaux Globaux")
            st.dataframe(
                totals_df.style.format("{:,.2f}"),
                use_container_width=True
            )
