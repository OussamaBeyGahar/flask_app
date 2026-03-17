from app import app, db, User
from werkzeug.security import generate_password_hash

def verify_search():
    client = app.test_client()
    
    with app.app_context():
        db.create_all()
        
        # Setup Admin
        admin = User.query.filter_by(username='admin_search').first()
        if not admin:
            admin = User(username='admin_search', email='admin@test.com', first_name='Admin', last_name='User', country='Test', password=generate_password_hash('pass'), is_admin=True, is_approved=True)
            db.session.add(admin)

        # Setup Target User
        target = User.query.filter_by(username='target_user').first()
        if not target:
            target = User(username='target_user', email='target@test.com', first_name='Target', last_name='User', country='Test', password=generate_password_hash('pass'), is_approved=True)
            db.session.add(target)

        # Setup Other User
        other = User.query.filter_by(username='other_user').first()
        if not other:
            other = User(username='other_user', email='other@test.com', first_name='Other', last_name='User', country='Test', password=generate_password_hash('pass'), is_approved=True)
            db.session.add(other)
            
        db.session.commit()

    # Login Admin
    client.post('/login', data={'username': 'admin_search', 'password': 'pass'}, follow_redirects=True)

    # Test Search
    print("Searching for 'target_user'...")
    resp = client.get('/admin/access_control?q=target_user', follow_redirects=True)
    
    if b'target_user' in resp.data and b'other_user' not in resp.data:
        print("[PASS] Search filtered correctly.")
    else:
        print("[FAIL] Search filtering failed.")
        if b'target_user' not in resp.data: print(" - Target not found.")
        if b'other_user' in resp.data: print(" - Other user NOT filtered out.")

    # Test Clear (Empty Search)
    print("Clearing search...")
    resp = client.get('/admin/access_control', follow_redirects=True)
    if b'target_user' in resp.data and b'other_user' in resp.data:
        print("[PASS] Clear search shows all users.")
    else:
        print("[FAIL] Clear search failed (users missing).")

if __name__ == "__main__":
    verify_search()
