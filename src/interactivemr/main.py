import os
import click
import gitlab
import webbrowser
import secrets
import requests
from dotenv import load_dotenv, set_key
from urllib.parse import urlparse, parse_qs, urlencode
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- OAuth2 Configuration ---
REDIRECT_URI = "http://localhost:7890"
OAUTH_SCOPE = "api"

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body><h1>Authentication successful!</h1><p>You can close this window.</p></body></html>")
        
        query = urlparse(self.path).query
        params = parse_qs(query)
        self.server.auth_code = params.get('code', [None])[0]
        self.server.state = params.get('state', [None])[0]

def get_gitlab_instance(gitlab_url):
    """Handles OAuth2 flow and returns an authenticated gitlab.Gitlab instance."""
    load_dotenv()
    app_id = os.getenv("GITLAB_APP_ID")
    app_secret = os.getenv("GITLAB_APP_SECRET")
    access_token = os.getenv("GITLAB_ACCESS_TOKEN")

    if not app_id or not app_secret:
        raise click.UsageError("GITLAB_APP_ID and GITLAB_APP_SECRET must be set in your .env file.")

    if access_token:
        gl = gitlab.Gitlab(gitlab_url, oauth_token=access_token)
        try:
            gl.auth()
            return gl
        except gitlab.exceptions.GitlabAuthenticationError:
            pass # Token is invalid or expired, proceed to re-authenticate

    # --- New OAuth Flow ---
    state = secrets.token_urlsafe(16)
    auth_params = {
        "client_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "state": state,
        "scope": OAUTH_SCOPE,
    }
    auth_url = f"{gitlab_url}/oauth/authorize?{urlencode(auth_params)}"
    
    print("Your browser will now open for GitLab authentication.")
    webbrowser.open(auth_url)

    with HTTPServer(('localhost', 7890), OAuthCallbackHandler) as httpd:
        print("Waiting for authentication callback on http://localhost:7890...")
        httpd.handle_request()
        auth_code = httpd.auth_code
        received_state = httpd.state

    if received_state != state:
        raise click.ClickException("State mismatch. Possible CSRF attack.")
    if not auth_code:
        raise click.ClickException("Could not get authorization code from GitLab.")

    # --- Manually exchange code for token ---
    token_params = {
        'client_id': app_id,
        'client_secret': app_secret,
        'code': auth_code,
        'grant_type': 'authorization_code',
        'redirect_uri': REDIRECT_URI,
    }
    token_url = f"{gitlab_url}/oauth/token"
    response = requests.post(token_url, data=token_params)
    response.raise_for_status() # Raise an exception for bad status codes
    
    token_data = response.json()
    access_token = token_data['access_token']
    
    # Save the new token to the .env file
    set_key(".env", "GITLAB_ACCESS_TOKEN", access_token)
    print("Successfully authenticated and saved new token.")
    
    # Return a new, authenticated instance
    return gitlab.Gitlab(gitlab_url, oauth_token=access_token)


from .tui.app import InteractiveMRApp

@click.command()
@click.option('--url', required=True, help='The full repository URL (e.g., https://gitlab.com/user/repo).')
@click.option('--mr', required=True, type=int, help='The merge request number.')
def main(url, mr):
    """
    An interactive MergeRequest code review tool.
    """
    try:
        parsed_url = urlparse(url)
        gitlab_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        project_path = parsed_url.path.strip('/')

        gl = get_gitlab_instance(gitlab_url)
        
        project = gl.projects.get(project_path)
        merge_request = project.mergerequests.get(mr)
        changes = merge_request.changes()

        app = InteractiveMRApp(merge_request=merge_request, diffs=changes['changes'])
        app.run()

    except gitlab.exceptions.GitlabError as e:
        print(f"Error communicating with GitLab: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Error during OAuth token exchange: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == '__main__':
    main()
