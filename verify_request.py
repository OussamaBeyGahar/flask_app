from app import app, db, User

def verify_request():
    client = app.test_client()
    
    # Login as admin
    print("Logging in as admin...")
    resp = client.post('/login', data={'username': 'admin', 'password': 'adminpass'}, follow_redirects=True)
    if b'Logged in successfully' not in resp.data:
        print("[FAIL] Could not login as admin.")
        return

    routes = [
        '/request_queued',
        '/request_completed',
        '/request_all_completed',
        '/request_failed',
        '/request_all_failed'
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
        verify_request()
