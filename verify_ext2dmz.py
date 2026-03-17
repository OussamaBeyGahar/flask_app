from app import app, db, User

def verify_ext2dmz():
    client = app.test_client()
    
    # Login as admin
    print("Logging in as admin...")
    resp = client.post('/login', data={'username': 'admin', 'password': 'adminpass'}, follow_redirects=True)
    if b'Logged in successfully' not in resp.data:
        print("[FAIL] Could not login as admin.")
        return

    routes = [
        '/ext2dmz_neodma',
        '/ext2dmz_elsa2dma',
        '/ext2dmz_excel2dma',
        '/ext2dmz_elsa2bthtsp'
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
        verify_ext2dmz()
