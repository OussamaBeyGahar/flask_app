from app import app, db, User

def verify_routes():
    client = app.test_client()
    
    # Login as admin (created in previous step)
    print("Logging in as admin...")
    resp = client.post('/login', data={'username': 'admin', 'password': 'adminpass'}, follow_redirects=True)
    if b'Logged in successfully' not in resp.data:
        print("[FAIL] Could not login as admin. Ensure admin user exists (run verify_admin.py first if needed).")
        return

    routes = [
        '/check_plm_xml',
        '/check_bat_contract',
        '/dma_to_team_center',
        '/plm_report'
    ]

    for route in routes:
        print(f"Checking {route}...")
        resp = client.get(route, follow_redirects=True)
        if resp.status_code == 200:
            if b'placeholder page' in resp.data:
                print(f"[PASS] {route} accessible.")
            else:
                print(f"[WARN] {route} accessible but content check failed.")
        else:
            print(f"[FAIL] {route} returned {resp.status_code}")

if __name__ == "__main__":
    with app.app_context():
        verify_routes()
