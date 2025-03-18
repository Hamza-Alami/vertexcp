# pages.py

import streamlit as st
import pandas as pd
import numpy as np
from collections import defaultdict

# --- Import from db_utils ---
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
    # Any other needed functions, e.g. get_portfolio, fetch_stocks if you prefer
)

# --- Import from logic ---
from logic import (
    get_current_masi,
    buy_shares,
    sell_shares,
    new_portfolio_creation_ui,
    poids_masi_map,         # the global dict for Poids Masi
    # any other logic items you might need
)

########################################
# 1) Manage Clients Page
########################################
def page_manage_clients():
    """Page: Gérer la création, la modification et la suppression des clients."""
    st.title("Gestion des Clients")
    existing_clients = get_all_clients()

    # === Créer un nouveau client ===
    with st.form("add_client_form", clear_on_submit=True):
        new_client_name = st.text_input("Nom du nouveau client", key="new_client_input")
        if st.form_submit_button("➕ Créer le client"):
            create_client(new_client_name)

    # === Modifier/Supprimer un client si la liste n'est pas vide ===
    if existing_clients:
        # Renommer un client
        with st.form("rename_client_form", clear_on_submit=True):
            rename_choice = st.selectbox(
                "Sélectionner le client à renommer",
                options=existing_clients,
                key="rename_choice"
            )
            rename_new = st.text_input("Nouveau nom du client", key="rename_text")
            if st.form_submit_button("✏️ Renommer ce client"):
                rename_client(rename_choice, rename_new)

        # Supprimer un client
        with st.form("delete_client_form", clear_on_submit=True):
            delete_choice = st.selectbox(
                "Sélectionner le client à supprimer",
                options=existing_clients,
                key="delete_choice"
            )
            if st.form_submit_button("🗑️ Supprimer ce client"):
                delete_client(delete_choice)


########################################
# 2) Create Portfolio Page
########################################
def page_create_portfolio():
    """Page: Créer un portefeuille pour un client n'ayant pas encore de portefeuille."""
    st.title("Création d'un Portefeuille Client")
    clist = get_all_clients()
    if not clist:
        st.warning("Aucun client trouvé. Veuillez d'abord créer un client.")
        return

    cselect = st.selectbox("Sélectionner un client", clist, key="create_pf_select")
    if cselect:
        # Vérifier si le client a déjà un portefeuille
        if client_has_portfolio(cselect):
            st.warning(f"Le client '{cselect}' dispose déjà d'un portefeuille.")
        else:
            # Appeler la fonction de création guidée
            new_portfolio_creation_ui(cselect)


