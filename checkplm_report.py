"""
Port of the ExportTool t12 treeview logic.
Processes dictinfo_pickled.bin and generates HTML for the CheckPLMXML treeview report.
"""
import sqlite3
import pickle
import os
from pathlib import Path


# ──────────────────────────────────────────────
# Pickle compatibility
# ──────────────────────────────────────────────

class _PartStub:
    """Minimal stub that accepts any attribute assignment during unpickling."""
    def __setstate__(self, state):
        self.__dict__.update(state)


class _CompatUnpickler(pickle.Unpickler):
    """
    Map all ExportTool classes to _PartStub so dictinfo_pickled.bin loads
    without cx_Oracle, pyramid, win32net, etc.
    Classes defined in __main__, classes_pickle, or index are all redirected.
    Any other unknown class is also stubbed rather than raising AttributeError.
    """
    _EXPORTTOOL_MODULES = {'__main__', 'classes_pickle', 'index'}

    def find_class(self, module, name):
        if module in self._EXPORTTOOL_MODULES:
            return _PartStub
        try:
            return super().find_class(module, name)
        except (AttributeError, ModuleNotFoundError):
            return _PartStub


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

def _follow_path_file(file_check_path, pickle_1):
    """
    Read a .path file and return the pickle path.
    Exact port of original display_check_plm logic:
      my_path = first line with drive letter stripped
      if UNC (starts //) → my_path + /build/dictinfo_pickled.bin
      else               → PROXY_PATH_FOR_PICKLE_1 + my_path + /build/dictinfo_pickled.bin
    Returns Path or None.
    """
    try:
        with open(file_check_path, encoding='latin-1') as f:
            my_path = f.readline().strip()
        slash = my_path.find('/')
        if slash < 0:
            return None
        my_path = my_path[slash:]   # strip drive letter e.g. "B:" → "/PBS_CRL.working/job"
        if my_path.startswith('//'):
            return Path(my_path) / 'build' / 'dictinfo_pickled.bin'
        return Path(pickle_1 + my_path) / 'build' / 'dictinfo_pickled.bin'
    except Exception:
        return None


def find_pickle(job_name, pickle_1, pickle_2):
    """
    Find dictinfo_pickled.bin — exact port of original display_check_plm 3-strategy search.
    pickle_1 = PROXY_PATH_FOR_PICKLE_1  (e.g. //naspoc3d…/DMAEXPORTTOOL)
    pickle_2 = PROXY_PATH_FOR_PICKLE_2  (e.g. //nasbobcat/bobcat/data)
    Returns (path_to_pickle, error_string).
    """
    # pth mirrors original: reportfolder "B:/PBS_CRL.working/{job_name}"
    #   → pth = "/PBS_CRL.working/{job_name}"
    pth = '/PBS_CRL.working/' + job_name
    curr_request = job_name
    tried = []

    # Strategy 1 — PROXY_PATH_FOR_PICKLE_1 + pth
    if pickle_1:
        req_path = pickle_1 + pth
        file_check = req_path + '/' + curr_request + '.path'
        tried.append(file_check)
        if os.path.isfile(file_check):
            pickle_path = _follow_path_file(file_check, pickle_1)
            if pickle_path and pickle_path.exists():
                return pickle_path, None

    # Strategy 2 — PROXY_PATH_FOR_PICKLE_2 + pth
    if pickle_2:
        req_path = pickle_2 + pth
        file_check = req_path + '/' + curr_request + '.path'
        tried.append(file_check)
        if os.path.isfile(file_check):
            pickle_path = _follow_path_file(file_check, pickle_1)
            if pickle_path and pickle_path.exists():
                return pickle_path, None

        # Strategy 3 — PROXY_PATH_FOR_PICKLE_2 + /working/{job_name}
        file_check = os.path.join(pickle_2, 'working', curr_request, curr_request + '.path')
        tried.append(file_check)
        if os.path.isfile(file_check):
            pickle_path = _follow_path_file(file_check, pickle_1)
            if pickle_path and pickle_path.exists():
                return pickle_path, None

    # Fallback: glob — handles display/stripped name (job name without embedded site)
    import re as _re
    m = _re.match(r'(\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}_)', job_name)
    if m and pickle_1:
        ts = m.group(1)
        ref_part = job_name.split('-')[-2] if job_name.count('-') >= 2 else ''
        try:
            base = Path(pickle_1) / 'PBS_CRL.working'
            for d in base.iterdir():
                if not d.is_dir() or not d.name.startswith(ts):
                    continue
                if ref_part and ref_part not in d.name:
                    continue
                dname = d.name
                file_check = str(d / (dname + '.path'))
                if os.path.isfile(file_check):
                    pickle_path = _follow_path_file(file_check, pickle_1)
                    if pickle_path and pickle_path.exists():
                        return pickle_path, None
                direct = d / 'build' / 'dictinfo_pickled.bin'
                if direct.exists():
                    return direct, None
        except Exception:
            pass

    return None, 'dictinfo_pickled.bin not found (tried: ' + '; '.join(tried) + ')'


