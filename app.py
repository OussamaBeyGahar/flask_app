from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Page, Setting, Job
import os
import xmlrpc.client
import xml.etree.ElementTree as ET
from functools import wraps

from config import config

app = Flask(__name__)
# Load config, default to development
config_name = os.environ.get('FLASK_ENV', 'default')
app.config.from_object(config[config_name])
db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('You do not have permission to access that page.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def check_access(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_admin:
            return f(*args, **kwargs)
        
        # Get the endpoint name (e.g., 'eco_design_dma')
        endpoint = request.endpoint
        page = Page.query.filter_by(endpoint=endpoint).first()
        
        if page and page not in current_user.pages:
            flash('You do not have access to this page.', 'error')
            return redirect(url_for('dashboard'))
            
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def check_maintenance():
    # Only process this if the app has been initialized
    if getattr(app, '_got_first_request', False):
        # Allow access to static files (like CSS/images)
        if request.path.startswith('/static/'):
            return
            
        # Check current maintenance setting
        maintenance_setting = Setting.query.filter_by(key='maintenance_mode').first()
        is_maintenance = maintenance_setting and maintenance_setting.value == 'True'

        if is_maintenance:
            # Allow admins to bypass maintenance page
            if current_user.is_authenticated and current_user.is_admin:
                return

            # Allow access to the login route so admins can log in
            if request.endpoint == 'login' or request.endpoint == 'maintenance':
                return
                
            return redirect(url_for('maintenance'))

@app.route('/maintenance')
def maintenance():
    maintenance_setting = Setting.query.filter_by(key='maintenance_mode').first()
    if not maintenance_setting or maintenance_setting.value == 'False':
        return redirect(url_for('home'))
        
    return render_template('maintenance.html')

@app.route('/admin/access_control', methods=['GET', 'POST'])
@login_required
@admin_required
def access_control():
    if request.method == 'POST':
        # Clear existing permissions (inefficient but simple for this scale)
        # Better: iterate through form data
        users = User.query.all()
        pages = Page.query.all()
        
        for user in users:
            if user.is_admin: continue # Admins have all access
            user.pages = [] # Reset
            for page in pages:
                if request.form.get(f'access_{user.id}_{page.id}'):
                    user.pages.append(page)
        db.session.commit()
        flash('Access permissions updated.', 'success')
        return redirect(url_for('access_control'))
        
    query = request.args.get('q', '')
    user_query = User.query.filter_by(is_admin=False)
    
    if query:
        user_query = user_query.filter((User.username.contains(query)) | (User.email.contains(query)))
        
    users = user_query.all()
    pages = Page.query.all()
    return render_template('admin_access_control.html', users=users, pages=pages)

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    users = User.query.all()
    maintenance_setting = Setting.query.filter_by(key='maintenance_mode').first()
    maintenance_mode = maintenance_setting.value if maintenance_setting else 'False'
    return render_template('admin.html', users=users, maintenance_mode=maintenance_mode)

@app.route('/admin/toggle_maintenance', methods=['POST'])
@login_required
@admin_required
def toggle_maintenance():
    setting = Setting.query.filter_by(key='maintenance_mode').first()
    if not setting:
        setting = Setting(key='maintenance_mode', value='True')
        db.session.add(setting)
    else:
        setting.value = 'False' if setting.value == 'True' else 'True'
    
    db.session.commit()
    status = "enabled" if setting.value == 'True' else "disabled"
    flash(f'Maintenance mode has been {status}.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/approve/<int:user_id>')
@login_required
@admin_required
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    db.session.commit()
    flash(f'User {user.username} approved.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<int:user_id>')
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete yourself.', 'error')
        return redirect(url_for('admin_dashboard'))
    
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.username} deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle_admin/<int:user_id>')
@login_required
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot remove your own admin status.', 'error')
        return redirect(url_for('admin_dashboard'))

    user.is_admin = not user.is_admin
    db.session.commit()
    status = "Admin" if user.is_admin else "User"
    flash(f'{user.username} is now a {status}.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            if not user.is_approved:
                flash('Account pending approval. Please wait for an admin to approve your account.', 'warning')
                return redirect(url_for('login'))
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        country = request.form.get('country')
        password = request.form.get('password')
        
        user_exists = User.query.filter((User.username == username) | (User.email == email)).first()
        if user_exists:
            flash('Username or Email already exists.', 'error')
            return redirect(url_for('register'))

        new_user = User(
            username=username, 
            email=email,
            first_name=first_name,
            last_name=last_name,
            country=country,
            password=generate_password_hash(password),
            is_approved=False
        )
        db.session.add(new_user)
        db.session.commit()
        
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/dashboard')
@login_required
@check_access
def dashboard():
    full_name = f"{current_user.first_name} {current_user.last_name}"
    return render_template('dashboard.html', name=full_name)

@app.route('/check_plm_xml', methods=['GET', 'POST'])
@login_required
@check_access
def check_plm_xml():
    if request.method == 'POST':
        dma_reference = request.form.get('dma_reference', '').strip()
        skip_ref = 'skip_reference' in request.form
        skip_tc  = 'skip_teamcenter' in request.form
        as_proto = 'as_prototype' in request.form
        check_lvl = request.form.get('check_level', 'all')
        plm_notes = request.form.get('plm_notes', '')

        if not dma_reference:
            flash('DMA reference is required.', 'error')
            return redirect(url_for('check_plm_xml'))

        # Build option string — mirrors original request_check_plm_xml logic
        option = "-"
        if skip_ref:
            lines = [l for l in plm_notes.replace('\r\n', '\n').split('\n') if l.strip()]
            if len(lines) == 1:
                option = "-EXCEPT{" + lines[0].replace("/", "_") + "}-"
            elif len(lines) > 1:
                option = ""
                for line in lines:
                    option += "-EXCEPT{" + line.replace("/", "_") + "}-"
                option = option.replace("--", "-")
        if as_proto:
            option = "-PROTO-"
        if skip_tc:
            option = "-SFT-"
        if as_proto and skip_tc:
            option = "-PROTO-SFT-"
        if check_lvl != 'all':
            option = option + check_lvl + "-"

        # Split DMA ref / rev (mirrors original: output_text.split("/"))
        parts = dma_reference.split("/")
        dma_ref = parts[0].strip()
        dma_rev = parts[1].strip() if len(parts) >= 2 else "#"

        try:
            proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
            uid = current_user.username
            site = current_user.country

            # Validate DMA reference exists on the server
            result = proxy.CHECKDMAREF(uid, dma_ref, dma_rev, app.config['HOST'], "0", option, site)
            dmaref, dmavers, dmaminor, dmacoid, dmamaturity = eval(result)

            if str(dmaref) != "None":
                # Duplicate-queue check
                existing = Job.query.filter_by(
                    user_id=current_user.id,
                    job_type='CHECKPLMXML',
                    dma_ref=dma_ref,
                    dma_rev=dma_rev,
                    status='QUEUED'
                ).first()
                if existing:
                    flash(f'Request already in queue: Ref={dma_ref}, Rev={dma_rev}', 'warning')
                    return redirect(url_for('check_plm_xml'))

                proxy.ADMINCHECKPLMXML(uid, dma_ref, dma_rev, request.remote_addr, "0", option, site)

                job = Job(
                    user_id=current_user.id,
                    job_type='CHECKPLMXML',
                    dma_ref=dma_ref,
                    dma_rev=dma_rev,
                    option=option,
                    status='QUEUED'
                )
                db.session.add(job)
                db.session.commit()

                flash(f'CheckPLMXML job queued: Ref={dma_ref}, Rev={dma_rev}, Options={option}, Level={check_lvl}', 'success')
            else:
                flash(f'DMA reference not found: {dma_ref}/{dma_rev}', 'error')

        except Exception as e:
            flash(f'XML-RPC error: {e}', 'error')

        return redirect(url_for('check_plm_xml'))
    return render_template('check_plm_xml.html')

@app.route('/check_bat_contract', methods=['GET', 'POST'])
@login_required
@check_access
def check_bat_contract():
    if request.method == 'POST':
        dtr_list = request.form.get('dtr_list')
        
        # Truncate for display if too long
        display_dtr = (dtr_list[:50] + '...') if len(dtr_list) > 50 else dtr_list
        flash(f'Form submitted: DTR List={display_dtr}', 'success')
        return redirect(url_for('check_bat_contract'))
    return render_template('check_bat_contract.html')

@app.route('/dma_to_team_center', methods=['GET', 'POST'])
@login_required
@check_access
def dma_to_team_center():
    if request.method == 'POST':
        dma_ref = request.form.get('dma_reference')
        skip_tc = 'skip_teamcenter' in request.form
        as_proto = 'as_prototype' in request.form
        doc_sep = 'doc_sep' in request.form
        no_rel = 'doc_sep_no_relation' in request.form
        
        flash(f'Form submitted: Ref={dma_ref}, SkipTC={skip_tc}, Proto={as_proto}, Sep={doc_sep}, NoRel={no_rel}', 'success')
        return redirect(url_for('dma_to_team_center'))
    return render_template('dma_to_team_center.html')

@app.route('/plm_report', methods=['GET', 'POST'])
@login_required
@check_access
def plm_report():
    if request.method == 'POST':
        if 'plm_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
            
        file = request.files['plm_file']
        
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
            
        if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xlsm')):
            flash(f'File "{file.filename}" uploaded successfully.', 'success')
            return redirect(url_for('plm_report'))
        else:
            flash('Invalid file format. Only .xlsx and .xlsm are allowed.', 'error')
            return redirect(request.url)
            
    return render_template('plm_report.html')

@app.route('/eco_design_dma', methods=['GET', 'POST'])
@login_required
@check_access
def eco_design_dma():
    if request.method == 'POST':
        dma_ref = request.form.get('dma_reference')
        flash(f'Form submitted: Ref={dma_ref}', 'success')
        return redirect(url_for('eco_design_dma'))
    return render_template('eco_design_dma.html')

@app.route('/eco_design_enovia', methods=['GET', 'POST'])
@login_required
@check_access
def eco_design_enovia():
    if request.method == 'POST':
        if 'enovia_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
            
        file = request.files['enovia_file']
        
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
            
        if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xlsm')):
            flash(f'File "{file.filename}" uploaded successfully.', 'success')
            return redirect(url_for('eco_design_enovia'))
        else:
            flash('Invalid file format. Only .xlsx and .xlsm are allowed.', 'error')
            return redirect(request.url)
            
    return render_template('eco_design_enovia.html')

@app.route('/exported3d_dma', methods=['GET', 'POST'])
@login_required
@check_access
def exported3d_dma():
    if request.method == 'POST':
        dma_ref = request.form.get('dma_reference')
        has_step = 'step' in request.form
        has_thickness = 'thickness' in request.form
        flash(f'Form submitted: Ref={dma_ref}, Step={has_step}, Thickness={has_thickness}', 'success')
        return redirect(url_for('exported3d_dma'))
    return render_template('exported3d_dma.html')

@app.route('/exported3d_tcra', methods=['GET', 'POST'])
@login_required
@check_access
def exported3d_tcra():
    if request.method == 'POST':
        if 'excel_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
            
        file = request.files['excel_file']
        
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
            
        if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xlsm')):
            flash(f'File "{file.filename}" uploaded successfully.', 'success')
            return redirect(url_for('exported3d_tcra'))
        else:
            flash('Invalid file format. Only .xlsx and .xlsm are allowed.', 'error')
            return redirect(request.url)
    return render_template('exported3d_tcra.html')

@app.route('/exported3d_report')
@login_required
@check_access
def exported3d_report():
    return render_template('exported3d_report.html')

@app.route('/ext2dmz_neodma', methods=['GET', 'POST'])
@login_required
@check_access
def ext2dmz_neodma():
    if request.method == 'POST':
        if 'neodma_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['neodma_file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
        if file:
            flash(f'File "{file.filename}" uploaded successfully.', 'success')
            return redirect(url_for('ext2dmz_neodma'))
    return render_template('ext2dmz_neodma.html')

@app.route('/ext2dmz_elsa2dma', methods=['GET', 'POST'])
@login_required
@check_access
def ext2dmz_elsa2dma():
    if request.method == 'POST':
        if 'elsa2dma_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['elsa2dma_file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
        if file:
            flash(f'File "{file.filename}" uploaded successfully.', 'success')
            return redirect(url_for('ext2dmz_elsa2dma'))
    return render_template('ext2dmz_elsa2dma.html')

@app.route('/ext2dmz_excel2dma', methods=['GET', 'POST'])
@login_required
@check_access
def ext2dmz_excel2dma():
    if request.method == 'POST':
        if 'excel2dma_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['excel2dma_file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
        if file:
            flash(f'File "{file.filename}" uploaded successfully.', 'success')
            return redirect(url_for('ext2dmz_excel2dma'))
    return render_template('ext2dmz_excel2dma.html')

@app.route('/ext2dmz_elsa2bthtsp', methods=['GET', 'POST'])
@login_required
@check_access
def ext2dmz_elsa2bthtsp():
    if request.method == 'POST':
        if 'elsa2bthtsp_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['elsa2bthtsp_file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
        if file:
            flash(f'File "{file.filename}" uploaded successfully.', 'success')
            return redirect(url_for('ext2dmz_elsa2bthtsp'))
    return render_template('ext2dmz_elsa2bthtsp.html')

@app.route('/delta_dma', methods=['GET', 'POST'])
@login_required
@check_access
def delta_dma():
    if request.method == 'POST':
        source_ref = request.form.get('source_dma_reference')
        dest_ref = request.form.get('destination_dma_reference')
        flash(f'Form submitted: Source Ref={source_ref}, Destination Ref={dest_ref}', 'success')
        return redirect(url_for('delta_dma'))
    return render_template('delta_dma.html')

@app.route('/delta_tcra', methods=['GET', 'POST'])
@login_required
@check_access
def delta_tcra():
    if request.method == 'POST':
        source_ref = request.form.get('source_tcra_reference')
        source_on_working = 'source_on_working' in request.form
        dest_ref = request.form.get('destination_tcra_reference')
        dest_on_working = 'destination_on_working' in request.form
        flash(f'Form submitted: Source Ref={source_ref}, Source Working={source_on_working}, Dest Ref={dest_ref}, Dest Working={dest_on_working}', 'success')
        return redirect(url_for('delta_tcra'))
    return render_template('delta_tcra.html')

@app.route('/tcra_report', methods=['GET', 'POST'])
@login_required
@check_access
def tcra_report():
    if request.method == 'POST':
        tc_ref = request.form.get('tc_reference')
        flash(f'Form submitted: TC Ref={tc_ref}', 'success')
        return redirect(url_for('tcra_report'))
    return render_template('tcra_report.html')

@app.route('/tcra_delta_check', methods=['GET', 'POST'])
@login_required
@check_access
def tcra_delta_check():
    if request.method == 'POST':
        source_file = request.files.get('source_tcra_file')
        source_filename = source_file.filename if source_file else 'None'
        
        dest_type = request.form.get('dest_load_type')
        if dest_type == 'file':
            dest_file = request.files.get('dest_tcra_file')
            dest_val = f"File: {dest_file.filename if dest_file else 'None'}"
        else:
            dest_val = f"Reference: {request.form.get('dest_tcra_reference')}"
            
        flash(f'Form submitted: Source={source_filename}, Destination=({dest_type}) {dest_val}', 'success')
        return redirect(url_for('tcra_delta_check'))
        
    return render_template('tcra_delta_check.html')

@app.route('/tcra_delta_dma_check', methods=['GET', 'POST'])
@login_required
@check_access
def tcra_delta_dma_check():
    if request.method == 'POST':
        source_type = request.form.get('source_load_type')
        if source_type == 'reference':
            source_ref = request.form.get('source_tcra_reference')
            source_date = request.form.get('source_tcra_date')
            source_val = f"Ref: {source_ref}, Date: {source_date}"
        else:
            source_file = request.files.get('source_tcra_file')
            source_val = f"File: {source_file.filename if source_file else 'None'}"
            
        dest_ref = request.form.get('dest_dma_reference')
        
        flash(f'Form submitted: Source=({source_type}) {source_val}, Dest DMA Ref={dest_ref}', 'success')
        return redirect(url_for('tcra_delta_dma_check'))
        
    return render_template('tcra_delta_dma_check.html')

@app.route('/tcra_delta_eng_check', methods=['GET', 'POST'])
@login_required
@check_access
def tcra_delta_eng_check():
    if request.method == 'POST':
        incl_specs = 'include_specifications' in request.form
        incl_refs = 'include_references' in request.form
        
        src_ref = request.form.get('source_tcra_reference')
        src_date = request.form.get('source_tcra_date')
        
        dest_ref = request.form.get('dest_tcra_reference')
        dest_date = request.form.get('dest_tcra_date')
        
        flash(f'Form submitted: Specs={incl_specs}, Refs={incl_refs}, Source=({src_ref}, {src_date}), Dest=({dest_ref}, {dest_date})', 'success')
        return redirect(url_for('tcra_delta_eng_check'))
        
    return render_template('tcra_delta_eng_check.html')

@app.route('/request_queued')
@login_required
@check_access
def request_queued():
    jobs = Job.query.filter_by(user_id=current_user.id, status='QUEUED').order_by(Job.created_at.desc()).all()
    return render_template('request_queued.html', jobs=jobs)

@app.route('/request_completed')
@login_required
@check_access
def request_completed():
    # Current user's completed jobs only (mirrors /t7 in original)
    jobs = Job.query.filter_by(user_id=current_user.id, status='COMPLETED').order_by(Job.created_at.desc()).all()
    return render_template('request_completed.html', jobs=jobs)

@app.route('/request_all_completed')
@login_required
@admin_required
def request_all_completed():
    # All users' completed jobs — mirrors /r7 in original (admin only)
    jobs = []
    error = None
    try:
        proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
        new = proxy.LISTREQUEST("COMPLETED", "ALL", "toto")
        t = ET.fromstring(new)
        lines = list(t)[0].findall('line')
        for x in reversed(lines):
            jobs.append(x.get('value') + " (" + x.get('owner') + ")")
    except Exception as e:
        error = str(e)
    return render_template('request_all_completed.html', jobs=jobs, error=error)

@app.route('/request_failed')
@login_required
@check_access
def request_failed():
    return render_template('request_failed.html')

@app.route('/request_all_failed')
@login_required
@check_access
def request_all_failed():
    return render_template('request_all_failed.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Initialize maintenance mode setting if missing
        if not Setting.query.filter_by(key='maintenance_mode').first():
            db.session.add(Setting(key='maintenance_mode', value='False'))
            db.session.commit()
        
        # Initialize pages
        endpoints = [
            'check_plm_xml', 'check_bat_contract', 'dma_to_team_center', 'plm_report',
            'eco_design_dma', 'eco_design_enovia',
            'exported3d_dma', 'exported3d_tcra', 'exported3d_report',
            'ext2dmz_neodma', 'ext2dmz_elsa2dma', 'ext2dmz_excel2dma', 'ext2dmz_elsa2bthtsp',
            'delta_dma', 'delta_tcra',
            'tcra_report', 'tcra_delta_check', 'tcra_delta_dma_check', 'tcra_delta_eng_check',
            'request_queued', 'request_completed', 'request_all_completed', 'request_failed', 'request_all_failed'
        ]
        
        for endpoint in endpoints:
            if not Page.query.filter_by(endpoint=endpoint).first():
                # specific name formatting
                name = endpoint.replace('_', ' ').title()
                db.session.add(Page(name=name, endpoint=endpoint))
        db.session.commit()
    app.run(debug=True)
