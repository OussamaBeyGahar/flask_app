from app import app, db, User
from werkzeug.security import generate_password_hash

def verify_check_bat_form():
    client = app.test_client()
    
    with app.app_context():
        db.create_all()
        # Ensure Admin exists
        admin = User.query.filter_by(username='admin_bat').first()
        if not admin:
            admin = User(username='admin_bat', email='admin_bat@test.com', first_name='Admin', last_name='BAT', country='Test', password=generate_password_hash('pass'), is_admin=True, is_approved=True)
            db.session.add(admin)
            db.session.commit()

    # Login
    client.post('/login', data={'username': 'admin_bat', 'password': 'pass'}, follow_redirects=True)

    # 1. Check Page Content
    print("Checking page content...")
    resp = client.get('/check_bat_contract', follow_redirects=True)
    
    if b'Check BAT contract' in resp.data:
        print("[PASS] Title updated.")
    else:
        print("[FAIL] Title NOT updated.")

    if b'dtr_list' in resp.data and b'Please enter DTR list to check' in resp.data:
        print("[PASS] Form field present.")
    else:
        print("[FAIL] Missing form field.")

    # 2. Test Submission
    print("Testing form submission...")
    data = {
        'dtr_list': 'DTR-001\nDTR-002\nDTR-003'
    }
    resp = client.post('/check_bat_contract', data=data, follow_redirects=True)
    
    # Check flash message logic
    if b'Form submitted: DTR List=DTR-001' in resp.data:
        print("[PASS] Form submitted and processed successfully.")
    else:
        print("[FAIL] Form submission failed or flash message missing.")
        # print(resp.data)

if __name__ == "__main__":
    verify_check_bat_form()
