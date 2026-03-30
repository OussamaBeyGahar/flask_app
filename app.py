from flask import Flask, render_template, redirect, url_for, request, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Page, Setting, Job
import os
import sys
import time
import subprocess
import xmlrpc.client
import xml.etree.ElementTree as ET
import io
import re
import json
from functools import wraps

from config import config


def _save_job(job_type, ref, rev=None):
    """Persist a job record to the local DB for audit trail."""
    try:
        job = Job(
            user_id=current_user.id,
            job_type=job_type,
            dma_ref=ref,
            dma_rev=rev,
            status='QUEUED'
        )
        db.session.add(job)
        db.session.commit()
    except Exception:
        pass


def strip_site_from_job(s):
    """Strip site prefix from job value string.
    e.g. '2026_03_26-14_44_57_-BLOCHECKPLMXML-BLO-AK00002472288-B'
      -> '2026_03_26-14_44_57_-CHECKPLMXML-AK00002472288-B'
    """
    m = re.match(r'(\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}_-)([A-Z]+)(-.+)', s)
    if not m:
        return s
    prefix, combined, rest = m.group(1), m.group(2), m.group(3)
    parts = rest.split('-')  # ['', 'BLO', 'AK00002472288', 'B']
    if len(parts) >= 3 and parts[1] and combined.startswith(parts[1]):
        site = parts[1]
        job_type = combined[len(site):]
        new_rest = '-'.join(parts[2:])
        return prefix + job_type + '-' + new_rest
    return s


def write_ura_nodes(dst, node, level):
    """Recursively write URA tree nodes to the structured text file."""
    tag = node.tag
    text = node.text or ''
    if tag == 'R':
        dst.write(f"{level}:SubReport :{text}\n")
    else:
        dst.write(f"{level}:DMA :{text}\n")
    for child in list(node):
        write_ura_nodes(dst, child, level + 1)


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

