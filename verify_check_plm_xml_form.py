from app import app, db, User
from werkzeug.security import generate_password_hash

def verify_check_plm_xml_form():
    client = app.test_client()
    
    with app.app_context():
        db.create_all()
        # Ensure Admin exists
        admin = User.query.filter_by(username='admin_plm').first()
        if not admin:
            admin = User(username='admin_plm', email='admin_plm@test.com', first_name='Admin', last_name='PLM', country='Test', password=generate_password_hash('pass'), is_admin=True, is_approved=True)
            db.session.add(admin)
            db.session.commit()

    # Login
    client.post('/login', data={'username': 'admin_plm', 'password': 'pass'}, follow_redirects=True)

    # 1. Check Page Content
    print("Checking page content...")
    resp = client.get('/check_plm_xml', follow_redirects=True)
    
    if b'Import DMA to FastTrack' in resp.data:
        print("[PASS] Title updated.")
    else:
        print("[FAIL] Title NOT updated.")

    form_fields = [b'dma_reference', b'skip_teamcenter', b'as_prototype', b'check_level']
    if all(field in resp.data for field in form_fields):
        print("[PASS] All form fields present.")
    else:
        print("[FAIL] Missing form fields.")

    # 2. Test Submission
    print("Testing form submission...")
    data = {
        'dma_reference': 'REF-456',
        'skip_teamcenter': 'on',
        'as_prototype': 'on',
        'check_level': '3'
    }
    resp = client.post('/check_plm_xml', data=data, follow_redirects=True)
    
    # Check flash message logic
    # Expected: Ref=REF-456, SkipTC=True, Proto=True, Level=3
    if b'Ref=REF-456' in resp.data and b'Level=3' in resp.data:
        print("[PASS] Form submitted and processed successfully.")
    else:
        print("[FAIL] Form submission failed or flash message missing.")
        # print(resp.data)

if __name__ == "__main__":
    verify_check_plm_xml_form()
