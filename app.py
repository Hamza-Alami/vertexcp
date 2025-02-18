import streamlit as st
import pandas as pd
from supabase import create_client
import os

# Connect to Supabase
supabase_url = st.secrets["supabase"]["url"]
supabase_key = st.secrets["supabase"]["key"]
client = create_client(supabase_url, supabase_key)

# Create a new client and portfolio
def create_client(name):
    client.table('clients').insert({"name": name}).execute()
    client.table('portfolios').insert({"client_name": name, "stocks": []}).execute()

# Display client portfolios
def display_portfolios(selected_clients):
    query = client.table('portfolios').select("*").execute()
    df = pd.DataFrame(query.data)
    filtered = df[df['client_name'].isin(selected_clients)]
    st.dataframe(filtered)

# Streamlit UI
st.title("📊 Client Portfolio Manager")

with st.form("add_client"):
    client_name = st.text_input("Client Name")
    if st.form_submit_button("Add Client"):
        create_client(client_name)
        st.success(f"Client '{client_name}' created!")
        st.experimental_rerun()

# View portfolios
all_clients = [c['name'] for c in client.table('clients').select('name').execute().data]
selected_clients = st.multiselect("Select Clients", all_clients)
if st.button("Show Portfolios"):
    display_portfolios(selected_clients)
