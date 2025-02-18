import streamlit as st
import pandas as pd
import requests
from supabase import create_client

# ======================== Connect to Supabase ========================
supabase_url = st.secrets["supabase"]["url"]
supabase_key = st.secrets["supabase"]["key"]
client = create_client(supabase_url, supabase_key)

# ======================== Fetch Stock Prices from ID Bourse ========================
@st.cache_data
def get_stock_data():
    url = "https://backend.idbourse.com/api_2/get_all_data"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()  # Likely returns a list
        if isinstance(data, list) and len(data) > 0:
            first_item = data[0]
            if 'stocks' in first_item:
                stocks = pd.DataFrame(first_item['stocks'])
                stocks = stocks[['name', 'dernier_cours']].rename(columns={'dernier_cours': 'price'})
                # Add CASH with fixed price 1
                stocks = pd.concat([stocks, pd.DataFrame([{'name': 'CASH', 'price': 1}])], ignore_index=True)
                return stocks
            else:
                st.error("API response does not contain 'stocks'. Check the API structure.")
        else:
            st.error("API response is empty or not in expected format.")
    else:
        st.error(f"Failed to load stock data. Status code: {response.status_code}")
    return pd.DataFrame()

stocks = get_stock_data()

# ======================== Sidebar Navigation ========================
page = st.sidebar.radio("Navigation", ["Cours", "Clients"])

# ======================== Cours Page (Stock Prices) ========================
if page == "Cours":
    st.title("📈 Cours (Stock Prices)")
    st.dataframe(stocks)

# ======================== Clients Page (Client Portfolio Manager) ========================
else:
    st.title("👥 Client Portfolio Manager")

    # 1️⃣ Add New Client
    with st.form("add_client"):
        client_name = st.text_input("Client Name")
        if st.form_submit_button("Add Client"):
            client.table('clients').insert({"name": client_name}).execute()
            client.table('portfolios').insert({
                "client_name": client_name,
                "name": "CASH",
                "quantity": 0,
                "value": 0,
                "cash": 0
            }).execute()
            st.success(f"Client '{client_name}' created with initial CASH = 0!")
            st.experimental_rerun()

    # 2️⃣ List All Clients
    all_clients = [c['name'] for c in client.table('clients').select('name').execute().data]
    st.subheader("All Clients")
    st.write(all_clients)

    # 3️⃣ Delete Client
    with st.form("delete_client"):
        client_to_delete = st.selectbox("Select Client to Delete", all_clients)
        if st.form_submit_button("Delete Client"):
            client.table('clients').delete().eq('name', client_to_delete).execute()
            client.table('portfolios').delete().eq('client_name', client_to_delete).execute()
            st.success(f"Client '{client_to_delete}' deleted.")
            st.experimental_rerun()

    # 4️⃣ Manage Portfolios
    selected_client = st.selectbox("Select Client to Manage Portfolio", all_clients)
    portfolio_data = pd.DataFrame(
        client.table('portfolios').select("*").eq('client_name', selected_client).execute().data
    )

    if not portfolio_data.empty:
        st.subheader(f"Portfolio for {selected_client}")

        # 🟡 Fix Missing Columns to Prevent KeyError
        required_columns = ['name', 'quantity', 'value', 'cash']
        for col in required_columns:
            if col not in portfolio_data.columns:
                portfolio_data[col] = 0  # Add missing columns with default value

        # 🟢 Show and Edit Portfolio
        edited_portfolio = st.data_editor(
            portfolio_data[required_columns],
            key="portfolio_editor",
            num_rows="dynamic"
        )

        # 💾 Save Portfolio Changes
        if st.button("Save Portfolio"):
            for _, row in edited_portfolio.iterrows():
                client.table('portfolios').update({
                    "quantity": row['quantity'],
                    "value": row['quantity'] * stocks.loc[stocks['name'] == row['name'], 'price'].values[0] if row['name'] in stocks['name'].values else 0
                }).eq('client_name', selected_client).eq('name', row['name']).execute()
            st.success("Portfolio updated successfully.")
            st.experimental_rerun()

        # 💰 Total Valorisation Calculation
        total_valorisation = edited_portfolio['value'].sum() + edited_portfolio['cash'].sum()
        st.subheader(f"💰 Total Portfolio Valorisation: {total_valorisation:.2f} MAD")

        # ➕ Add Stocks from Cours to Portfolio
        with st.form("add_stock"):
            stock_to_add = st.selectbox("Select Stock to Add", stocks['name'].tolist())
            quantity_to_add = st.number_input("Quantity", min_value=1, value=1)
            if st.form_submit_button("Add Stock"):
                stock_price = stocks.loc[stocks['name'] == stock_to_add, 'price'].values[0]
                client.table('portfolios').insert({
                    "client_name": selected_client,
                    "name": stock_to_add,
                    "quantity": quantity_to_add,
                    "value": quantity_to_add * stock_price,
                    "cash": 0
                }).execute()
                st.success(f"Added {quantity_to_add} of {stock_to_add} to {selected_client}'s portfolio.")
                st.experimental_rerun()

    else:
        st.write(f"No portfolio found for {selected_client}. Try adding stocks or cash.")
