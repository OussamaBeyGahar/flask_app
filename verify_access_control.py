from app import app, db, User, Page
from werkzeug.security import generate_password_hash

def verify_access_control():
    client = app.test_client()
    
    with app.app_context():
        # Ensure pages are initialized
        db.create_all()
        
        # Create/Get Admin
        admin = User.query.filter_by(username='admin_ac').first()
        if not admin:
            admin = User(username='admin_ac', email='admin_ac@test.com', 
                         first_name='Admin', last_name='User', country='Test',
                         password=generate_password_hash('adminpass'),
                         is_admin=True, is_approved=True)
            db.session.add(admin)
            
        # Create/Get User
        user = User.query.filter_by(username='user_ac').first()
        if not user:
            user = User(username='user_ac', email='user_ac@test.com',
                        first_name='Regular', last_name='User', country='Test',
                        password=generate_password_hash('userpass'),
                        is_admin=False, is_approved=True)
            db.session.add(user)
        
        # Grant 'eco_design_dma' payload to user
        page = Page.query.filter_by(endpoint='eco_design_dma').first()
        if page:
            user.pages = [page]
        else:
            print("[ERROR] Page eco_design_dma not found in DB!")
            return

        db.session.commit()
        print("Test data set up.")

    # 1. Login as User
    print("Logging in as user_ac...")
    client.post('/login', data={'username': 'user_ac', 'password': 'userpass'}, follow_redirects=True)
    
    # 2. Access Allowed Page
    print("Checking allowed page (/eco_design_dma)...")
    resp = client.get('/eco_design_dma', follow_redirects=True)
    if resp.status_code == 200 and b'ECO Desgin Report DMA' in resp.data:
        print("[PASS] Access granted to allowed page.")
    else:
        print(f"[FAIL] Access denied to allowed page. Status: {resp.status_code}")
        # print(f"Response data: {resp.data[:200]}")
        
    # 3. Access Denied Page
    print("Checking denied page (/exported3d_dma)...")
    resp = client.get('/exported3d_dma', follow_redirects=True)
    # Should redirect to dashboard and show flash message
    if b'You do not have access to this page' in resp.data:
        print("[PASS] Access denied to unauthorized page.")
    else:
        print(f"[FAIL] Access NOT checked/denied for unauthorized page. Content: {resp.data[:100]}...")

if __name__ == "__main__":
    verify_access_control()
