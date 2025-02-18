
import streamlit as st
import pandas as pd
from supabase import create_client

# Verify Secrets Loaded
st.write(f"Detected Secrets Keys: {list(st.secrets.keys())}")

# Connect to Supabase
supabase_url = st.secrets.get("supabase", {}).get("url")
supabase_key = st.secrets.get("supabase", {}).get("key")

if not supabase_url or not supabase_key:
    st.error("❌ Missing Supabase URL or Key. Check Streamlit Cloud Secrets.")
    st.stop()

client = create_client(supabase_url, supabase_key)

# Create Client and Portfolio
def create_client(name):
    client.table('clients').insert({"name": name}).execute()
    client.table('portfolios').insert({"client_name": name, "stocks": []}).execute()

# Display Portfolios
def display_portfolios(selected_clients):
    data = client.table('portfolios').select("*").execute().data
    df = pd.DataFrame(data)
    st.dataframe(df[df['client_name'].isin(selected_clients)])

# Streamlit UI
st.title("📊 Client Portfolio Manager")

with st.form("add_client"):
    client_name = st.text_input("Client Name")
    if st.form_submit_button("Add Client"):
        create_client(client_name)
        st.success(f"Client '{client_name}' created!")
        st.experimental_rerun()

# View Portfolios
all_clients = [c['name'] for c in client.table('clients').select('name').execute().data]
selected_clients = st.multiselect("Select Clients", all_clients)
if st.button("Show Portfolios"):
    display_portfolios(selected_clients)
