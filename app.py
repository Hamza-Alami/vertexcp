import streamlit as st
import requests
import pandas as pd
import numpy as np

# Load stock prices from API
@st.cache_data
def get_stock_data():
    url = "https://backend.idbourse.com/api_2/get_all_data"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
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

strategy_name = st.sidebar.text_input("Strategy Name")
selected_stocks = st.sidebar.multiselect("Select Stocks", stocks['name'].tolist())
weights = {stock: st.sidebar.slider(f"Weight for {stock} (%)", 0.0, 100.0, 0.0, 0.5) for stock in selected_stocks}
cash_weight = 100 - sum(weights.values())

if st.sidebar.button("Save Strategy"):
    weights['CASH'] = cash_weight
    st.session_state['strategies'][strategy_name] = weights
    st.success(f"Strategy '{strategy_name}' saved")

for name in list(st.session_state['strategies'].keys()):
    if st.sidebar.button(f"Delete Strategy {name}"):
        del st.session_state['strategies'][name]
        st.success(f"Strategy '{name}' deleted")

# Clients Management
st.sidebar.title("👤 Clients")
if 'clients' not in st.session_state:
    st.session_state['clients'] = {}

client_name = st.sidebar.text_input("Client Name")
strategy_for_client = st.sidebar.selectbox("Select Strategy", list(st.session_state['strategies'].keys()) + ["Custom"])

if st.sidebar.button("Add Client"):
    client_portfolio = pd.DataFrame(columns=["Valeur", "Quantité", "Cours", "Valorisation", "Target Weight", "Target Quantity", "Difference"])
    if strategy_for_client != "Custom":
        strategy_weights = st.session_state['strategies'][strategy_for_client]
        for stock, weight in strategy_weights.items():
            client_portfolio = pd.concat([client_portfolio, pd.DataFrame({'Valeur': [stock], 'Target Weight': [weight]})], ignore_index=True)
    st.session_state['clients'][client_name] = {'portfolio': client_portfolio, 'strategy': strategy_for_client}

for client, data in st.session_state['clients'].items():
    st.subheader(f"Portfolio for {client} (Strategy: {data['strategy']})")
    portfolio = data['portfolio']
    portfolio['Cours'] = portfolio['Valeur'].map(stocks.set_index('name')['dernier_cours'])
    portfolio['Valorisation'] = portfolio['Quantité'].fillna(0) * portfolio['Cours']
    valorisation_totale = portfolio['Valorisation'].sum()
    portfolio['Target Quantity'] = (portfolio['Target Weight'] * valorisation_totale / portfolio['Cours']).fillna(0)
    portfolio['Difference'] = (portfolio['Quantité'].fillna(0) - portfolio['Target Quantity']).apply(lambda x: int(np.floor(x)) if x != 'CASH' else x)
    st.write(f"Total Portfolio Value: {valorisation_totale:.2f}")
    st.data_editor(portfolio, num_rows="dynamic", height=400)
    st.session_state['clients'][client]['portfolio'] = portfolio
    if st.button(f"Delete {client}"):
        del st.session_state['clients'][client]
        st.success(f"Client '{client}' deleted")

# Inventaire Section
st.title("📊 Inventaire")
inventaire = pd.DataFrame(columns=["Valeur", "Quantité Totale"])
for data in st.session_state['clients'].values():
    grouped = data['portfolio'].groupby('Valeur')['Quantité'].sum().reset_index()
    inventaire = pd.concat([inventaire, grouped])
inventaire = inventaire.groupby('Valeur')['Quantité'].sum().reset_index()
st.dataframe(inventaire)
