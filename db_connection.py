# db_connection.py
import streamlit as st


def _create_supabase_client():
    """
    Create a Supabase client.

    We import `supabase` lazily because in some deployments the dependency
    chain (anyio/httpcore/httpx) can fail at import-time. Lazy loading keeps
    the Streamlit app from crashing before the first DB access.
    """
    from supabase import create_client

    supabase_url = st.secrets["supabase"]["url"]
    supabase_key = st.secrets["supabase"]["key"]
    return create_client(supabase_url, supabase_key)


@st.cache_resource
def get_supabase_client():
    """
    Creates and returns a Supabase client object (cached as a resource).
    """
    try:
        return _create_supabase_client()
    except Exception as e:
        st.error(
            "Supabase initialization failed. "
            "Check Supabase secrets and dependency versions (anyio/httpx). "
            f"Details: {e}"
        )
        raise
