import os
from app import app, db, User
from werkzeug.security import generate_password_hash

# Path to DB
db_path = os.path.join('instance', 'database.db')
if os.path.exists(db_path):
    os.remove(db_path)
    print(f"Database removed at {db_path}.")

with app.app_context():
    db.create_all()
    print("Database created.")

    # Create Admin
    admin = User(
        username='admin',
        email='admin@example.com',
        first_name='Admin',
        last_name='User',
        country='Earth',
        password=generate_password_hash('adminpass'),
        is_admin=True,
        is_approved=True
    )
    db.session.add(admin)
    db.session.commit()
    print("Admin user created (ID: 1).")

    # Create Normal User
    user = User(
        username='user',
        email='user@example.com',
        first_name='Normal',
        last_name='User',
        country='Mars',
        password=generate_password_hash('userpass'),
        is_approved=False
    )
    db.session.add(user)
    db.session.commit()
    print("Normal user created (pending) (ID: 2).")

    # Verify Logic
    client = app.test_client()
    
    # 1. Login as pending user
    print("\n--- Testing Pending User Login ---")
    resp = client.post('/login', data={'username': 'user', 'password': 'userpass'}, follow_redirects=True)
    if b'Account pending approval' in resp.data:
        print("[PASS] Pending user cannot login.")
    else:
        print("[FAIL] Pending user login check failed.")
        # print(resp.data)

    # 2. Login as admin
    print("\n--- Testing Admin Login & Dashboard ---")
    with client:
        resp = client.post('/login', data={'username': 'admin', 'password': 'adminpass'}, follow_redirects=True)
        if b'Logged in successfully' in resp.data:
            print("[PASS] Admin login success.")
        else:
            print("[FAIL] Admin login failed.")
        
        # Access Admin Page
        resp = client.get('/admin')
        if b'User Management' in resp.data and b'user' in resp.data:
            print("[PASS] Admin dashboard accessible and shows pending user.")
        else:
             print("[FAIL] Admin dashboard check failed.")

        # Approve User
        user_id = 2 # Known ID
        print(f"\n--- Approving User ID {user_id} ---")
        resp = client.get(f'/admin/approve/{user_id}', follow_redirects=True)
        if b'User user approved' in resp.data:
            print("[PASS] User approval action success.")
        else:
            print("[FAIL] User approval action failed.")
            print(resp.data.decode())

    # 3. Login as approved user
    print("\n--- Testing Approved User Login ---")
    client = app.test_client() # New client, no cookies
    resp = client.post('/login', data={'username': 'user', 'password': 'userpass'}, follow_redirects=True)
    if b'Logged in successfully' in resp.data:
         print("[PASS] Approved user login success.")
    else:
         print("[FAIL] Approved user login failed.")
