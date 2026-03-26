from app import app, db, User
from werkzeug.security import generate_password_hash

def verify_dma_form():
    client = app.test_client()
    
    with app.app_context():
        db.create_all()
        # Ensure Admin exists
        admin = User.query.filter_by(username='admin_dma').first()
        if not admin:
            admin = User(username='admin_dma', email='admin_dma@test.com', first_name='Admin', last_name='DMA', site_source='BLO', site_destination='BLO', password=generate_password_hash('pass'), is_admin=True, is_approved=True)
            db.session.add(admin)
            db.session.commit()

    # Login
    client.post('/login', data={'username': 'admin_dma', 'password': 'pass'}, follow_redirects=True)

    # 1. Check Page Content
    print("Checking page content...")
    resp = client.get('/dma_to_team_center', follow_redirects=True)
    
    if b'Import DMA to FastTrack' in resp.data:
        print("[PASS] Title updated.")
    else:
        print("[FAIL] Title NOT updated.")

    form_fields = [b'dma_reference', b'skip_teamcenter', b'as_prototype', b'doc_sep', b'doc_sep_no_relation']
    if all(field in resp.data for field in form_fields):
        print("[PASS] All form fields present.")
    else:
        print("[FAIL] Missing form fields.")

    # 2. Test Submission
    print("Testing form submission...")
    data = {
        'dma_reference': 'REF-123',
        'skip_teamcenter': 'on',
        'as_prototype': 'on'
    }
    resp = client.post('/dma_to_team_center', data=data, follow_redirects=True)
    
    # Check flash message logic
    # Expected: Ref=REF-123, SkipTC=True, Proto=True, Sep=False, NoRel=False
    if b'Ref=REF-123' in resp.data and b'SkipTC=True' in resp.data:
        print("[PASS] Form submitted and processed successfully.")
    else:
        print("[FAIL] Form submission failed or flash message missing.")
        # print(resp.data)

if __name__ == "__main__":
    verify_dma_form()
