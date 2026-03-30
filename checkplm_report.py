"""
Port of the ExportTool t12 treeview logic.
Processes dictinfo_pickled.bin and generates HTML for the CheckPLMXML treeview report.
"""
import sqlite3
import pickle
import os
from pathlib import Path


# ──────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────

def open_db(db_path):
    """Open SQLite DB; return connection or None."""
    try:
        if db_path and os.path.exists(db_path):
            return sqlite3.connect(db_path, check_same_thread=False)
    except Exception:
        pass
    return None


def get_message(conn, message_id, language='EN'):
    """Look up a UI label from MESSAGES_DEFINITION. Falls back to message_id."""
    if conn is None:
        return message_id
    col = 'MESSAGE_EN' if language != 'FR' else 'MESSAGE_FR'
    try:
        cur = conn.execute(f"SELECT {col} FROM MESSAGES_DEFINITION WHERE MESSAGE_ID=?", (message_id,))
        row = cur.fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return message_id


def get_error_definition(conn, error_id, process, subprocess, type_error, language='EN'):
    """Look up an error definition. Returns (row_dict, message_str)."""
    if conn is None:
        return None, error_id
    col = 'ERROR_EN' if language != 'FR' else 'ERROR_FR'
    try:
        cur = conn.execute(
            f"""SELECT {col}, TEMPLATE_VAR, POSTCODE
                FROM ERRORS_DEFINITION
                WHERE ERROR_ID=? AND PROCESS=? AND SUBPROCESS=? AND TYPE_{type_error}=1
                LIMIT 1""",
            (error_id, process, subprocess)
        )
        row = cur.fetchone()
        if row and row[0]:
            return row, row[0]
    except Exception:
        pass
    return None, error_id


# ──────────────────────────────────────────────
# Pickle + path resolution
# ──────────────────────────────────────────────

def _read_path_file(path_file, base):
    """
    Read a .path file and return the pickle path.
    Mirrors the original t12 logic:
      - strip drive letter → /PBS_CRL.working/folder
      - if UNC (//…): use directly
      - else: base_parent + stripped_path + /build/dictinfo_pickled.bin
    base is SHARE_STANDARD_WORKING which already includes PBS_CRL.working,
    so base_parent = Path(base).parent = …/DMAEXPORTTOOL (≡ PROXY_PATH_FOR_PICKLE_1).
    Returns Path or None.
    """
    try:
        with open(path_file, encoding='latin-1') as f:
            my_path = f.readline().strip().replace('\\', '/')
        slash = my_path.find('/')
        if slash < 0:
            return None
        my_path = my_path[slash:]          # strip drive letter → /PBS_CRL.working/folder
        if my_path.startswith('//'):
            return Path(my_path) / 'build' / 'dictinfo_pickled.bin'
        # Reconstruct UNC via parent of base (= PROXY_PATH_FOR_PICKLE_1)
        pickle_path = Path(base).parent / my_path.lstrip('/') / 'build' / 'dictinfo_pickled.bin'
        return pickle_path
    except Exception:
        return None


def find_pickle(job_name, standard_working, alternate_working):
    """
    Find dictinfo_pickled.bin for a completed CHECKPLMXML job.
    Mirrors the original display_check_plm logic exactly.
    Returns (path_to_pickle, error_string).
    """
    tried = []

    for base in [standard_working, alternate_working]:
        if not base:
            continue

        # ── Strategy 1: exact .path file (mirrors original t12) ─────────────
        # Original: req_path = PROXY_PATH_FOR_PICKLE_1 + /PBS_CRL.working/{job_name}
        #           fileCheckPath = req_path/{job_name}.path
        # Equivalent: {SHARE_STANDARD_WORKING}/{job_name}/{job_name}.path
        for job_dir in [Path(base) / job_name,
                        Path(base) / 'working' / job_name]:
            path_file = job_dir / (job_name + '.path')
            tried.append(str(path_file))
            if path_file.exists():
                pickle_path = _read_path_file(path_file, base)
                if pickle_path and pickle_path.exists():
                    return pickle_path, None
                # .path found but pickle not there — try direct build/ too
                direct = job_dir / 'build' / 'dictinfo_pickled.bin'
                tried.append(str(direct))
                if direct.exists():
                    return direct, None

        # ── Strategy 2: direct build/ (no .path needed) ──────────────────────
        direct = Path(base) / job_name / 'build' / 'dictinfo_pickled.bin'
        tried.append(str(direct))
        if direct.exists():
            return direct, None

        # ── Strategy 3: glob — handles stripped/display name ─────────────────
        # Extract timestamp prefix and ref/rev from job_name so we can locate
        # the actual raw-named directory even when the job name was stripped.
        import re as _re
        m = _re.match(r'(\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}_)', job_name)
        if m:
            ts = m.group(1)
            try:
                for d in Path(base).iterdir():
                    if not d.is_dir():
                        continue
                    dname = d.name
                    if not dname.startswith(ts):
                        continue
                    # Check if the ref part of job_name appears in this dir name
                    ref_part = job_name.split('-')[-2] if job_name.count('-') >= 2 else ''
                    if ref_part and ref_part not in dname:
                        continue
                    path_file = d / (dname + '.path')
                    if path_file.exists():
                        pickle_path = _read_path_file(path_file, base)
                        if pickle_path and pickle_path.exists():
                            return pickle_path, None
                    direct = d / 'build' / 'dictinfo_pickled.bin'
                    if direct.exists():
                        return direct, None
            except Exception:
                pass

    return None, 'dictinfo_pickled.bin not found (tried: ' + '; '.join(tried[:6]) + ')'


