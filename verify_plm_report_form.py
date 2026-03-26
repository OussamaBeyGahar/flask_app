from app import app, db, User
from werkzeug.security import generate_password_hash
import io

def verify_plm_report_form():
    client = app.test_client()
    
    with app.app_context():
        db.create_all()
        # Ensure Admin exists
        admin = User.query.filter_by(username='admin_report').first()
        if not admin:
            admin = User(username='admin_report', email='admin_report@test.com', first_name='Admin', last_name='Report', site_source='BLO', site_destination='BLO', password=generate_password_hash('pass'), is_admin=True, is_approved=True)
            db.session.add(admin)
            db.session.commit()

    # Login
    client.post('/login', data={'username': 'admin_report', 'password': 'pass'}, follow_redirects=True)

    # 1. Check Page Content
    print("Checking page content...")
    resp = client.get('/plm_report', follow_redirects=True)
    
    if b'Import PLM repport' in resp.data:
        print("[PASS] Title updated.")
    else:
        print("[FAIL] Title NOT updated.")

    if b'type="file"' in resp.data and b'accept=".xlsx, .xlsm"' in resp.data:
        print("[PASS] File input with accept attribute present.")
    else:
        print("[FAIL] File input missing or accept attribute incorrect.")

    # 2. Test Valid File Upload
    print("Testing valid file upload (.xlsx)...")
    data = {
        'plm_file': (io.BytesIO(b"dummy content"), 'test.xlsx')
    }
    resp = client.post('/plm_report', data=data, content_type='multipart/form-data', follow_redirects=True)
    
    if b'File "test.xlsx" uploaded successfully' in resp.data:
        print("[PASS] Valid file upload successful.")
    else:
        print("[FAIL] Valid file upload failed.")
        print(f"Response data: {resp.data[:300]}")

    # 3. Test Invalid File Upload
    print("Testing invalid file upload (.txt)...")
    data = {
        'plm_file': (io.BytesIO(b"dummy content"), 'test.txt')
    }
    resp = client.post('/plm_report', data=data, content_type='multipart/form-data', follow_redirects=True)
    
    if b'Invalid file format' in resp.data:
        print("[PASS] Invalid file format rejected.")
    else:
        print("[FAIL] Invalid file format NOT rejected.")

if __name__ == "__main__":
    verify_plm_report_form()
