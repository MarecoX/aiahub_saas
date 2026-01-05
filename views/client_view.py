# Redirect to new architecture
from views.client_dashboard.main import render_client_dashboard


def render_client_view(user_data):
    """
    Deprecated entry point. Redirects to new modular dashboard.
    """
    render_client_dashboard(user_data)