def load_pickle(pickle_path):
    """Load and return the pickle dict using the compat unpickler."""
    with open(pickle_path, 'rb') as f:
        return _CompatUnpickler(f).load()


# ──────────────────────────────────────────────
# Part processing  (port of traitements_msg_trace)
# ──────────────────────────────────────────────

_LIST_TO_NOT_DISPLAY = {
    'ZEROCOMPUTEDMASS', 'MISSINGMAT', 'WRONGTREATCORRECTED',
    'NOTRELEASED', 'NOTRELEASED-PROTOTYPE', 'NOT_RELEASED_COMPONENT',
    'WRONGMAT', 'WRONGTREAT', 'PART_DONONTUSE'
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
            except (AttributeError, KeyError, TypeError):
                continue

            for error_dict in errors:
                error_id    = error_dict[0] if isinstance(error_dict, (list, tuple)) and len(error_dict) > 0 else str(error_dict)
                part_number = getattr(part_dict, 'S_PART_NUMBER', '')

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


def _tr(part_id, *cells):
    """Build a <tr id='...' onclick='parent.jump(this.id)'> row — mirrors POSTCODE HTML."""
    tds = ''.join(f'<td>{c}</td>' for c in cells)
    return f"<tr id='{part_id}' onclick='parent.jump(this.id)'>{tds}</tr>"


def _pn(obj):
    """Safely get S_PART_NUMBER from a Part stub (or return str of obj)."""
    return getattr(obj, 'S_PART_NUMBER', str(obj))


def _populate_category(error_id, error_dict,
                        nomass, notag, nomaterial,
                        noreleased, wrongmat, wrongtreat):
    """
    Populate filter-button lists with HTML <tr> strings.
    Mirrors the DB POSTCODE exec logic exactly:
      MISSINGMAT  → NOMATERIAL.append(<tr id=pn><td>MAT:pn</td></tr>)
      NULLTAG     → NOTAG.append(<tr id=pn><td>pn</td><td>pn2</td></tr>)
      ZEROCOMPUTED→ NOMASS.append(<tr id=pn><td>pn</td></tr>)
      NOTRELEASED → NORELEASED.append(<tr id=pn><td>pn</td></tr>)
      WRONGMAT/   → WRONGMAT/TREAT.append(<tr id=pn><td>pn</td><td>val</td></tr>)
      WRONGTREAT
    """
    p1 = _pn(error_dict[1]) if len(error_dict) > 1 else ''

    if error_id in ('MISSINGMAT',):
        row = _tr(p1, 'MAT:' + p1)
        if row not in nomaterial:
            nomaterial.append(row)

    elif error_id in ('NULLTAG',):
        p2 = _pn(error_dict[2]) if len(error_dict) > 2 else ''
        row = _tr(p1, p1, p2)
        if row not in notag:
            notag.append(row)

    elif error_id in ('ZEROCOMPUTEDMASS',):
        row = _tr(p1, p1)
        if row not in nomass:
            nomass.append(row)

    elif error_id in ('NOTRELEASED', 'NOTRELEASED-PROTOTYPE',
                      'NOT_RELEASED_COMPONENT', 'OTHER_SITE_RESP_NOTRELEASED'):
        row = _tr(p1, p1)
        if row not in noreleased:
            noreleased.append(row)

    elif error_id in ('WRONGMAT', 'MATMISMATCH'):
        p2 = _pn(error_dict[2]) if len(error_dict) > 2 else p1
        val = str(error_dict[3]) if len(error_dict) > 3 else ''
        row = _tr(p2, p2, val)
        if row not in wrongmat:
            wrongmat.append(row)

    elif error_id in ('WRONGTREAT',):
        p2 = _pn(error_dict[2]) if len(error_dict) > 2 else p1
        val = str(error_dict[3]) if len(error_dict) > 3 else ''
        row = _tr(p2, p2, val)
        if row not in wrongtreat:
            wrongtreat.append(row)


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