def load_pickle(pickle_path):
    """Load and return the pickle dict, or raise."""
    with open(pickle_path, 'rb') as f:
        return pickle.load(f)


# ──────────────────────────────────────────────
# Part processing  (port of traitements_msg_trace)
# ──────────────────────────────────────────────

_LIST_TO_NOT_DISPLAY = {
    'ZEROCOMPUTEDMASS', 'MISSINGMAT', 'WRONGTREATCORRECTED',
    'NOTRELEASED', 'NOTRELEASED-PROTOTYPE', 'NOT_RELEASED_COMPONENT',
    'WRONGMAT', 'WRONGTREAT'
}

_PRIORITY = [
    {'TYPE_ERROR': 'FATAL',   'COLOUR': 'red',    'INDEX': 0},
    {'TYPE_ERROR': 'WARNING', 'COLOUR': 'orange',  'INDEX': 1},
    {'TYPE_ERROR': 'INFO',    'COLOUR': 'blue',    'INDEX': 2},
]


def process_parts(parts_dict, process, subprocess, conn, language='EN'):
    """
    Iterate parts, classify errors as FATAL/WARNING/INFO,
    build the collapsible tree HTML and populate category lists.
    """
    nomass, notag, nomaterial, noreleased, wrongmat, wrongtreat = [], [], [], [], [], []
    part_list_fatal, part_list_warning, part_list_info = [], [], []

    output_html = ''

    for part_dict in parts_dict:
        header_html = None
        part_number = ''

        for p in _PRIORITY:
            type_error = p['TYPE_ERROR']
            colour     = p['COLOUR']
            index      = p['INDEX']
            grouped    = ''

            try:
                errors = part_dict.trace[type_error]
            except (AttributeError, KeyError):
                continue

            for error_dict in errors:
                error_id    = error_dict[0]
                part_number = part_dict.S_PART_NUMBER

                # Populate category side-tables (mirrors postcode logic)
                if error_id not in _LIST_TO_NOT_DISPLAY:
                    lst = {'FATAL': part_list_fatal,
                           'WARNING': part_list_warning,
                           'INFO': part_list_info}[type_error]
                    if part_number not in lst:
                        lst.append(part_number)

                # Populate filter-button lists from error_id
                _populate_category(error_id, error_dict,
                                   nomass, notag, nomaterial,
                                   noreleased, wrongmat, wrongtreat)

                # Get human-readable message from DB (falls back to error_id)
                _, msg = get_error_definition(conn, error_id, process, subprocess,
                                              type_error, language)
                grouped += f'<li>{error_id}: {msg}</li>\n'
                grouped += '<li><b>' + '-' * 60 + '</b></li>\n'

            if grouped:
                if header_html is None:
                    desc  = getattr(part_dict, 'PART_DESCRIPTION', '')
                    atype = getattr(part_dict, 'A_TYPE', '')
                    rev   = getattr(part_dict, 'C_PART_VERSION', '')
                    header_html = (
                        f"<a id='{part_number}'></a>"
                        f"<input type='checkbox' checked='checked' id='{part_number}' />"
                        f"<label for='{part_number}'>"
                        f"<font color='{colour}'><b>{part_number} {desc} ({atype} REV:{rev})</b></font>"
                        f"</label>"
                    )
                    output_html += '<li>' + header_html + '<ul>'

                sub_id = f'{part_number}-{index}'
                header2 = (
                    f"<input type='checkbox' checked='checked' id='{sub_id}' />"
                    f"<label for='{sub_id}'>{type_error}</label>"
                )
                output_html += '<ul>\n'
                output_html += f'\t<li>{header2}\n'
                output_html += f'\t\t<ul>{grouped}</ul></li>\n'
                output_html += '</ul>\n'

        output_html += '</ul>\n'

    return output_html, {
        'nomaterial':      sorted(set(nomaterial)),
        'noreleased':      sorted(set(noreleased)),
        'nomass':          sorted(set(nomass)),
        'notag':           sorted(set(notag)),
        'wrongmat':        sorted(set(wrongmat)),
        'wrongtreat':      sorted(set(wrongtreat)),
        'part_list_fatal':   part_list_fatal,
        'part_list_warning': part_list_warning,
        'part_list_info':    part_list_info,
    }