########################################
# 3) Afficher le portefeuille d'un client
########################################
def show_portfolio(client_name, read_only=False):
    """
    Affiche le portefeuille d'un client, en mode lecture seule ou en mode édition.
    S'appuie sur db_utils pour récupérer les données, puis recalcule la valorisation,
    la performance latente, etc.
    """
    cid = get_client_id(client_name)
    if cid is None:
        st.warning("Client introuvable.")
        return

    df = db_utils.get_portfolio(client_name)
    if df.empty:
        st.warning(f"Aucun portefeuille trouvé pour « {client_name} ».")
        return

    # Récupérer les cours actualisés
    stocks = db_utils.fetch_stocks()

    # Convertir la colonne 'quantité' en entier (sauf si c'est un float pour Cash)
    df = df.copy()
    if "quantité" in df.columns:
        # On force 'quantité' en int (int64). (Gaffe si Cash devait être float.)
        df["quantité"] = df["quantité"].astype('int64')

    # Calculer cours, valorisation, cost_total, etc.
    for i, row in df.iterrows():
        val = str(row["valeur"])
        match = stocks[stocks["valeur"] == val]
        live_price = float(match["cours"].values[0]) if not match.empty else 0.0

        qty_ = int(row["quantité"])
        vw_  = float(row.get("vwap", 0.0))

        val_ = round(qty_ * live_price, 2)
        cost_ = round(qty_ * vw_, 2)
        perf_ = round(val_ - cost_, 2)

        df.at[i, "cours"] = live_price
        df.at[i, "valorisation"] = val_
        df.at[i, "cost_total"] = cost_
        df.at[i, "performance_latente"] = perf_

        # Poids Masi: 0 pour le Cash, sinon chercher dans poids_masi_map
        if val == "Cash":
            df.at[i, "poids_masi"] = 0.0
        else:
            info = poids_masi_map.get(val, {"poids_masi": 0.0})
            df.at[i, "poids_masi"] = info["poids_masi"]

    # Calcul du poids du stock dans le portefeuille
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

    # --- Mode lecture seule ---
    if read_only:
        drop_cols = ["id", "client_id", "is_cash", "__cash_marker"]
        for col in drop_cols:
            if col in df.columns:
                df.drop(columns=col, inplace=True)

        columns_display = [
            "valeur", "quantité", "vwap", "cours",
            "cost_total", "valorisation", "performance_latente",
            "poids", "poids_masi"
        ]
        avail_cols = [x for x in columns_display if x in df.columns]
        df_display = df[avail_cols].copy()

        # Mise en forme (perf en vert/rouge, Cash en gras, etc.)
        def color_perf(x):
            if isinstance(x, (float, int)) and x > 0:
                return "color:green;"
            elif isinstance(x, (float, int)) and x < 0:
                return "color:red;"
            return ""

        def bold_cash(row):
            return ["font-weight:bold;"] * len(row) if row["valeur"] == "Cash" else ["" for _ in row]

        df_styled = (
            df_display
            .style
            .format("{:,.2f}",
                    subset=["quantité","vwap","cours","cost_total",
                            "valorisation","performance_latente","poids","poids_masi"])
            .applymap(color_perf, subset=["performance_latente"])
            .apply(bold_cash, axis=1)
        )

        st.dataframe(df_styled, use_container_width=True)
        return

    # --- Mode édition ---
    with st.expander(f"Modifier Commissions / Taxes / Frais pour {client_name}", expanded=False):
        cinfo = get_client_info(client_name)
        if cinfo:
            exch = float(cinfo.get("exchange_commission_rate") or 0.0)
            mgf  = float(cinfo.get("management_fee_rate") or 0.0)
            pea  = bool(cinfo.get("is_pea") or False)
            tax  = float(cinfo.get("tax_on_gains_rate") or 15.0)

            new_exch = st.number_input(
                f"Commission d'intermédiation (%) - {client_name}",
                min_value=0.0,
                value=exch,
                step=0.01,
                key=f"exch_{client_name}"
            )
            new_mgmt = st.number_input(
                f"Frais de gestion (%) - {client_name}",
                min_value=0.0,
                value=mgf,
                step=0.01,
                key=f"mgf_{client_name}"
            )
            new_pea = st.checkbox(
                f"Compte PEA pour {client_name} ?",
                value=pea,
                key=f"pea_{client_name}"
            )
            new_tax = st.number_input(
                f"Taux d'imposition sur les gains (%) - {client_name}",
                min_value=0.0,
                value=tax,
                step=0.01,
                key=f"tax_{client_name}"
            )

            if st.button(f"Mettre à jour les paramètres pour {client_name}", key=f"update_rates_{client_name}"):
                update_client_rates(client_name, new_exch, new_pea, new_tax, new_mgmt)

    # On affiche le DataFrame complet (en mode lecture + éditeur)
    columns_display = [
        "valeur","quantité","vwap","cours","cost_total",
        "valorisation","performance_latente","poids_masi","poids","__cash_marker"
    ]
    df = df[columns_display].copy()

    def color_perf(x):
        if isinstance(x, (float,int)) and x > 0:
            return "color:green;"
        elif isinstance(x,(float,int)) and x < 0:
            return "color:red;"
        return ""

    def bold_cash(row):
        return ["font-weight:bold;"] * len(row) if row["valeur"] == "Cash" else ["" for _ in row]

    df_styled = (
        df.drop(columns="__cash_marker")
          .style
          .format("{:,.2f}",
                  subset=["quantité","vwap","cours","cost_total",
                          "valorisation","performance_latente","poids_masi","poids"])
          .applymap(color_perf, subset=["performance_latente"])
          .apply(bold_cash, axis=1)
    )

    st.write("#### Actifs actuels du portefeuille (Poids Masi à 0% pour Cash)")
    st.dataframe(df_styled, use_container_width=True)

    # --- Édition manuelle: quantité / VWAP ---
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
            for _, row2 in updated_df.iterrows():
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

    # --- Achat ---
    st.write("### Opération d'Achat")
    _stocks = db_utils.fetch_stocks()
    buy_stock = st.selectbox(
        f"Choisir la valeur à acheter pour {client_name}",
        _stocks["valeur"].tolist(),
        key=f"buy_s_{client_name}"
    )
    buy_price = st.number_input(
        f"Prix d'achat pour {buy_stock}",
        min_value=0.0,
        value=0.0,
        step=0.01,
        key=f"buy_price_{client_name}"
    )
    # Quantité d'achat => entier
    buy_qty = st.number_input(
        f"Quantité à acheter pour {buy_stock}",
        min_value=1,  # ENTIER
        value=1,
        step=1,
        key=f"buy_qty_{client_name}"
    )
    if st.button(f"Acheter {buy_stock}", key=f"buy_btn_{client_name}"):
        buy_shares(client_name, buy_stock, buy_price, float(buy_qty))

    # --- Vente ---
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
    sell_qty = st.number_input(
        f"Quantité à vendre pour {sell_stock}",
        min_value=1,  # ENTIER
        value=1,
        step=1,
        key=f"sell_qty_{client_name}"
    )
    if st.button(f"Vendre {sell_stock}", key=f"sell_btn_{client_name}"):
        sell_shares(client_name, sell_stock, sell_price, float(sell_qty))


