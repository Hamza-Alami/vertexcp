import streamlit as st
import pandas as pd
from supabase import create_client

# Debug Secrets
st.write(f"👀 Loaded Secrets Keys: {list(st.secrets.keys())}")

# Retrieve Secrets Safely
supabase_secrets = st.secrets.get("supabase")
if not supabase_secrets:
    st.error("🚨 Missing `[supabase]` section in secrets. Check Streamlit Cloud > Settings > Secrets.")
    st.stop()

supabase_url = supabase_secrets.get("url")
supabase_key = supabase_secrets.get("key")

if not supabase_url or not supabase_key:
    st.error("❌ Missing Supabase URL or Key. Ensure both are in Streamlit Cloud Secrets.")
    st.stop()

# Connect to Supabase
client = create_client(supabase_url, supabase_key)

# Client and Portfolio Functions
def create_client(name):
    client.table('clients').insert({"name": name}).execute()
    client.table('portfolios').insert({"client_name": name, "stocks": []}).execute()

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
        st.success(f"✅ Client '{client_name}' created!")
        st.experimental_rerun()

all_clients = [c['name'] for c in client.table('clients').select('name').execute().data]
selected_clients = st.multiselect("Select Clients", all_clients)
if st.button("Show Portfolios"):
    display_portfolios(selected_clients)