def _populate_category(error_id, error_dict,
                        nomass, notag, nomaterial,
                        noreleased, wrongmat, wrongtreat):
    """Populate filter-button lists based on error_id (mirrors DB POSTCODE logic)."""
    mapping = {
        'NOMASS':         nomass,
        'ZEROCOMPUTEDMASS': nomass,
        'NOTAG':          notag,
        'MISSINGMAT':     nomaterial,
        'NOMATERIAL':     nomaterial,
        'NOTRELEASED':    noreleased,
        'NOTRELEASED-PROTOTYPE': noreleased,
        'NOT_RELEASED_COMPONENT': noreleased,
        'WRONGMAT':       wrongmat,
        'WRONGTREAT':     wrongtreat,
        'WRONGTREATCORRECTED': wrongtreat,
    }
    lst = mapping.get(error_id)
    if lst is not None:
        val = error_dict[1] if len(error_dict) > 1 else error_id
        if val not in lst:
            lst.append(val)


# ──────────────────────────────────────────────
# PPL (Parts per Level) processing
# ──────────────────────────────────────────────

def process_ppl(pickle_treat, conn, language):
    """Build PPL table rows and KPI rows."""
    ppl_rows = []
    ppl_kpi  = []

    try:
        yes = get_message(conn, '_INTERNAL_YES', language)
        no  = get_message(conn, '_INTERNAL_NO',  language)

        data_not_std = pickle_treat['PPL']['NOT_STD']
        for s, v in data_not_std.items():
            ppl_rows.append(f'<tr><td>{s}</td><td>{v}</td><td>{no}</td></tr>')
        n_not_std = len(data_not_std)

        data_std = pickle_treat['PPL']['STD']
        for s, v in data_std.items():
            ppl_rows.append(f'<tr><td>{s}</td><td>{v}</td><td>{yes}</td></tr>')
        n_std = len(data_std)

        total = n_not_std + n_std
        lbl_ns  = get_message(conn, '_INTERNAL_TREEVIEW_QUANTY_NO_STD', language)
        lbl_s   = get_message(conn, '_INTERNAL_TREEVIEW_QUANTY_STD',    language)
        lbl_tot = get_message(conn, '_INTERNAL_TREEVIEW_totalofParts',   language)

        if total:
            ppl_kpi.append(f'<tr><td>{lbl_ns}</td><td>{n_not_std}</td><td>{n_not_std/total*100:.1f}%</td></tr>')
            ppl_kpi.append(f'<tr><td>{lbl_s}</td><td>{n_std}</td><td>{n_std/total*100:.1f}%</td></tr>')
        ppl_kpi.append(f'<tr><td>{lbl_tot}</td><td>{total}</td><td></td></tr>')
    except Exception:
        pass

    return ppl_rows, ppl_kpi


# ──────────────────────────────────────────────
# Format part lists for table rows (port of format_part_lists)
# ──────────────────────────────────────────────

def format_part_list(parts):
    """Convert a list of part numbers into clickable table rows."""
    return [
        f"<tr id='{p}' onclick='jumpTo(\"{p}\")'><td>{p}</td></tr>"
        for p in parts
    ]