@app.route('/admin/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.first_name = request.form.get('first_name', user.first_name)
        user.last_name = request.form.get('last_name', user.last_name)
        user.email = request.form.get('email', user.email)
        user.site_source = request.form.get('site_source', user.site_source)
        user.site_destination = request.form.get('site_destination', user.site_destination)
        new_password = request.form.get('new_password', '').strip()
        if new_password:
            user.password = generate_password_hash(new_password)
        db.session.commit()
        flash(f'User {user.username} updated.', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_edit_user.html', user=user)

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
        site_source = request.form.get('site_source')
        site_destination = request.form.get('site_destination')
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
            site_source=site_source,
            site_destination=site_destination,
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
    uid = current_user.username
    queued_jobs, running_jobs, failed_jobs = [], [], []
    try:
        proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
        for status, lst in [("QUEUED", queued_jobs), ("RUNNING", running_jobs), ("FAILED", failed_jobs)]:
            t = ET.fromstring(proxy.LISTREQUEST(status, "ALL", "toto"))
            for x in reversed(list(t)[0].findall('line')):
                if x.get('owner') == uid:
                    lst.append(strip_site_from_job(x.get('value')))
    except Exception:
        pass
    return render_template('dashboard.html', name=full_name,
                           queued_jobs=queued_jobs,
                           running_jobs=running_jobs,
                           failed_jobs=failed_jobs)

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
            site = current_user.site_source

            # Validate DMA reference exists on the server
            result = proxy.CHECKDMAREF(uid, dma_ref, dma_rev, app.config['HOST'], "0", option, site)
            dmaref, dmavers, dmaminor, dmacoid, dmamaturity = eval(result)

            if str(dmaref) != "None":
                # Check spool QUEUED dir for existing request (mirrors old ExportTool check_queued)
                check_string = dma_ref + '-' + dma_rev
                queued_found = False
                try:
                    queued_dir = os.path.join(app.config['SHARE_SPOOL'], 'QUEUED')
                    for fname in os.listdir(queued_dir):
                        if ('CHECKPLMXML' in fname or 'CHECKGSI' in fname) and check_string in fname:
                            with open(os.path.join(queued_dir, fname), 'r') as qf:
                                for line in qf:
                                    if line.split('<>')[1] == uid:
                                        queued_found = True
                                        break
                        if queued_found:
                            break
                except Exception:
                    pass

                if queued_found:
                    flash(f'Request already in queue: {dma_ref}/{dma_rev}', 'warning')
                    return redirect(url_for('check_plm_xml'))

                proxy.ADMINCHECKPLMXML(uid, dma_ref, dma_rev, request.remote_addr, "0", option, "-")
                _save_job('CHECKPLMXML', dma_ref, dma_rev)
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
    result = None
    error = None
    if request.method == 'POST':
        dtr_input = request.form.get('dtr_list', '')
        dtr_inline = dtr_input.replace('\n', ';').replace('\r', '').strip()
        try:
            p = subprocess.Popen(
                [sys.executable, app.config['PY_CHECK_BAT_CONTRACT'], dtr_inline],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, stderr = p.communicate()
            result = stdout.decode('utf-8', errors='replace')
            if not result and stderr:
                error = stderr.decode('utf-8', errors='replace')
        except Exception as e:
            error = str(e)
    return render_template('check_bat_contract.html', result=result, error=error)

@app.route('/dma_to_team_center', methods=['GET', 'POST'])
@login_required
@check_access
def dma_to_team_center():
    if request.method == 'POST':
        dma_reference = request.form.get('dma_reference', '').strip()
        skip_tc  = 'skip_teamcenter' in request.form
        as_proto = 'as_prototype' in request.form
        doc_sep  = 'doc_sep' in request.form
        no_rel   = 'doc_sep_no_relation' in request.form

        if not dma_reference:
            flash('DMA reference is required.', 'error')
            return redirect(url_for('dma_to_team_center'))

        # Build option string — mirrors RequestDmatoPlmXml logic
        option = "-"
        if doc_sep:  option = "-DRS-"
        if no_rel:   option = "-NOREL-"
        if as_proto: option = "-PROTO-"
        if skip_tc:  option = "-SFT-"
        if as_proto and skip_tc:                    option = "-SFT-PROTO-"
        if as_proto and skip_tc and doc_sep:        option = "-SFT-DRS-PROTO-"
        if as_proto and skip_tc and no_rel:         option = "-SFT-DRS-NOREL-PROTO-"

        # Parse DMA ref / rev — handle optional #R or #<other> suffix
        parts = dma_reference.split("/")
        dma_ref     = parts[0].strip()
        dma_rev_raw = parts[1].strip() if len(parts) >= 2 else "#"

        if "#" in dma_rev_raw:
            nobom   = dma_rev_raw.split("#")
            dma_rev = nobom[0]
            suffix  = nobom[1] if len(nobom) > 1 else ""
            if suffix == "R":
                option = option + "BOMREL-"
            else:
                option = option + "NOBOM-"
        else:
            dma_rev = dma_rev_raw

        try:
            proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
            uid  = current_user.username
            site = current_user.site_source

            # Validate DMA reference exists
            result = proxy.CHECKDMAREF(uid, dma_ref, dma_rev, app.config['HOST'], "0", option, site)
            dmaref, dmavers, dmaminor, dmacoid, dmamaturity = eval(result)

            if str(dmaref) != "None":
                proxy.ADMINDMA2PLMXML(uid, dma_ref, dma_rev, request.remote_addr, "0", option, site)
                _save_job('DMA2PLMXML', dma_ref, dma_rev)
                flash(f'DMA2PLMXML job queued: Ref={dma_ref}, Rev={dma_rev}, Options={option}', 'success')
            else:
                flash(f'DMA reference not found: {dma_ref}/{dma_rev}', 'error')

        except Exception as e:
            flash(f'XML-RPC error: {e}', 'error')

        return redirect(url_for('dma_to_team_center'))
    return render_template('dma_to_team_center.html')

@app.route('/plm_report', methods=['GET', 'POST'])
@login_required
@check_access
def plm_report():
    results = []
    error = None
    if request.method == 'POST':
        files = request.files.getlist('plm_file')
        if not files or all(f.filename == '' for f in files):
            flash('No file selected.', 'error')
            return redirect(request.url)
        try:
            proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
            uid = current_user.username
            for f in files:
                fn = os.path.basename(f.filename)
                if not (fn.endswith('.xlsx') or fn.endswith('.xlsm')):
                    flash(f'Skipped "{fn}": invalid format.', 'warning')
                    continue
                dma_ref = time.strftime("%Y%m%d_%H%M%S") + "_PLMREPORT_" + fn
                dma_rev = "NotUsed"
                export_file = os.path.normpath(os.path.join(app.config['PREPROCESSING_REPORT'], dma_ref))
                f.save(export_file)
                proxy.PLMREPORT(uid, dma_ref, dma_rev, request.remote_addr, "0", "-OptionNotUsed")
                _save_job('PLMREPORT', fn)
                hyperlink = "file://sacrl1gla2/" + fn[0:3] + "_PLM_Reports/Reports"
                results.append({'filename': fn, 'hyperlink': hyperlink})
        except Exception as e:
            error = str(e)
    return render_template('plm_report.html', results=results, error=error)

@app.route('/eco_design_dma', methods=['GET', 'POST'])
@login_required
@check_access
def eco_design_dma():
    error = None
    if request.method == 'POST':
        eco_reference = request.form.get('dma_reference', '').strip()
        if not eco_reference:
            flash('DMA reference is required.', 'error')
            return redirect(url_for('eco_design_dma'))
        try:
            ref_rev      = eco_reference.split('/')
            reference    = ref_rev[0].strip()
            revision     = ref_rev[1].strip() if len(ref_rev) > 1 else ""
            ext_revision = '_' + revision if revision else ""

            req_file_name = time.strftime(f"%Y_%m_%d-%H_%M_%S_-ECOREPORT-{reference}{ext_revision}")
            username  = f"{current_user.first_name} {current_user.last_name}"
            uid       = current_user.username
            front_data = {'action': 'ECODESIGN-REPORT', 'language': 'EN', 'name': username}
            data = f"ECO-<>{uid}<>{reference}<>{revision}<>0<>0<>{front_data}"

            queued_path = os.path.join(app.config['SHARE_SPOOL'], "QUEUED", req_file_name)
            with open(queued_path, "w") as f:
                f.write(data)

            _save_job('ECODESIGNDMA', reference, revision or None)
            flash(f'Eco Design job queued: {reference}/{revision if revision else "#"}', 'success')
        except Exception as e:
            error = str(e)
    return render_template('eco_design_dma.html', error=error)

@app.route('/eco_design_enovia', methods=['GET', 'POST'])
@login_required
@check_access
def eco_design_enovia():
    error = None
    if request.method == 'POST':
        if 'enovia_file' not in request.files:
            error = 'No file part in request.'
            return render_template('eco_design_enovia.html', error=error)

        file = request.files['enovia_file']

        if file.filename == '':
            error = 'No file selected.'
            return render_template('eco_design_enovia.html', error=error)

        fn = os.path.basename(file.filename)
        if not (fn.endswith('.xlsx') or fn.endswith('.xlsm')):
            error = 'Invalid file format. Only .xlsx and .xlsm are allowed.'
            return render_template('eco_design_enovia.html', error=error)

        try:
            fn_noext = os.path.splitext(fn)[0]
            req_file_name = time.strftime(f"%Y_%m_%d-%H_%M_%S_-ECOREPORT-ENOVIA_{fn_noext}")

            # Save uploaded file to SHARE_ALTERNATE_WORKING
            dest_dir = os.path.join(app.config['SHARE_ALTERNATE_WORKING'], req_file_name)
            os.makedirs(dest_dir, exist_ok=True)
            enovia_file_path = os.path.join(dest_dir, fn)
            file.save(enovia_file_path)

            # Write spool token file
            uid = current_user.username
            username = f"{current_user.first_name} {current_user.last_name}"
            front_data = {'action': 'ECODESIGN-REPORT-ENOVIA', 'language': 'EN', 'name': username, 'enovia_file': enovia_file_path}
            data = f"ECO-<>{uid}<><><>0<>0<>{front_data}"

            queued_path = os.path.join(app.config['SHARE_SPOOL'], "QUEUED", req_file_name)
            with open(queued_path, "w") as f:
                f.write(data)

            _save_job('ECODESIGNENOVIA', fn)
            flash(f'Eco Design Enovia job queued: {fn}', 'success')
            return redirect(url_for('eco_design_enovia'))
        except Exception as e:
            error = str(e)

    return render_template('eco_design_enovia.html', error=error)

@app.route('/exported3d_dma', methods=['GET', 'POST'])
@login_required
@check_access
def exported3d_dma():
    if request.method == 'POST':
        dma_reference = request.form.get('dma_reference', '').strip()
        has_step = 'step' in request.form
        has_thickness = 'thickness' in request.form

        if not dma_reference:
            flash('DMA reference is required.', 'error')
            return redirect(url_for('exported3d_dma'))

        # Build option string — mutually exclusive (step takes priority)
        if has_step:
            option = "-STEP-"
        elif has_thickness:
            option = "-THICK-"
        else:
            option = "-"

        # Parse DMA ref / rev
        parts = dma_reference.split("/")
        dma_ref = parts[0].strip()
        dma_rev = parts[1].strip() if len(parts) >= 2 else "#"

        try:
            proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
            uid = current_user.username

            # Validate DMA reference — no site param for this route
            result = proxy.CHECKDMAREF(uid, dma_ref, dma_rev, app.config['HOST'], "0", option)
            dmaref, dmavers, dmaminor, dmacoid, dmamaturity = eval(result)

            if str(dmaref) != "None":
                proxy.ADMIN3DFROMDMA(uid, dma_ref, dma_rev, request.remote_addr, "0", option)
                _save_job('3DFROMDMA', dma_ref, dma_rev)
                flash(f'3D from DMA job queued: Ref={dma_ref}, Rev={dma_rev}, Options={option}', 'success')
            else:
                flash(f'DMA reference not found: {dma_ref}/{dma_rev}', 'error')

        except Exception as e:
            flash(f'XML-RPC error: {e}', 'error')

        return redirect(url_for('exported3d_dma'))
    return render_template('exported3d_dma.html')

@app.route('/exported3d_tcra', methods=['GET', 'POST'])
@login_required
@check_access
def exported3d_tcra():
    results = []
    error = None
    if request.method == 'POST':
        files = request.files.getlist('tcra_file')
        if not files or all(f.filename == '' for f in files):
            flash('No file selected.', 'error')
            return redirect(request.url)
        try:
            proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
            uid = current_user.username
            opt_str = "-STEP-"
            for f in files:
                fn = os.path.basename(f.filename)
                dma_ref = time.strftime("%Y%m%d_%H%M%S") + "_TCRA_" + fn
                dma_rev = "NotUsed"
                export_file = os.path.normpath(os.path.join(app.config['PREPROCESSING_REPORT'], dma_ref))
                f.save(export_file)
                proxy.ADMIN3DFROMTCRA(uid, dma_ref, dma_rev, request.remote_addr, "0", opt_str)
                _save_job('3DFROMTCRA', fn)
                hyperlink = "file://sacrl1gla2/" + fn[0:3] + "_PLM_Reports/Reports"
                results.append({'filename': fn, 'hyperlink': hyperlink})
        except Exception as e:
            error = str(e)
    return render_template('exported3d_tcra.html', results=results, error=error)

@app.route('/exported3d_report', methods=['GET', 'POST'])
@login_required
@check_access
def exported3d_report():
    error = None
    if request.method == 'POST':
        xml_data = request.form.get('tree_xml', '').strip()
        has_step = 'step' in request.form
        if not xml_data:
            error = 'No tree data submitted.'
            return render_template('exported3d_report.html', error=error)
        try:
            tree = ET.fromstring(xml_data)
            children = list(tree)
            report_name = children[0].text if children else 'report'
            dma_ref = time.strftime("%Y%m%d_%H%M%S") + "_URA_" + report_name
            dma_rev = "NotUsed"
            option = "-STEP-" if has_step else "-"

            export_file = os.path.normpath(os.path.join(app.config['PREPROCESSING_REPORT'], dma_ref))
            with open(export_file, "w") as dst:
                if tree.tag == 'Report':
                    dst.write(f"1:{tree.tag}:{report_name}\n")
                for child in list(children[0]):
                    write_ura_nodes(dst, child, 2)

            proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
            proxy.ADMIN3DFROMDMA(current_user.username, dma_ref, dma_rev, request.remote_addr, "0", option)
            _save_job('URAREPORT', report_name)
            flash(f'URA report job queued: {report_name}', 'success')
            return redirect(url_for('exported3d_report'))
        except Exception as e:
            error = str(e)
    return render_template('exported3d_report.html', error=error)


@app.route('/exported3d_report_check', methods=['POST'])
@login_required
def exported3d_report_check():
    refs_text = request.form.get('refs', '').strip()
    result = ''
    try:
        proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
        uid = current_user.username
        for line in refs_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            # Format: AK00001234567/A — ref is first 13 chars, rev from char 14 onward
            dma_ref = line[0:13].upper()
            dma_rev = line[14:].upper() if len(line) > 14 else '#'
            new = proxy.CHECKDMAREF(uid, dma_ref, dma_rev, app.config['HOST'], "0", "-")
            dmaref, *_ = eval(new)
            if str(dmaref) != "None":
                result += dma_ref + "/" + dma_rev + "\n"
            elif dma_ref:
                result += dma_ref + "/" + dma_rev + " - Not found\n"
    except Exception as e:
        result = f"Error: {e}"
    return Response(result, mimetype='text/plain')

@app.route('/ext2dmz_neodma', methods=['GET', 'POST'])
@login_required
@check_access
def ext2dmz_neodma():
    error = None
    if request.method == 'POST':
        if 'neodma_file' not in request.files:
            error = 'No file part in request.'
            return render_template('ext2dmz_neodma.html', error=error)
        file = request.files['neodma_file']
        if file.filename == '':
            error = 'No file selected.'
            return render_template('ext2dmz_neodma.html', error=error)
        try:
            fn = os.path.basename(file.filename)
            file_bytes = file.read()

            # Parse XML to extract PartNumber and HarnessVersion from MHBillOfMaterial
            try:
                tree = ET.parse(io.BytesIO(file_bytes))
            except ET.ParseError as e:
                error = f'The input file is not a valid XML file: {e}'
                return render_template('ext2dmz_neodma.html', error=error)

            root = tree.getroot()
            rev_xml = ''
            ref_xml = ''
            for child in root:
                if child.tag == 'MHBillOfMaterial':
                    rev_xml = str(child.attrib.get('HarnessVersion', '')).strip().upper()
                    ref_xml = str(child.attrib.get('PartNumber', '')).strip().upper()
                    break

            if not rev_xml or not ref_xml:
                error = 'Missing PartNumber or HarnessVersion in MHBillOfMaterial element.'
                return render_template('ext2dmz_neodma.html', error=error)

            # Validate ref/rev exists via XML-RPC (replaces direct DB query)
            proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
            uid = current_user.username
            check = proxy.CHECKDMAREF(uid, ref_xml, rev_xml, app.config['HOST'], "0", "-")
            dmaref, *_ = eval(check)
            if str(dmaref) == "None":
                error = f'Reference {ref_xml}/{rev_xml} from XML file not found in DMA.'
                return render_template('ext2dmz_neodma.html', error=error)

            # Rebuild filename as {ref}@{rev}@{original} and build DMAref
            fn_parts = fn.split('@')
            fn_base = fn_parts[-1]
            fn = f"{ref_xml}@{rev_xml}@{fn_base}"
            dma_ref = time.strftime("%Y%m%d_%H%M%S") + "_NEOPLMXML_" + fn
            dma_rev = ""

            export_file = os.path.normpath(os.path.join(app.config['PREPROCESSING_REPORT'], dma_ref))
            with open(export_file, "wb") as dst:
                dst.write(file_bytes)

            uid_name = uid.split("@")[0].replace("NEO2DMA", "-NEO2DMA")
            proxy.NEOPLMXML(uid_name, dma_ref, dma_rev, request.remote_addr, "0", "-NEO2DMA-")
            _save_job('NEO2DMA', ref_xml, rev_xml)
            flash(f'NEO2DMA job queued: {ref_xml}/{rev_xml}', 'success')
            return redirect(url_for('ext2dmz_neodma'))
        except Exception as e:
            error = str(e)
    return render_template('ext2dmz_neodma.html', error=error)

@app.route('/ext2dmz_elsa2dma', methods=['GET', 'POST'])
@login_required
@check_access
def ext2dmz_elsa2dma():
    error = None
    if request.method == 'POST':
        if 'elsa2dma_file' not in request.files:
            error = 'No file part in request.'
            return render_template('ext2dmz_elsa2dma.html', error=error)
        file = request.files['elsa2dma_file']
        if file.filename == '':
            error = 'No file selected.'
            return render_template('ext2dmz_elsa2dma.html', error=error)
        try:
            fn = os.path.basename(file.filename)
            if '@' not in fn:
                error = f'Invalid filename "{fn}": must contain "@" separator (e.g. ref@rev@filename).'
                return render_template('ext2dmz_elsa2dma.html', error=error)

            dma_ref = time.strftime("%Y%m%d_%H%M%S") + "_NEOPLMXML_" + fn
            dma_rev = ""

            export_file = os.path.normpath(os.path.join(app.config['PREPROCESSING_REPORT'], dma_ref))
            file.save(export_file)

            proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
            uid = current_user.username
            uid_name = uid.split("@")[0].replace("ELSA2DMA", "-ELSA2DMA")
            proxy.NEOPLMXML(uid_name, dma_ref, dma_rev, request.remote_addr, "0", "-ELSA2DMA-")
            _save_job('ELSA2DMA', fn)
            flash(f'ELSA2DMA job queued: {fn}', 'success')
            return redirect(url_for('ext2dmz_elsa2dma'))
        except Exception as e:
            error = str(e)
    return render_template('ext2dmz_elsa2dma.html', error=error)

@app.route('/ext2dmz_excel2dma', methods=['GET', 'POST'])
@login_required
@check_access
def ext2dmz_excel2dma():
    error = None
    if request.method == 'POST':
        if 'excel2dma_file' not in request.files:
            error = 'No file part in request.'
            return render_template('ext2dmz_excel2dma.html', error=error)
        file = request.files['excel2dma_file']
        if file.filename == '':
            error = 'No file selected.'
            return render_template('ext2dmz_excel2dma.html', error=error)
        try:
            fn = os.path.basename(file.filename)
            if '@' not in fn:
                error = f'Invalid filename "{fn}": must contain "@" separator (e.g. ref@rev@filename).'
                return render_template('ext2dmz_excel2dma.html', error=error)

            dma_ref = time.strftime("%Y%m%d_%H%M%S") + "_NEOPLMXML_" + fn
            dma_rev = ""

            export_file = os.path.normpath(os.path.join(app.config['PREPROCESSING_REPORT'], dma_ref))
            file.save(export_file)

            proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
            uid = current_user.username
            uid_name = uid.split("@")[0].replace("EXCEL2DMA", "-EXCEL2DMA")
            proxy.NEOPLMXML(uid_name, dma_ref, dma_rev, request.remote_addr, "0", "-EXCEL2DMA-")
            _save_job('EXCEL2DMA', fn)
            flash(f'EXCEL2DMA job queued: {fn}', 'success')
            return redirect(url_for('ext2dmz_excel2dma'))
        except Exception as e:
            error = str(e)
    return render_template('ext2dmz_excel2dma.html', error=error)

@app.route('/ext2dmz_elsa2bthtsp', methods=['GET', 'POST'])
@login_required
@check_access
def ext2dmz_elsa2bthtsp():
    error = None
    if request.method == 'POST':
        if 'elsa2bthtsp_file' not in request.files:
            error = 'No file part in request.'
            return render_template('ext2dmz_elsa2bthtsp.html', error=error)
        file = request.files['elsa2bthtsp_file']
        if file.filename == '':
            error = 'No file selected.'
            return render_template('ext2dmz_elsa2bthtsp.html', error=error)
        try:
            fn = os.path.basename(file.filename)
            if '@' not in fn:
                error = f'Invalid filename "{fn}": must contain "@" separator (e.g. ref@rev@filename).'
                return render_template('ext2dmz_elsa2bthtsp.html', error=error)

            dma_ref = time.strftime("%Y%m%d_%H%M%S") + "_NEOPLMXML_" + fn
            dma_rev = ""

            export_file = os.path.normpath(os.path.join(app.config['PREPROCESSING_REPORT'], dma_ref))
            file.save(export_file)

            proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
            uid = current_user.username
            uid_name = uid.split("@")[0].replace("ELSA2BTHTSP", "-ELSA2BTHTSP")
            proxy.NEOPLMXML(uid_name, dma_ref, dma_rev, request.remote_addr, "0", "-ELSA2BTHTSP-")
            _save_job('ELSA2BTHTSP', fn)
            flash(f'ELSA2BTHTSP job queued: {fn}', 'success')
            return redirect(url_for('ext2dmz_elsa2bthtsp'))
        except Exception as e:
            error = str(e)
    return render_template('ext2dmz_elsa2bthtsp.html', error=error)

@app.route('/delta_dma', methods=['GET', 'POST'])
@login_required
@check_access
def delta_dma():
    error = None
    if request.method == 'POST':
        reference_from = request.form.get('reference_from', '').strip()
        reference_to = request.form.get('reference_to', '').strip()

        if not reference_from or not reference_to:
            error = 'Both source and destination references are required.'
            return render_template('delta_dma.html', error=error)

        pattern = re.compile(r'^[^\s/]+/[^\s/]+$')
        for ref in [reference_from, reference_to]:
            if not pattern.match(ref):
                error = 'Use / to separate reference and revision (e.g. AK00000000000/D) with no spaces.'
                return render_template('delta_dma.html', error=error)

        try:
            uid = current_user.username
            full_name = f"{current_user.first_name} {current_user.last_name}"
            job_name = time.strftime("%Y_%m_%d-%H_%M_%S") + "_-DELTA-DMA_" + \
                       reference_from.replace("/", "_") + "-" + reference_to.replace("/", "_")
            working_dir = os.path.join(app.config['SHARE_ALTERNATE_WORKING'], job_name)
            output_path = os.path.join(app.config['SHARE_DELTA'], 'DELTA_DMA')

            payload = {
                "action": "DELTA_DMA",
                "working_dir": working_dir,
                "reference_1": reference_from,
                "working_1": False,
                "reference_2": reference_to,
                "working_2": False,
                "output_path": output_path,
                "language": "EN",
                "name": full_name
            }
            content = f"DELTA-DMA<>{uid}<><><><><>{json.dumps(payload, ensure_ascii=False)}"

            queued_path = os.path.join(app.config['SHARE_SPOOL'], "QUEUED", job_name)
            with open(queued_path, "w") as f:
                f.write(content)

            _save_job('DELTADMA', reference_from, reference_to)
            flash(f'Delta DMA job queued: {reference_from} → {reference_to}', 'success')
            return redirect(url_for('delta_dma'))
        except Exception as e:
            error = str(e)
    return render_template('delta_dma.html', error=error)

@app.route('/delta_tcra', methods=['GET', 'POST'])
@login_required
@check_access
def delta_tcra():
    error = None
    if request.method == 'POST':
        reference_from = request.form.get('reference_from', '').strip()
        reference_to = request.form.get('reference_to', '').strip()
        working_from = True if request.form.get('working_from') else False
        working_to = True if request.form.get('working_to') else False

        if not reference_from or not reference_to:
            error = 'Both source and destination references are required.'
            return render_template('delta_tcra.html', error=error)

        pattern = re.compile(r'^[^\s/]+/[^\s/]+$')
        for ref in [reference_from, reference_to]:
            if not pattern.match(ref):
                error = 'Use / to separate reference and revision (e.g. AK00000000000/D) with no spaces.'
                return render_template('delta_tcra.html', error=error)

        try:
            uid = current_user.username
            full_name = f"{current_user.first_name} {current_user.last_name}"
            job_name = time.strftime("%Y_%m_%d-%H_%M_%S") + "_-DELTA-TCRA_" + \
                       reference_from.replace("/", "_") + "-" + reference_to.replace("/", "_")
            working_dir = os.path.join(app.config['SHARE_ALTERNATE_WORKING'], job_name)
            output_path = os.path.join(app.config['SHARE_DELTA'], 'DELTA_TCRA')

            payload = {
                "action": "DELTA_TCRA",
                "working_dir": working_dir,
                "reference_1": reference_from,
                "working_1": working_from,
                "reference_2": reference_to,
                "working_2": working_to,
                "output_path": output_path,
                "language": "EN",
                "name": full_name
            }
            content = f"DELTA-TCRA<>{uid}<><><><><>{json.dumps(payload, ensure_ascii=False)}"

            queued_path = os.path.join(app.config['SHARE_SPOOL'], "QUEUED", job_name)
            with open(queued_path, "w") as f:
                f.write(content)

            _save_job('DELTATCRA', reference_from, reference_to)
            flash(f'Delta TCRA job queued: {reference_from} → {reference_to}', 'success')
            return redirect(url_for('delta_tcra'))
        except Exception as e:
            error = str(e)
    return render_template('delta_tcra.html', error=error)

def _tcra_check_report_exist(reference, uid):
    tcra_dir = app.config['SHARE_ALTERNATE_WORKING']
    ref_rev = "TCRA_" + reference.replace("/", "_")
    try:
        entries = sorted(os.listdir(tcra_dir), reverse=True)
    except Exception:
        return None
    for entry in entries:
        if ref_rev in entry:
            dir_path = os.path.join(tcra_dir, entry)
            if os.path.isdir(dir_path):
                config_bin = os.path.join(dir_path, 'bin', 'config.bin')
                tcra_dict = os.path.join(dir_path, 'bin', 'tcra.dict')
                if os.path.isfile(config_bin) and os.path.isfile(tcra_dict):
                    try:
                        with open(config_bin, 'r', encoding='latin-1') as f:
                            cfg = json.load(f)
                        if cfg.get('USER_NAME', '').lower() == uid.lower():
                            return dir_path
                    except Exception:
                        continue
    return None

@app.route('/tcra_report', methods=['GET', 'POST'])
@login_required
@check_access
def tcra_report():
    error = None
    if request.method == 'POST':
        submitted_mode = request.form.get('mode', '')
        reference = request.form.get('tcReference', '').strip()

        if submitted_mode == 'CHECK_TC':
            if not reference or '/' not in reference:
                error = 'Use / to separate reference and revision (e.g. AK00000000000/D).'
                return render_template('tcra_report.html', mode='start', error=error)
            uid = current_user.username
            existing_dir = _tcra_check_report_exist(reference, uid)
            if existing_dir:
                existing_date = ''
                try:
                    with open(os.path.join(existing_dir, 'bin', 'config.bin'), 'r', encoding='latin-1') as f:
                        cfg = json.load(f)
                    existing_date = cfg.get('CREATED_ON', '')
                except Exception:
                    pass
                return render_template('tcra_report.html', mode='dir_found',
                                       reference=reference, existing_dir=existing_dir,
                                       existing_date=existing_date)
            else:
                return render_template('tcra_report.html', mode='options', reference=reference)

        elif submitted_mode == 'REGENERATE':
            return render_template('tcra_report.html', mode='options', reference=reference)

        elif submitted_mode == 'RELOAD':
            return redirect(url_for('tcra_report'))

        elif submitted_mode == 'CREATE_TCRA':
            try:
                uid = current_user.username
                full_name = f"{current_user.first_name} {current_user.last_name}"
                ref_rev = reference.replace('/', '_')
                time_stamp = time.strftime("%Y_%m_%d_%H_%M_%S_TCRA_") + ref_rev
                full_path = os.path.join(app.config['SHARE_ALTERNATE_WORKING'], time_stamp)
                end_user_path = os.path.join(app.config['SHARE_TCRA_OUT'], time_stamp)
                os.makedirs(os.path.join(full_path, 'bin'), exist_ok=True)

                dict_config = {
                    'REP_SUBCONTRACTOR': request.form.get('SUBCONTRACTOR', 'NONE'),
                    'REP_MANUFAC': request.form.get('REP_MANUFAC', 'FALSE'),
                    'CREATE_3D': request.form.get('CREATE_3D', 'FALSE'),
                    'DXF_FOLDER': request.form.get('DXF_FOLDER', 'FALSE'),
                    'EBOM_ONLY': request.form.get('EBOM_ONLY', 'FALSE'),
                    'LIST_DOCS': request.form.get('LIST_DOCS', 'FALSE'),
                    'PART_LIST': request.form.get('PART_LIST', 'FALSE'),
                    'REF_REV': reference,
                    'REMOVE_CI': request.form.get('REMOVE_CI', 'FALSE'),
                    'REMOVE_MAKE_BUY': request.form.get('REMOVE_MAKE_BUY', 'FALSE'),
                    'SEL_TT_CI': request.form.get('SEL_TT_CI', 'TT'),
                    'LEVEL_NODES': request.form.get('LEVEL_NODES', '*'),
                    'TREE_EDIT': request.form.get('TREE_EDIT', 'FALSE'),
                    'UNZIP_FILES': request.form.get('UNZIP_FILES', 'FALSE'),
                    'FULL_PATH': full_path,
                    'END_USER_PATH': end_user_path,
                    'CREATED_ON': time.strftime("%d/%m/%Y %H:%M:%S"),
                    'USER_NAME': uid,
                    'FULL_NAME': full_name,
                    'LANGUAGE': 'EN',
                    'PROJECT_NAME': request.form.get('PROJECT_NAME', ''),
                    'REPORT_PATH': full_path + '/bin/report',
                    'TTBOM': request.form.get('TTBOM', 'FALSE'),
                    'EXPAND_MBOM_BUY_TREE': request.form.get('EXPAND_MBOM_BUY_TREE', 'FALSE'),
                    'NO_CLIENT_PLAN': request.form.get('NO_CLIENT_PLAN', 'FALSE'),
                }
                with open(os.path.join(full_path, 'bin', 'config.bin'), 'w', encoding='latin-1') as f:
                    json.dump(dict_config, f, ensure_ascii=False, indent=4)

                job_mode = 'BIN' if dict_config['TREE_EDIT'] == 'TRUE' else 'TOTAL'
                config_file_name = time_stamp + '.txt'
                job_path = os.path.join(app.config['PREPROCESSING_REPORT'], config_file_name)
                with open(job_path, 'w', encoding='latin-1') as f:
                    json.dump({'fullPath': full_path, 'MODE': job_mode}, f, ensure_ascii=False, indent=4)

                proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
                proxy.TCRAREPORT(uid, config_file_name, "None", request.remote_addr, "0", "-")
                _save_job('TCRAREPORT', reference)
                flash(f'TCRA report job queued: {reference}', 'success')
                return redirect(url_for('tcra_report'))
            except Exception as e:
                error = str(e)
                return render_template('tcra_report.html', mode='options', reference=reference, error=error)

        elif submitted_mode == 'COMPLETE_REPORTS':
            existing_dir = request.form.get('dir', '')
            try:
                config_bin_path = os.path.join(existing_dir, 'bin', 'config.bin')
                with open(config_bin_path, 'r', encoding='latin-1') as f:
                    dict_config = json.load(f)
                full_path = dict_config['FULL_PATH']
                ref_rev = reference.replace('/', '_')
                time_stamp = time.strftime("%Y_%m_%d_%H_%M_%S_TCRA_") + ref_rev
                dict_config['END_USER_PATH'] = os.path.join(app.config['SHARE_TCRA_OUT'], time_stamp)
                dict_config['CREATED_ON'] = time.strftime("%d/%m/%Y %H:%M:%S")
                with open(config_bin_path, 'w', encoding='latin-1') as f:
                    json.dump(dict_config, f, ensure_ascii=False, indent=4)

                config_file_name = os.path.basename(full_path) + '.txt'
                job_path = os.path.join(app.config['PREPROCESSING_REPORT'], config_file_name)
                with open(job_path, 'w', encoding='latin-1') as f:
                    json.dump({'fullPath': full_path, 'MODE': 'REPORT'}, f, ensure_ascii=False, indent=4)

                uid = current_user.username
                proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
                proxy.TCRAREPORT(uid, config_file_name, "None", request.remote_addr, "0", "-")
                _save_job('TCRAREPORT', reference)
                flash(f'TCRA complete reports job queued: {reference}', 'success')
                return redirect(url_for('tcra_report'))
            except Exception as e:
                error = str(e)
                return render_template('tcra_report.html', mode='start', error=error)

    return render_template('tcra_report.html', mode='start', error=error)

@app.route('/tcra_delta_check', methods=['GET', 'POST'])
@login_required
@check_access
def tcra_delta_check():
    error = None
    if request.method == 'POST':
        file_from = request.files.get('fileTCRA_from')
        select_to = request.form.get('select_to', '')
        file_to = request.files.get('fileTCRA_to')
        reference_to = request.form.get('tcReference_to', '').strip()

        # Validate source
        if not file_from or file_from.filename == '':
            error = 'Source TCRA file not loaded.'
            return render_template('tcra_delta_check.html', error=error)
        name_from = os.path.basename(file_from.filename)
        conf_file_from = name_from
        conf_ref_from = ''

        # Validate destination
        if select_to == 'FILE':
            if not file_to or file_to.filename == '':
                error = 'Destination TCRA file not loaded.'
                return render_template('tcra_delta_check.html', error=error)
            name_to = os.path.basename(file_to.filename)
            conf_file_to = name_to
            conf_ref_to = ''
            if name_from == name_to:
                error = 'TCRA source and destination cannot be identical.'
                return render_template('tcra_delta_check.html', error=error)
        elif select_to == 'REFERENCE':
            if not reference_to or '/' not in reference_to:
                error = 'Use / to separate reference and revision (e.g. AK00000000000/D).'
                return render_template('tcra_delta_check.html', error=error)
            name_to = reference_to
            conf_file_to = ''
            conf_ref_to = reference_to
        else:
            error = 'Please select a destination type.'
            return render_template('tcra_delta_check.html', error=error)

        try:
            uid = current_user.username
            full_name = f"{current_user.first_name} {current_user.last_name}"
            delta_ref = f"{name_from.replace('/', '_')}-{name_to.replace('/', '_')}"
            time_stamp = time.strftime("%Y_%m_%d_%H_%M_%S_TCRA_") + delta_ref
            full_path = os.path.join(app.config['SHARE_ALTERNATE_WORKING'], time_stamp)
            end_user_path = os.path.join(app.config['SHARE_DELTA_TCRA_OUT'], time_stamp)
            os.makedirs(os.path.join(full_path, 'bin'), exist_ok=True)

            dict_config = {
                'REF_REV': delta_ref,
                'FULL_PATH': full_path,
                'END_USER_PATH': end_user_path,
                'CREATED_ON': time.strftime("%d/%m/%Y %H:%M:%S"),
                'USER_NAME': uid,
                'FULL_NAME': full_name,
                'LANGUAGE': 'EN',
                'FILE_FROM': conf_file_from,
                'FILE_TO': conf_file_to,
                'REF_FROM': conf_ref_from,
                'REF_TO': conf_ref_to,
            }
            with open(os.path.join(full_path, 'bin', 'config.bin'), 'w', encoding='latin-1') as f:
                json.dump(dict_config, f, ensure_ascii=False, indent=4)

            if conf_file_from:
                file_from.save(os.path.join(full_path, conf_file_from))
            if conf_file_to:
                file_to.save(os.path.join(full_path, conf_file_to))

            config_file_name = time_stamp + '.txt'
            job_path = os.path.join(app.config['PREPROCESSING_REPORT'], config_file_name)
            with open(job_path, 'w', encoding='latin-1') as f:
                json.dump({'fullPath': full_path, 'MODE': 'DELTA'}, f, ensure_ascii=False, indent=4)

            proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
            proxy.TCRAREPORT(uid, config_file_name, "None", request.remote_addr, "0", "-")
            _save_job('TCRADELTA', name_from, name_to)
            flash(f'TCRA delta check job queued: {name_from} → {name_to}', 'success')
            return redirect(url_for('tcra_delta_check'))
        except Exception as e:
            error = str(e)

    return render_template('tcra_delta_check.html', error=error)

@app.route('/tcra_delta_dma_check', methods=['GET', 'POST'])
@login_required
@check_access
def tcra_delta_dma_check():
    error = None
    if request.method == 'POST':
        select_from = request.form.get('select_from', '')
        reference_from = request.form.get('tcReference_from', '').strip()
        reference_date = request.form.get('tcReference_date', '').strip()
        file_from = request.files.get('fileTCRA_from')
        reference_dma = request.form.get('dmaReference_from', '').strip()

        # Validate DMA destination (always required)
        if not reference_dma or '/' not in reference_dma or len(reference_dma.split('/')) != 2 or reference_dma.split('/')[1] == '':
            error = 'Use / to separate DMA reference and revision (e.g. AK00000000000/D).'
            return render_template('tcra_delta_dma_check.html', error=error)

        dma_ref = reference_dma.split('/')[0]
        dma_rev = reference_dma.split('/')[1]

        if select_from == 'REFERENCE':
            if not reference_from or '/' not in reference_from or len(reference_from.split('/')) != 2 or reference_from.split('/')[1] == '':
                error = 'Use / to separate TC reference and revision (e.g. AK00000000000/D).'
                return render_template('tcra_delta_dma_check.html', error=error)
            if not reference_date:
                error = 'Please enter a valid date.'
                return render_template('tcra_delta_dma_check.html', error=error)
            ref_tc = reference_from.replace('/', '_')
            delta_reference = f"DMA_{ref_tc}_{dma_rev}"
            conf_file_from = ''
        elif select_from == 'FILE':
            if not file_from or file_from.filename == '':
                error = 'Source TCRA file not loaded.'
                return render_template('tcra_delta_dma_check.html', error=error)
            tcra_stem = os.path.splitext(os.path.basename(file_from.filename))[0]
            dma_name = reference_dma.replace('/', '_').strip()
            delta_reference = f"DMA_{tcra_stem}_{dma_name}"
            conf_file_from = os.path.basename(file_from.filename)
        else:
            error = 'Please select a source type.'
            return render_template('tcra_delta_dma_check.html', error=error)

        try:
            uid = current_user.username
            full_name = f"{current_user.first_name} {current_user.last_name}"
            time_stamp = time.strftime("%Y_%m_%d_%H_%M_%S_TCRA_") + delta_reference
            full_path = os.path.join(app.config['SHARE_ALTERNATE_WORKING'], time_stamp)
            end_user_path = os.path.join(app.config['SHARE_DELTA_TCRA_DMA_OUT'], time_stamp)
            os.makedirs(os.path.join(full_path, 'bin'), exist_ok=True)

            params = {
                'TCITEMD': '',
                'TCREV': '',
                'TCDATE': '',
                'DMAREF': dma_ref,
                'DMAREV': dma_rev,
                'FULL_PATH': full_path,
                'END_USER_PATH': end_user_path,
                'USER_NAME': uid,
                'FULL_NAME': full_name,
                'LANGUAGE': 'EN',
            }

            if select_from == 'FILE':
                file_from.save(os.path.join(full_path, conf_file_from))
                params['TCITEMD'] = f'TCRA:{conf_file_from}'
            else:
                params['TCITEMD'] = reference_from.split('/')[0]
                params['TCREV'] = reference_from.split('/')[1]
                params['TCDATE'] = reference_date

            with open(os.path.join(full_path, 'bin', 'params_delta.txt'), 'w', encoding='latin-1') as f:
                json.dump(params, f, ensure_ascii=False, indent=4)

            config_file_name = time_stamp + '.txt'
            job_path = os.path.join(app.config['PREPROCESSING_REPORT'], config_file_name)
            with open(job_path, 'w', encoding='latin-1') as f:
                json.dump({'fullPath': full_path, 'MODE': 'DELTA'}, f, ensure_ascii=False, indent=4)

            py_script = app.config['PY_DELTA_4_INDUS']
            os.system(f'start cmd /c "title DELTA4INDUS & python.exe {py_script} {full_path}"')

            _save_job('TCRADELTADMA', delta_reference)
            flash(f'TCRA delta DMA check launched: {delta_reference}', 'success')
            return redirect(url_for('tcra_delta_dma_check'))
        except Exception as e:
            error = str(e)

    return render_template('tcra_delta_dma_check.html', error=error)

@app.route('/tcra_delta_eng_check', methods=['GET', 'POST'])
@login_required
@check_access
def tcra_delta_eng_check():
    error = None
    if request.method == 'POST':
        reference_from = request.form.get('tcReference_from', '').strip()
        reference_date = request.form.get('tcReference_date', '').strip()
        reference2_from = request.form.get('tcReference2_from', '').strip()
        reference2_date = request.form.get('tcReference2_date', '').strip()
        include_specs = request.form.get('REP_SPECS', 'NO')
        include_refs = request.form.get('REP_REFS', 'NO')

        for ref in [reference_from, reference2_from]:
            if not ref or '/' not in ref or len(ref.split('/')) != 2 or ref.split('/')[1] == '':
                error = 'Use / to separate reference and revision (e.g. AK00000000000/D).'
                return render_template('tcra_delta_eng_check.html', error=error)

        if not reference_date or not reference2_date:
            error = 'Please enter a valid date for both source and destination.'
            return render_template('tcra_delta_eng_check.html', error=error)

        try:
            uid = current_user.username
            full_name = f"{current_user.first_name} {current_user.last_name}"
            ref_tc = reference_from.replace('/', '_')
            rev_to = reference2_from.split('/')[1]
            delta_reference = f"ENG_{ref_tc}_{rev_to}"
            time_stamp = time.strftime("%Y_%m_%d_%H_%M_%S_TCRA_") + delta_reference
            full_path = os.path.join(app.config['SHARE_ALTERNATE_WORKING'], time_stamp)
            end_user_path = os.path.join(app.config['SHARE_DELTA_TCRA_ENG_OUT'], time_stamp)
            os.makedirs(os.path.join(full_path, 'bin'), exist_ok=True)

            params = {
                'TCITEMD1': reference_from.split('/')[0],
                'TCREV1': reference_from.split('/')[1],
                'TCDATE1': reference_date,
                'TCITEMD2': reference2_from.split('/')[0],
                'TCREV2': reference2_from.split('/')[1],
                'TCDATE2': reference2_date,
                'SPECS': include_specs,
                'REFS': include_refs,
                'FULL_PATH': full_path,
                'END_USER_PATH': end_user_path,
                'USER_NAME': uid,
                'FULL_NAME': full_name,
                'LANGUAGE': 'EN',
            }
            with open(os.path.join(full_path, 'bin', 'params_delta.txt'), 'w', encoding='latin-1') as f:
                json.dump(params, f, ensure_ascii=False, indent=4)

            config_file_name = time_stamp + '.txt'
            job_path = os.path.join(app.config['PREPROCESSING_REPORT'], config_file_name)
            with open(job_path, 'w', encoding='latin-1') as f:
                json.dump({'fullPath': full_path, 'MODE': 'DELTA'}, f, ensure_ascii=False, indent=4)

            exe = app.config['EXE_DELTATCENG']
            subprocess.Popen([exe, full_path], close_fds=True,
                             creationflags=0x00000200 | 0x00000010)

            _save_job('TCRADELTAENG', delta_reference)
            flash(f'TCRA delta ENG check launched: {delta_reference}', 'success')
            return redirect(url_for('tcra_delta_eng_check'))
        except Exception as e:
            error = str(e)

    return render_template('tcra_delta_eng_check.html', error=error)

@app.route('/request_queued')
@login_required
@check_access
def request_queued():
    jobs = []
    error = None
    try:
        proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
        new = proxy.LISTREQUEST("QUEUED", "ALL", "toto")
        t = ET.fromstring(new)
        lines = list(t)[0].findall('line')
        uid = current_user.username
        for x in reversed(lines):
            if x.get('owner') == uid:
                jobs.append(strip_site_from_job(x.get('value')))
    except Exception as e:
        error = str(e)
    return render_template('request_queued.html', jobs=jobs, error=error)

@app.route('/request_completed')
@login_required
@check_access
def request_completed():
    # Current user's completed jobs — mirrors /t7 in original
    jobs = []
    error = None
    try:
        proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
        new = proxy.LISTREQUEST("COMPLETED", "ALL", "toto")
        t = ET.fromstring(new)
        lines = list(t)[0].findall('line')
        uid = current_user.username
        for x in reversed(lines):
            if x.get('owner') == uid:
                jobs.append(strip_site_from_job(x.get('value')))
    except Exception as e:
        error = str(e)
    return render_template('request_completed.html', jobs=jobs, error=error)

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
            jobs.append(strip_site_from_job(x.get('value')) + " (" + x.get('owner') + ")")
    except Exception as e:
        error = str(e)
    return render_template('request_all_completed.html', jobs=jobs, error=error)

@app.route('/request_failed')
@login_required
@check_access
def request_failed():
    # Current user's failed jobs — mirrors /t8 in original
    jobs = []
    error = None
    try:
        proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
        new = proxy.LISTREQUEST("FAILED", "ALL", "toto")
        t = ET.fromstring(new)
        lines = list(t)[0].findall('line')
        uid = current_user.username
        for x in reversed(lines):
            if x.get('owner') == uid:
                jobs.append(strip_site_from_job(x.get('value')))
    except Exception as e:
        error = str(e)
    return render_template('request_failed.html', jobs=jobs, error=error)

@app.route('/request_running')
@login_required
@check_access
def request_running():
    # Current user's running jobs — mirrors /t6 in original
    jobs = []
    error = None
    try:
        proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
        new = proxy.LISTREQUEST("RUNNING", "ALL", "toto")
        t = ET.fromstring(new)
        lines = list(t)[0].findall('line')
        uid = current_user.username
        for x in reversed(lines):
            if x.get('owner') == uid:
                jobs.append(strip_site_from_job(x.get('value')))
    except Exception as e:
        error = str(e)
    return render_template('request_running.html', jobs=jobs, error=error)

@app.route('/request_all_failed')
@login_required
@admin_required
def request_all_failed():
    # All users' failed jobs — mirrors /r8 in original (admin only)
    jobs = []
    error = None
    try:
        proxy = xmlrpc.client.ServerProxy(app.config['PROXY_QUERY'])
        new = proxy.LISTREQUEST("FAILED", "ALL", "toto")
        t = ET.fromstring(new)
        lines = list(t)[0].findall('line')
        for x in reversed(lines):
            jobs.append(strip_site_from_job(x.get('value')) + " (" + x.get('owner') + ")")
    except Exception as e:
        error = str(e)
    return render_template('request_all_failed.html', jobs=jobs, error=error)

@app.route('/job_report')
@login_required
def job_report():
    from pathlib import Path

    job_name = request.args.get('job', '').strip()
    queue_type = request.args.get('queue', 'COMPLETED').upper()

    if not job_name:
        return render_template('job_report.html', error='No job name provided.')

    # Strip " (owner)" suffix that admin list views append
    paren = job_name.find(' (')
    if paren > 0:
        job_name = job_name[:paren]

    # Read spool file for request metadata
    reqtype = job_name
    reqowner = ''
    config_preprocessing = ''
    try:
        spool_file = os.path.join(app.config['SHARE_SPOOL'], queue_type, job_name)
        with open(spool_file, 'r', encoding='latin-1') as f:
            reqparams = f.readline().split('<>')
            reqtype            = reqparams[0] if len(reqparams) > 0 else job_name
            reqowner           = reqparams[1] if len(reqparams) > 1 else ''
            config_preprocessing = reqparams[2] if len(reqparams) > 2 else ''
    except Exception:
        pass

    # Search for Process.log across working directories and fallback strategies
    path_process = None
    for working in [app.config.get('SHARE_STANDARD_WORKING', ''),
                    app.config.get('SHARE_ALTERNATE_WORKING', '')]:
        if not working:
            continue

        # Strategy 1: {working}/{job_name}/Process.log
        p = Path(working) / job_name / 'Process.log'
        if p.exists():
            path_process = p
            break

        # Strategy 2: {working}/{configPreprocessing}/Process.log
        if config_preprocessing:
            p = Path(working) / config_preprocessing / 'Process.log'
            if p.exists():
                path_process = p
                break

        # Strategy 3: {working}/{job_name}/{job_name}.path → follow the path
        path_file = Path(working) / job_name / (job_name + '.path')
        if path_file.exists():
            try:
                with open(path_file, 'r', encoding='latin-1') as f:
                    stored = Path(f.readline().strip())
                p = stored.parent / 'Process.log'
                if p.exists():
                    path_process = p
                    break
            except Exception:
                pass

        # Strategy 4: walk subdirs of {working}/{job_name} for configPreprocessing
        if config_preprocessing:
            root_dir = Path(working) / job_name
            if root_dir.exists():
                try:
                    for _, dirs, _ in os.walk(str(root_dir)):
                        for d in dirs:
                            if config_preprocessing in d:
                                p = root_dir / d / 'Process.log'
                                if p.exists():
                                    path_process = p
                                break
                        break
                except Exception:
                    pass
        if path_process:
            break

    if path_process is None or not path_process.exists():
        return render_template('job_report.html',
                               job_name=job_name,
                               queue_type=queue_type,
                               reqtype=reqtype,
                               reqowner=reqowner,
                               error='Process.log not found for this job.')

    try:
        with open(path_process, 'r', encoding='latin-1') as f:
            log_lines = f.read().splitlines()
        time_log = time.strftime('%d/%m/%Y %H:%M:%S',
                                 time.localtime(os.path.getctime(str(path_process))))
        report_title = reqtype.split('-')[0] + ' Report'
        full_path_log = str(path_process) if current_user.is_admin else None
    except Exception as e:
        return render_template('job_report.html',
                               job_name=job_name,
                               queue_type=queue_type,
                               reqtype=reqtype,
                               reqowner=reqowner,
                               error=f'Error reading log: {e}')

    return render_template('job_report.html',
                           job_name=job_name,
                           queue_type=queue_type,
                           report_title=report_title,
                           reqtype=reqtype,
                           reqowner=reqowner,
                           time_log=time_log,
                           log_lines=log_lines,
                           total_lines=len(log_lines),
                           full_path_log=full_path_log)


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
            'request_queued', 'request_running', 'request_completed', 'request_all_completed', 'request_failed', 'request_all_failed'
        ]
        
        for endpoint in endpoints:
            if not Page.query.filter_by(endpoint=endpoint).first():
                # specific name formatting
                name = endpoint.replace('_', ' ').title()
                db.session.add(Page(name=name, endpoint=endpoint))
        db.session.commit()
    app.run(debug=True)
