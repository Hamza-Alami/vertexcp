import streamlit as st
import requests
import pandas as pd
import json

# Load stock prices from API
@st.cache_data
def get_stock_data():
    url = "https://backend.idbourse.com/api_2/get_all_data"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if isinstance(data, (list, dict)):
            stocks = pd.DataFrame(data if isinstance(data, list) else data.get('stocks', []))
            stocks = stocks[['name', 'dernier_cours']]
            stocks = pd.concat([stocks, pd.DataFrame([{'name': 'CASH', 'dernier_cours': 1}])], ignore_index=True)
            return stocks
    st.error("Failed to load stock data")
    return pd.DataFrame()

stocks = get_stock_data()
st.title("📈 Stock Prices")
st.dataframe(stocks)

# Strategies Management
st.sidebar.title("🎯 Manage Strategies")
if 'strategies' not in st.session_state:
    st.session_state['strategies'] = {}

# Add, edit, delete strategies
strategy_name = st.sidebar.text_input("Strategy Name")
selected_stocks = st.sidebar.multiselect("Select Stocks", stocks['name'].tolist())
weights = {stock: st.sidebar.slider(f"Weight for {stock} (%)", 0.0, 100.0, 0.0, 0.5) for stock in selected_stocks}
cash_weight = 100 - sum(weights.values())

if st.sidebar.button("Save Strategy"):
    if strategy_name and cash_weight >= 0:
        weights['CASH'] = cash_weight
        st.session_state['strategies'][strategy_name] = weights
        st.success(f"Strategy '{strategy_name}' saved")
    else:
        st.error("Invalid strategy configuration")

for name in list(st.session_state['strategies'].keys()):
    if st.sidebar.button(f"Delete Strategy {name}"):
        del st.session_state['strategies'][name]
        st.success(f"Strategy '{name}' deleted")

# Clients Management with Add/Edit/Delete functionality
st.sidebar.title("👤 Clients")
if 'clients' not in st.session_state:
    st.session_state['clients'] = {}

client_name = st.sidebar.text_input("Client Name")
strategy_for_client = st.sidebar.selectbox("Select Strategy", list(st.session_state['strategies'].keys()))

if st.sidebar.button("Add/Update Client"):
    client_portfolio = pd.DataFrame(columns=["Valeur", "Quantité", "Cours", "Target Weight", "Target Quantity", "Difference"])
    strategy_weights = st.session_state['strategies'][strategy_for_client]
    for stock, weight in strategy_weights.items():
        client_portfolio = pd.concat([client_portfolio, pd.DataFrame({'Valeur': [stock], 'Target Weight': [weight]})], ignore_index=True)
    st.session_state['clients'][client_name] = {'portfolio': client_portfolio, 'strategy': strategy_for_client}
    st.success(f"Client '{client_name}' added/updated")

for client, data in st.session_state['clients'].items():
    st.subheader(f"Portfolio for {client} (Strategy: {data['strategy']})")
    data['portfolio']['Cours'] = data['portfolio']['Valeur'].map(stocks.set_index('name')['dernier_cours'])
    data['portfolio']['Target Quantity'] = (data['portfolio']['Target Weight'] * 1000) / data['portfolio']['Cours']
    data['portfolio']['Difference'] = data['portfolio']['Quantité'].fillna(0) - data['portfolio']['Target Quantity']
    edited_portfolio = st.data_editor(data['portfolio'], num_rows="dynamic")
    st.session_state['clients'][client]['portfolio'] = edited_portfolio
    if st.button(f"Delete {client}"):
        del st.session_state['clients'][client]
        st.success(f"Client '{client}' deleted")

# Inventaire Section
st.title("📊 Inventaire")
inventaire = pd.DataFrame(columns=["Valeur", "Quantité Totale"])
for data in st.session_state['clients'].values():
    if not data['portfolio'].empty:
        grouped = data['portfolio'].groupby('Valeur')['Quantité'].sum().reset_index()
        inventaire = pd.concat([inventaire, grouped])
inventaire = inventaire.groupby('Valeur')['Quantité'].sum().reset_index()
st.dataframe(inventaire)
