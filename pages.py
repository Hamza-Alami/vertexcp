# pages.py

import streamlit as st
import pandas as pd
from collections import defaultdict
from datetime import date

import db_utils  # your utilities
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
    # Performance
    get_performance_periods_for_client,
    create_performance_period,
    update_performance_period_rows,   # We'll define a new function in db_utils to handle row updates
    get_latest_performance_period_for_all_clients,
)
from logic import (
    buy_shares,
    sell_shares,
    new_portfolio_creation_ui,
    poids_masi_map,
    get_current_masi
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
    else:
        cselect = st.selectbox("Sélectionner un client", clist, key="create_pf_select")
        if cselect:
            if client_has_portfolio(cselect):
                st.warning(f"Le client '{cselect}' dispose déjà d'un portefeuille.")
            else:
                new_portfolio_creation_ui(cselect)

########################################
# 3) Afficher / Gérer un portefeuille
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

    stocks = db_utils.fetch_stocks()

    df = df.copy()
    # Ensure 'quantité' is integer
    if "quantité" in df.columns:
        df["quantité"] = df["quantité"].astype(int, errors="ignore")

    # Recalculate columns
    for i, row in df.iterrows():
        val = str(row["valeur"])
        match = stocks[stocks["valeur"] == val]
        live_price = float(match["cours"].values[0]) if not match.empty else 0.0
        df.at[i, "cours"] = live_price

        qty_ = row.get("quantité", 0)
        if pd.isna(qty_):
            qty_ = 0
        qty_ = float(qty_)

        vw_  = float(row.get("vwap", 0.0))
        val_ = round(qty_ * live_price, 2)
        df.at[i, "valorisation"] = val_

        cost_ = round(qty_ * vw_, 2)
        df.at[i, "cost_total"] = cost_
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

    df["__cash_marker"] = df["valeur"].apply(lambda x: 1 if x == "Cash" else 0)
    df.sort_values("__cash_marker", inplace=True, ignore_index=True)

    st.subheader(f"Portefeuille de {client_name}")
    st.write(f"**Valorisation totale du portefeuille :** {total_val:,.2f}")

    # If read_only => style only
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
        df_disp = df[columns_display].copy()
        def color_perf(x):
            if isinstance(x, (float, int)) and x > 0:
                return "color:green;"
            elif isinstance(x, (float, int)) and x < 0:
                return "color:red;"
            return ""
        def bold_cash(row):
            if row["valeur"] == "Cash":
                return ["font-weight:bold;"] * len(row)
            return ["" for _ in row]

        df_styled = df_disp.style.format(
            "{:,.2f}",
            subset=["quantité","vwap","cours","cost_total","valorisation","performance_latente","poids","poids_masi"]
        ).applymap(color_perf, subset=["performance_latente"]) \
         .apply(bold_cash, axis=1)
        st.dataframe(df_styled, use_container_width=True)
        return

    # Not read_only => let user edit commissions + buy/sell
    # Commission / Taxes / Surperformance
    with st.expander(f"Modifier Commissions / Taxes / Frais pour {client_name}", expanded=False):
        cinfo = get_client_info(client_name)
        if cinfo:
            exch = float(cinfo.get("exchange_commission_rate") or 0.0)
            mgf  = float(cinfo.get("management_fee_rate") or 0.0)
            pea  = bool(cinfo.get("is_pea") or False)
            tax  = float(cinfo.get("tax_on_gains_rate") or 15.0)
            bill_surf = bool(cinfo.get("bill_surperformance", False))

            new_exch = st.number_input(
                "Commission d'intermédiation (%)", min_value=0.0, value=exch, step=0.01, key=f"exch_{client_name}"
            )
            new_mgmt = st.number_input(
                "Frais de gestion (%)", min_value=0.0, value=mgf, step=0.01, key=f"mgf_{client_name}"
            )
            new_pea  = st.checkbox("Compte PEA ?", value=pea, key=f"pea_{client_name}")
            new_tax  = st.number_input(
                "Taux d'imposition sur les gains (%)", min_value=0.0, value=tax, step=0.01, key=f"tax_{client_name}"
            )
            new_bill = st.checkbox("Facturer Surperformance ?", value=bill_surf, key=f"billSurf_{client_name}")

            if st.button(f"Mettre à jour les paramètres pour {client_name}", key=f"update_rates_{client_name}"):
                update_client_rates(client_name, new_exch, new_pea, new_tax, new_mgmt, new_bill)

    columns_display = [
        "valeur","quantité","vwap","cours","cost_total",
        "valorisation","performance_latente","poids_masi","poids","__cash_marker"
    ]
    df2 = df[columns_display].copy()

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

    df_styled = df2.drop(columns="__cash_marker").style.format(
        "{:,.2f}",
        subset=["quantité","vwap","cours","cost_total","valorisation","performance_latente","poids_masi","poids"]
    ).applymap(color_perf, subset=["performance_latente"]) \
     .apply(bold_cash, axis=1)

    st.write("#### Actifs actuels du portefeuille")
    st.dataframe(df_styled, use_container_width=True)

    # Manual Edits data_editor
    with st.expander("Édition manuelle (Quantité / VWAP)", expanded=False):
        edit_cols = ["valeur", "quantité", "vwap"]
        edf = df2[edit_cols].drop(columns="__cash_marker", errors="ignore").copy()

        # We want quantités as int => so let's ensure edf["quantité"] is int typed:
        edf["quantité"] = edf["quantité"].astype(int, errors="ignore")

        updated_df = st.data_editor(
            edf,
            use_container_width=True,
        )
        if st.button(f"💾 Enregistrer modifications"):
            from db_utils import portfolio_table
            cid2 = get_client_id(client_name)
            for idx, row2 in updated_df.iterrows():
                valn = str(row2["valeur"])
                qn   = int(row2["quantité"])
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

    # BUY
    st.write("### Opération d'Achat")
    _stocks = db_utils.fetch_stocks()
    buy_stock = st.selectbox("Choisir la valeur à acheter", _stocks["valeur"].tolist(), key=f"buy_s_{client_name}")
    buy_price = st.number_input("Prix d'achat", min_value=0.0, value=0.0, step=0.01, key=f"buy_price_{client_name}")
    buy_qty   = st.number_input("Quantité à acheter", min_value=1, value=1, step=1, key=f"buy_qty_{client_name}")
    if st.button("Acheter"):
        buy_shares(client_name, buy_stock, buy_price, float(buy_qty))

    # SELL
    st.write("### Opération de Vente")
    existing_stocks = df2[df2["valeur"] != "Cash"]["valeur"].unique().tolist()
    sell_stock = st.selectbox("Choisir la valeur à vendre", existing_stocks, key=f"sell_s_{client_name}")
    sell_price = st.number_input("Prix de vente", min_value=0.0, value=0.0, step=0.01, key=f"sell_price_{client_name}")
    sell_qty   = st.number_input("Quantité à vendre", min_value=1, value=1, step=1, key=f"sell_qty_{client_name}")
    if st.button("Vendre"):
        sell_shares(client_name, sell_stock, sell_price, float(sell_qty))

########################################
# 4) View Single Portfolio
########################################
def page_view_client_portfolio():
    st.title("Portefeuille d'un Client")
    c2 = get_all_clients()
    if not c2:
        st.warning("Aucun client trouvé.")
    else:
        client_selected = st.selectbox("Sélectionner un client", c2, key="view_portfolio_select")
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

    from db_utils import fetch_stocks
    stocks = fetch_stocks()

    clients = get_all_clients()
    if not clients:
        st.warning("Aucun client n'est disponible.")
        return

    master_data = defaultdict(lambda: {"quantity": 0.0, "clients": set()})
    overall_val = 0.0

    for c in clients:
        dfp = get_portfolio(c)
        if not dfp.empty:
            portf_val = 0.0
            for _, row in dfp.iterrows():
                val = str(row["valeur"])
                qty = float(row["quantité"])
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
        if sum_stocks_val>0:
            row["poids"] = round((row["valorisation"]/sum_stocks_val)*100, 2)
        else:
            row["poids"] = 0.0

    df_inv = pd.DataFrame(rows)
    fmt_dict = {
        "quantité total": "{:,.0f}",  # integer if you prefer no decimals for total quantity
        "valorisation": "{:,.2f}",
        "poids": "{:,.2f}"
    }
    styled_inv = df_inv.style.format(fmt_dict)
    st.dataframe(styled_inv, use_container_width=True)
    st.write(f"### Actif sous gestion: {overall_val:,.2f}")

########################################
# 7) Market Page
########################################
def page_market():
    st.title("Marché Boursier")
    st.write("Les cours affichés peuvent avoir un décalage (~15 min).")

    from logic import compute_poids_masi
    from db_utils import fetch_stocks

    mm = compute_poids_masi()
    if not mm:
        st.warning("Aucun instrument trouvé / BD vide.")
        return

    stx = fetch_stocks()

    rows = []
    for val, info in mm.items():
        rows.append({
            "valeur": val,
            "Capitalisation": info["capitalisation"],
            "Poids Masi": info["poids_masi"]
        })
    df_mkt = pd.DataFrame(rows)
    df_mkt = pd.merge(df_mkt, stx, on="valeur", how="left")
    df_mkt.rename(columns={"cours":"Cours"}, inplace=True)
    df_mkt = df_mkt[["valeur","Cours","Capitalisation","Poids Masi"]]

    styled_mkt = df_mkt.style.format({
        "Cours":"{:,.2f}",
        "Capitalisation":"{:,.2f}",
        "Poids Masi":"{:,.2f}"
    })
    st.dataframe(styled_mkt, use_container_width=True)

########################################
# 8) Performance & Fees
########################################
def page_performance_fees():
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

    st.subheader("Périodes de Performance pour ce Client")
    df_periods = get_performance_periods_for_client(cid)

    # ---- Let the user add a new row
    with st.expander("Ajouter une nouvelle période"):
        with st.form("add_perf_period_form", clear_on_submit=True):
            start_date_input = st.date_input("Date de Début")
            start_value_port = st.number_input("Portefeuille Départ", min_value=0.0, step=0.01, value=0.0)
            start_value_masi = st.number_input("MASI Départ", min_value=0.0, step=0.01, value=0.0)
            s_sub = st.form_submit_button("Enregistrer")
            if s_sub:
                start_date_str = str(start_date_input)
                create_performance_period(cid, start_date_str, start_value_port, start_value_masi)

    # ---- Show a data_editor for existing periods
    if df_periods.empty:
        st.info("Aucune période n'existe pour ce client.")
        return
    # Convert start_date to real date for data_editor
    df_periods = df_periods.copy()
    if "start_date" in df_periods.columns:
        df_periods["start_date"] = pd.to_datetime(df_periods["start_date"], errors="coerce").dt.date

    # If you have an ID column as primary key for performance_periods, we keep it to locate the row
    # We'll do an editing UI:
    column_cfg = {
        "start_date": st.column_config.DateColumn("Date Début"),
        "start_value": st.column_config.NumberColumn("Portf Départ", format="%.2f"),
        "masi_start_value": st.column_config.NumberColumn("MASI Départ", format="%.2f"),
    }
    # If you have "created_at" or "id", we can choose to hide them or set them read_only
    if "id" in df_periods.columns:
        column_cfg["id"] = st.column_config.Column("id", disabled=True)

    # We do data_editor:
    updated_periods = st.data_editor(
        df_periods,
        use_container_width=True,
        column_config=column_cfg,
        key="perfPeriodsEditor"
    )

    # After data_editor, we want a "Save Changes" button:
    if st.button("Enregistrer modifications des périodes"):
        # Compare updated_periods vs df_periods => row by row updates
        update_performance_period_rows(df_periods, updated_periods)
        st.success("Modifications enregistrées avec succès!")
        st.experimental_rerun()

    # ---- Now let user pick a row to compute performance:
    st.subheader("Calculer la Performance sur une Période")
    if not updated_periods.empty:
        # Sort by date descending
        sorted_periods = updated_periods.sort_values("start_date", ascending=False)
        start_options = sorted_periods["start_date"].unique().tolist()
        pick = st.selectbox("Choisir la date de début", start_options, key="calc_perf_startdate")
        row_chosen = sorted_periods[sorted_periods["start_date"]==pick].iloc[0]
        port_start_val = float(row_chosen.get("start_value",0))
        masi_start_val = float(row_chosen.get("masi_start_value",0))

        # Current portfolio
        pdf = get_portfolio(client_name)
        if pdf.empty:
            st.warning("Pas de portefeuille pour ce client.")
        else:
            stx = db_utils.fetch_stocks()
            p_current = 0.0
            for _, rowp in pdf.iterrows():
                v_ = str(rowp["valeur"])
                q_ = float(rowp["quantité"])
                match = stx[stx["valeur"]==v_]
                px_ = float(match["cours"].values[0]) if not match.empty else 0.0
                p_current += (q_* px_)

            gains_port = p_current - port_start_val
            perf_port  = (gains_port/port_start_val)*100 if port_start_val>0 else 0.0

            masi_now = get_current_masi()
            gains_masi = masi_now - masi_start_val
            perf_masi  = (gains_masi/masi_start_val)*100 if masi_start_val>0 else 0.0

            surp_abs = gains_port - gains_masi
            surp_pct = 0.0
            if port_start_val>0:
                surp_pct = (surp_abs/port_start_val)*100

            # Bill or not
            cinfo_ = get_client_info(client_name)
            mgmt_r = float(cinfo_.get("management_fee_rate",0))/100.0
            if cinfo_.get("bill_surperformance", False):
                # surperf
                base_amt = max(0, surp_abs)
                fees_ = base_amt* mgmt_r
            else:
                # normal perf
                base_amt = max(0, gains_port)
                fees_ = base_amt* mgmt_r

            # Display it in a small 1-row table:
            df_res = pd.DataFrame([{
                "Portf. Départ": port_start_val,
                "Portf. Actuel": p_current,
                "Gains Portf": gains_port,
                "Perf Portf %": perf_port,
                "MASI Départ": masi_start_val,
                "MASI Actuel": masi_now,
                "Gains MASI": gains_masi,
                "Perf MASI %": perf_masi,
                "Surperf Abs.": surp_abs,
                "Surperf %": surp_pct,
                "Frais": fees_,
            }])
            # Format numeric columns
            numeric_cols = df_res.select_dtypes(include=["int","float","number"]).columns
            df_res_style = df_res.style.format("{:,.2f}", subset=numeric_cols)
            st.dataframe(df_res_style, use_container_width=True)

    # 5) Résumé global
    st.subheader("Résumé de Performance (tous les clients)")
    all_rows = get_latest_performance_period_for_all_clients()
    if all_rows.empty:
        st.info("Aucune donnée globale de performance.")
    else:
        # We'll do a table
        stx = db_utils.fetch_stocks()
        masi_cur = get_current_masi()
        summary_list = []
        all_clients = get_all_clients()
        for _, r1 in all_rows.iterrows():
            c_id = r1["client_id"]
            st_val = float(r1["start_value"] or 0)
            st_masi= float(r1["masi_start_value"] or 0)
            ddate  = str(r1["start_date"])

            # find name
            nm = None
            for ccc in all_clients:
                if get_client_id(ccc)==c_id:
                    nm= ccc
                    break
            if not nm:
                continue

            pdf2 = get_portfolio(nm)
            cur_val2=0.0
            if not pdf2.empty:
                for _, prow2 in pdf2.iterrows():
                    v2 = str(prow2["valeur"])
                    q2 = float(prow2["quantité"])
                    match2= stx[stx["valeur"]== v2]
                    px2= float(match2["cours"].values[0]) if not match2.empty else 0.0
                    cur_val2+= (q2* px2)

            gains2 = cur_val2 - st_val
            perf_p2=0.0
            if st_val>0:
                perf_p2= (gains2/ st_val)*100

            gm = masi_cur- st_masi
            pm=0.0
            if st_masi>0:
                pm= (gm/ st_masi)*100

            sur_abs= gains2- gm
            sur_pct= 0.0
            if st_val>0:
                sur_pct= (sur_abs/ st_val)*100

            cinfo2= get_client_info(nm)
            mgmtr= float(cinfo2.get("management_fee_rate",0))/100.0
            if cinfo2.get("bill_surperformance",False):
                base_ = max(0, sur_abs)
                fee_  = base_* mgmtr
            else:
                base_ = max(0, gains2)
                fee_  = base_* mgmtr

            summary_list.append({
                "Client": nm,
                "Date Début": ddate,
                "Portf Départ": st_val,
                "Portf Actuel": cur_val2,
                "Perf Portf %": perf_p2,
                "MASI Départ": st_masi,
                "MASI Actuel": masi_cur,
                "Perf MASI %": pm,
                "Surperf Abs.": sur_abs,
                "Surperf %": sur_pct,
                "Frais": fee_,
            })

        if not summary_list:
            st.info("Aucune info disponible.")
        else:
            df_sum= pd.DataFrame(summary_list)
            num_cols= df_sum.select_dtypes(include=["int","float","number"]).columns
            df_sum_style= df_sum.style.format("{:,.2f}", subset=num_cols)
            st.dataframe(df_sum_style, use_container_width=True)

            # Totals
            tot_start = df_sum["Portf Départ"].sum()
            tot_cur   = df_sum["Portf Actuel"].sum()
            tot_fees  = df_sum["Frais"].sum()
            df_tot = pd.DataFrame([{
                "Total Portf Départ": tot_start,
                "Total Portf Actuel": tot_cur,
                "Total Frais": tot_fees
            }])
            df_tot_style= df_tot.style.format("{:,.2f}")
            st.write("#### Totaux Globaux")
            st.dataframe(df_tot_style, use_container_width=True)