########################################
# 4) Voir le portefeuille d'un client
########################################
def page_view_client_portfolio():
    """Page: Permettre de visualiser et d'éditer un portefeuille en particulier."""
    st.title("Portefeuille d'un Client")
    c2 = get_all_clients()
    if not c2:
        st.warning("Aucun client trouvé. Veuillez créer un client.")
        return

    client_selected = st.selectbox("Sélectionner un client", c2, key="view_portfolio_select")
    if client_selected:
        show_portfolio(client_selected, read_only=False)


########################################
# 5) Voir tous les portefeuilles
########################################
def page_view_all_portfolios():
    """Page: Affiche tous les portefeuilles clients en mode lecture seule."""
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
    """
    Page: Recensement global de tous les actifs détenus par tous les portefeuilles.
    """
    st.title("Inventaire des Actifs")

    from collections import defaultdict

    stocks = db_utils.fetch_stocks()
    clients_list = get_all_clients()
    if not clients_list:
        st.warning("Aucun client n'est disponible. Veuillez créer un client.")
        return

    master_data = defaultdict(lambda: {"quantity": 0.0, "clients": set()})
    overall_portfolio_sum = 0.0

    # Agréger la quantité de chaque valeur
    for c in clients_list:
        dfp = db_utils.get_portfolio(c)
        if dfp.empty:
            continue

        portfolio_val = 0.0
        for _, row in dfp.iterrows():
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
        st.write("Aucun actif trouvé dans les portefeuilles clients.")
        return

    # Construire le DataFrame
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

    # Calculer le poids relatif
    for row in rows_data:
        if sum_of_all_stocks_val > 0:
            row["poids"] = round((row["valorisation"] / sum_of_all_stocks_val) * 100, 2)
        else:
            row["poids"] = 0.0

    inv_df = pd.DataFrame(rows_data)
    # Format the numeric columns with 2 decimals + thousand separators
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
    """
    Page: Affiche les cours du marché, la capitalisation et le poids Masi pour chaque valeur,
    selon les données renvoyées par votre compute_poids_masi().
    """
    st.title("Marché Boursier")
    st.write("Les cours affichés peuvent présenter un décalage d'environ 15 minutes.")

    from logic import compute_poids_masi
    m = compute_poids_masi()
    if not m:
        st.warning("Aucun instrument trouvé, vérifiez la base de données et l'API.")
        return

    stocks = db_utils.fetch_stocks()
    rows = []
    for val, info in m.items():
        rows.append({
            "valeur": val,
            "Capitalisation": info["capitalisation"],
            "Poids Masi": info["poids_masi"]
        })
    df_market = pd.DataFrame(rows)
    df_market = pd.merge(df_market, stocks, on="valeur", how="left")
    df_market.rename(columns={"cours": "Cours"}, inplace=True)
    df_market = df_market[["valeur", "Cours", "Capitalisation", "Poids Masi"]]

    # Format with thousand separators + 2 decimals
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
    Page: Gère la performance du portefeuille par rapport au MASI,
    la surperformance, et le calcul de frais éventuels.
    """
    st.title("Performance et Frais")

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

    # 1) Ajouter / mettre à jour la période de performance
    with st.expander("Ajouter ou modifier la Date de Début / la Valeur de Départ (Portefeuille & MASI)"):
        with st.form("perf_period_form", clear_on_submit=True):
            start_date_input = st.date_input("Date de Début")
            start_value_input = st.number_input("Valeur de Départ du Portefeuille", min_value=0.0, step=0.01, value=0.0)
            masi_start_input = st.number_input("Valeur de Départ du MASI (à la même date)", min_value=0.0, step=0.01, value=0.0)
            submitted = st.form_submit_button("Enregistrer la période de performance")
            if submitted:
                start_date_str = str(start_date_input)
                db_utils.create_performance_period(cid, start_date_str, start_value_input, masi_start_input)

    # 2) Afficher toutes les périodes existantes de ce client
    with st.expander("Périodes de Performance Existantes"):
        df_periods = db_utils.get_performance_periods_for_client(cid)
        if df_periods.empty:
            st.info("Aucune période de performance trouvée pour ce client.")
        else:
            tmp = df_periods.copy()
            numeric_cols = ["start_value","masi_start_value"]
            for col in numeric_cols:
                if col in tmp.columns:
                    tmp[col] = tmp[col].apply(lambda x: f"{x:,.2f}")
            st.dataframe(tmp, use_container_width=True)

    # 3) Permettre de choisir une "start_date" pour calculer la performance
    with st.expander("Calculer la Performance & les Frais à partir d'une Date de Début"):
        if not df_periods.empty:
            df_periods = df_periods.sort_values("start_date", ascending=False)
            start_options = df_periods["start_date"].unique().tolist()
            selected_start_date = st.selectbox(
                "Choisir la date de départ pour le calcul de performance",
                start_options,
                key="calc_perf_startdate"
            )
            row_chosen = df_periods[df_periods["start_date"] == selected_start_date].iloc[0]
            chosen_start_value   = float(row_chosen.get("start_value", 0))
            chosen_masi_startval = float(row_chosen.get("masi_start_value", 0))

            # Récupérer la valeur du portefeuille actuel
            df_portfolio = db_utils.get_portfolio(client_name)
            if df_portfolio.empty:
                st.warning("Ce client ne possède aucun portefeuille.")
            else:
                stocks_df = db_utils.fetch_stocks()
                total_val = 0.0
                for _, prow in df_portfolio.iterrows():
                    val = str(prow["valeur"])
                    match = stocks_df[stocks_df["valeur"] == val]
                    live_price = float(match["cours"].values[0]) if not match.empty else 0.0
                    qty_ = float(prow["quantité"])
                    total_val += (qty_ * live_price)

                # Gains du portefeuille
                gains = total_val - chosen_start_value
                perf_pct = (gains / chosen_start_value)*100.0 if chosen_start_value>0 else 0.0

                # Récupérer la MASI courante
                masi_current = get_current_masi()
                gains_masi = masi_current - chosen_masi_startval if chosen_masi_startval>0 else 0.0
                perf_masi_pct = (gains_masi / chosen_masi_startval)*100.0 if chosen_masi_startval>0 else 0.0

                surperf_abs = gains - gains_masi
                surperf_pct = (surperf_abs / chosen_start_value)*100.0 if chosen_start_value>0 else 0.0

                st.write(f"**Portefeuille**: Départ= {chosen_start_value:,.2f}, Actuel= {total_val:,.2f}")
                st.write(f"**Gains**= {gains:,.2f} => Perf= {perf_pct:,.2f}%")

                st.write(f"**MASI**: Départ= {chosen_masi_startval:,.2f}, Actuel= {masi_current:,.2f}")
                st.write(f"**Gains MASI**= {gains_masi:,.2f} => Perf MASI= {perf_masi_pct:,.2f}%")

                st.write(f"**Surperformance absolue**= {surperf_abs:,.2f}")
                st.write(f"**Surperformance %**= {surperf_pct:,.2f}%")

                cinfo = get_client_info(client_name)
                mgmt_rate = float(cinfo.get("management_fee_rate",0.0))/100.0

                if cinfo.get("bill_surperformance", False):
                    # Facturation sur surperformance
                    base_amount = max(0, surperf_abs)
                    fees_owed = base_amount * mgmt_rate
                    st.write(f"Facturation sur Surperformance => Frais= {fees_owed:,.2f}")
                else:
                    # Facturation standard
                    base_amount = max(0, gains)
                    fees_owed = base_amount * mgmt_rate
                    st.write(f"Facturation standard => Frais= {fees_owed:,.2f}")

    # 4) Résumé de Performance (tous les clients)
    with st.expander("Résumé de Performance (tous les clients)"):
        df_latest = db_utils.get_latest_performance_period_for_all_clients()
        if df_latest.empty:
            st.info("Aucune donnée de performance pour aucun client.")
        else:
            summary_rows = []
            stocks_df = db_utils.fetch_stocks()
            masi_current = get_current_masi()

            clients_list = get_all_clients()

            for _, rrow in df_latest.iterrows():
                c_id   = rrow["client_id"]
                s_val  = float(rrow.get("start_value",0))
                s_masi = float(rrow.get("masi_start_value",0))
                ddate  = str(rrow.get("start_date",""))

                # Retrouver le client
                cinfo_name = None
                for ccc in clients_list:
                    if get_client_id(ccc) == c_id:
                        cinfo_name = ccc
                        break
                if not cinfo_name:
                    continue

                # Valeur courante du portefeuille
                pdf = db_utils.get_portfolio(cinfo_name)
                cur_val = 0.0
                if not pdf.empty:
                    for _, prow2 in pdf.iterrows():
                        val2 = str(prow2["valeur"])
                        mm = stocks_df[stocks_df["valeur"] == val2]
                        lp = float(mm["cours"].values[0]) if not mm.empty else 0.0
                        q2 = float(prow2["quantité"])
                        cur_val += (q2 * lp)

                gains_portf = cur_val - s_val
                perf_portf_pct = (gains_portf / s_val)*100.0 if s_val>0 else 0.0

                gains_masi = masi_current - s_masi if s_masi>0 else 0.0
                perf_masi_pct = (gains_masi / s_masi)*100.0 if s_masi>0 else 0.0

                surperf = gains_portf - gains_masi
                surperf_pct = (surperf / s_val)*100.0 if s_val>0 else 0.0

                cinfo_db = get_client_info(cinfo_name)
                mgmtr = float(cinfo_db.get("management_fee_rate", 0))/100.0

                if cinfo_db.get("bill_surperformance", False):
                    base_amount = max(0, surperf)
                    fees2 = base_amount * mgmtr
                else:
                    base_amount = max(0, gains_portf)
                    fees2 = base_amount * mgmtr

                summary_rows.append({
                    "Client": cinfo_name,
                    "Date Début": ddate,
                    "Portf Start": s_val,
                    "MASI Start": s_masi,
                    "Portf Current": cur_val,
                    "Gains Portf": gains_portf,
                    "Perf Portf %": perf_portf_pct,
                    "Gains MASI": gains_masi,
                    "Perf MASI %": perf_masi_pct,
                    "Surperformance": surperf,
                    "Surperf %": surperf_pct,
                    "Frais": fees2,
                })

            if not summary_rows:
                st.info("Aucune donnée valide à afficher.")
            else:
                df_sum = pd.DataFrame(summary_rows)
                format_dict = {
                    "Portf Start": "{:,.2f}",
                    "MASI Start": "{:,.2f}",
                    "Portf Current": "{:,.2f}",
                    "Gains Portf": "{:,.2f}",
                    "Perf Portf %": "{:,.2f}",
                    "Gains MASI": "{:,.2f}",
                    "Perf MASI %": "{:,.2f}",
                    "Surperformance": "{:,.2f}",
                    "Surperf %": "{:,.2f}",
                    "Frais": "{:,.2f}",
                }
                df_styled = df_sum.style.format(format_dict)
                st.dataframe(df_styled, use_container_width=True)

                # Totaux
                total_portf_start = df_sum["Portf Start"].sum()
                total_portf_cur   = df_sum["Portf Current"].sum()
                total_fees        = df_sum["Frais"].sum()

                totals_df = pd.DataFrame([{
                    "Somme Start Value": total_portf_start,
                    "Somme Current": total_portf_cur,
                    "Somme Frais": total_fees
                }])
                st.write("#### Totaux Globaux")
                st.dataframe(
                    totals_df.style.format("{:,.2f}"),
                    use_container_width=True
                )
