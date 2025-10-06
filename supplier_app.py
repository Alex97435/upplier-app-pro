"""
supplier_app.py
----------------

This file implements a simple web application for managing salon suppliers.
The application is built with the Flask framework and stores all supplier
records in a local SQLite database.  Each supplier belongs to a specific
category (such as carrelage, sanitaires, menuiseries alu, etc.), can be
assigned a rating colour (red, yellow or green) and may include contact
details, optional WhatsApp and WeChat links, as well as uploaded photos
and catalogue documents.  A key feature of the app is the ability to
generate QR codes for WhatsApp and WeChat contacts on demand using the
``qrcode`` library – the PyPI project page notes that you can generate
QR codes in Python by calling ``qrcode.make('Some data here')`` and then
saving the image to disk via ``img.save("some_file.png")``【617998091682678†L124-L135】.

Routes provided by this application:

* ``/`` – Displays a table of all suppliers with optional search by
  category.  Each row shows the supplier’s name, category, contact
  information, rating colour indicator, thumbnail of the uploaded photo
  (if any), link to the catalogue file (if any), and action buttons to
  view details, edit or delete the supplier.
* ``/add`` – Presents a form for creating a new supplier.  The form
  accepts text inputs for the name, category and contact details,
  optional WhatsApp and WeChat links, a rating selector and file inputs
  for uploading a photo and a catalogue document.  When the form is
  submitted, the uploaded files are stored in the ``uploads`` folder
  relative to the application root and the supplier is inserted into the
  SQLite database.
* ``/supplier/<id>`` – Shows a detailed view of a single supplier.
  This page displays all the stored fields, including the uploaded
  images and documents.  It also generates QR code images on demand for
  WhatsApp and WeChat using the ``qrcode`` library if links are
  provided.
* ``/edit/<id>`` – Provides a form to update an existing supplier.  It
  closely mirrors the add form but pre‑populates the fields with the
  current database values.  Uploaded files are replaced if new files are
  selected.
* ``/delete/<id>`` – Removes the specified supplier and any associated
  files from the server.

The database connection logic is adapted from the official Flask
patterns for working with SQLite, which recommend connecting lazily
within the request context and closing the connection at the end of the
request【686956880271344†L15-L34】.  A helper ``init_db()`` function
creates the ``suppliers`` table when the application starts if it does
not already exist.

To run this application locally you will need to install its Python
dependencies.  The QR code generator is provided by the ``qrcode``
package; according to the PyPI documentation, it can be installed with
``pip install qrcode[pil]``【617998091682678†L101-L115】.  Flask itself
must also be installed (``pip install flask``).  See the bottom of
this file for step‑by‑step instructions on how to run the app using
PowerShell.
"""

import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, g, request, redirect, url_for, send_from_directory, abort,
    render_template_string, session, flash, jsonify
)

import requests  # For calling the Azure Document Intelligence API
import time      # For polling asynchronous Azure operations
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode


###############################################################################
# Configuration
###############################################################################

# Create the Flask application
app = Flask(__name__)

# Secret key for session management.  This should be overridden via an
# environment variable in production.  Without a secret key Flask cannot
# securely sign session cookies.  Here we fall back to a default for
# development purposes.
app.secret_key = os.environ.get('SECRET_KEY', 'tradeLinkPro-secret-key')

# Determine the base directory for resolving relative paths to the source
# code.  ``BASE_DIR`` is used as a fallback when no environment overrides
# are provided.  In containerised deployments (such as Railway), the
# application directory may be read‑only, so we allow both the upload
# directory and database path to be configured via environment variables.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Configure where uploaded files will be stored.  By default the
# ``uploads`` directory resides next to this script.  In production you
# should set ``UPLOAD_FOLDER`` via an environment variable to point to a
# writable location (for example a mounted volume).  The directory is
# created at startup if it doesn't exist.
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, "uploads"))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Path to the SQLite database file.  If ``DATABASE_PATH`` is set in the
# environment it will be used, otherwise we default to storing the
# database alongside the script.  On hosting providers like Railway the
# source directory may be read only, so you should set ``DATABASE_PATH``
# to a writable location such as ``/tmp/suppliers.db`` or a mounted
# volume (e.g. ``/data/suppliers.db``).  Without this override the
# application will attempt to create the database in the current
# directory which may fail in read‑only environments.
DATABASE = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'suppliers.db'))

# Allowed file extensions for catalogue documents and photos.  This
# prevents unwanted files from being uploaded.
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'pdf', 'doc', 'docx'}

# Predefined list of supplier categories.  When adding or editing a
# supplier, the category field is presented as a dropdown with these
# options.  Suppliers can belong to one of these activities.
# Categories of suppliers.  Added 'autre' to allow a catch‑all option.
CATEGORIES = [
    'carrelage',
    'sanitaires',
    'menuiseries alu',
    'plomberie',
    'électricité',
    'menuiserie bois',
    'cuisine',
    'luminaire',
    'structures métalliques',
    'autre'
]

# Email of the application administrator.  Only this user may create
# additional user accounts once the application is initialised.  When
# no users exist in the database, the first account created will be
# treated as the administrator (it is up to you to use this email
# during initial registration).
ADMIN_EMAIL = 'alexandrebetonpro@gmail.com'


###############################################################################
# Authentication utilities
###############################################################################

def login_required(func):
    """Decorator to require a user to be logged in to access a route.

    If the user is not logged in, they are redirected to the login page with
    a ``next`` parameter so they can be returned after successful login.
    """
    @wraps(func)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return func(*args, **kwargs)
    return wrapped


def is_admin() -> bool:
    """Return True if the currently logged-in user is the administrator.

    This checks the ``username`` stored in the session against the
    configured ``ADMIN_EMAIL``.  If no user is logged in, returns False.
    """
    return session.get('username') == ADMIN_EMAIL


###############################################################################
# Database helpers
###############################################################################

def get_db():
    """Return a database connection for the current context.

    Connections are created on demand and cached on the `g` object for
    reuse within a single request.  This pattern comes directly from
    Flask’s documentation on working with SQLite【686956880271344†L15-L34】.
    The row factory is set to return ``sqlite3.Row`` objects so that
    results behave like dictionaries.
    """
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    """Close the database connection at the end of the request context."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    """Initialise the database with the suppliers table.

    This function creates the ``suppliers`` table if it does not already
    exist.  It should be called once when the application starts.
    """
    with app.app_context():
        db = get_db()
        # Create the suppliers table if it doesn't exist.  We include
        # optional columns for description and created_at.  SQLite
        # ignores duplicate columns if they already exist.
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                contact TEXT,
                whatsapp_link TEXT,
                wechat_link TEXT,
                rating TEXT,
                photo_filename TEXT,
                catalog_filename TEXT,
                created_at TEXT
            )
            """
        )
        # Attempt to add missing columns if they were not part of the
        # original table.  These statements will raise
        # OperationalError if the column already exists, which we
        # intentionally ignore.
        try:
            db.execute("ALTER TABLE suppliers ADD COLUMN description TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            db.execute("ALTER TABLE suppliers ADD COLUMN created_at TEXT")
        except sqlite3.OperationalError:
            pass
        # Add user_id column to suppliers table for multi-user support.  This
        # column links each supplier to the user who created it.  Existing
        # tables may not have this column, so we attempt to add it and ignore
        # the error if it already exists.
        try:
            db.execute("ALTER TABLE suppliers ADD COLUMN user_id INTEGER")
        except sqlite3.OperationalError:
            pass

        # Create the users table if it does not exist.  Each user has a
        # unique username and a password hash.  Passwords are hashed using
        # Werkzeug’s ``generate_password_hash`` to avoid storing plain text.
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
            """
        )

###############################################################################
# Azure Document Intelligence route
###############################################################################

@app.route('/analyze_card', methods=['POST'])
@login_required
def analyze_card():
    """Analyze a business card image using Azure Document Intelligence.

    This endpoint expects a multipart/form-data request with a file field
    named ``card_image`` containing the image of a business card.  It uses
    the prebuilt Business Card model (version 3.1) to extract contact
    information.  The endpoint and key must be provided via the
    ``AZURE_ENDPOINT`` and ``AZURE_KEY`` environment variables.  On
    success, returns a JSON payload with the detected ``name`` and ``phone``.

    If Azure configuration is missing or the service cannot be reached,
    returns an error message for graceful handling on the client side.
    """
    # Ensure an image has been uploaded
    if 'card_image' not in request.files:
        return jsonify({'error': 'Aucune image reçue'}), 400
    uploaded = request.files['card_image']
    if uploaded.filename == '':
        return jsonify({'error': 'Aucune image reçue'}), 400
    image_data = uploaded.read()

    # Retrieve Azure endpoint and API key from environment
    endpoint = os.environ.get('AZURE_ENDPOINT')
    key = os.environ.get('AZURE_KEY')
    if not endpoint or not key:
        return jsonify({'error': 'Configuration Azure manquante'}), 500

    # Build the analysis request
    analyze_url = f"{endpoint.rstrip('/')}/formrecognizer/documentModels/prebuilt-businessCard:analyze?api-version=2023-07-31"
    headers = {
        'Ocp-Apim-Subscription-Key': key,
        'Content-Type': uploaded.mimetype or 'application/octet-stream'
    }
    try:
        response = requests.post(analyze_url, headers=headers, data=image_data)
    except Exception as exc:
        return jsonify({'error': f'Erreur de connexion au service Azure : {exc}'})
    # Expect a 202 Accepted with an Operation-Location header
    if response.status_code != 202:
        return jsonify({'error': 'Échec de l\'analyse', 'details': response.text}), 500
    result_url = response.headers.get('Operation-Location')
    if not result_url:
        return jsonify({'error': 'Réponse inattendue du service Azure'}), 500

    # Poll the result until succeeded or failed
    result_data = None
    for _ in range(30):  # up to ~30 s
        time.sleep(1)
        try:
            result_resp = requests.get(result_url, headers={'Ocp-Apim-Subscription-Key': key})
            result_json = result_resp.json()
        except Exception:
            continue
        status = result_json.get('status')
        if status == 'succeeded':
            result_data = result_json
            break
        elif status == 'failed':
            return jsonify({'error': 'Analyse de la carte échouée'}), 500
    if result_data is None:
        return jsonify({'error': 'Analyse incomplète'}), 500

    # Extract name and phone from the result
    name = ''
    phone = ''
    try:
        documents = result_data['analyzeResult']['documents']
        if documents:
            fields = documents[0].get('fields', {})
            # Extract full name from contactNames if present
            names_list = fields.get('contactNames', {}).get('valueArray', [])
            full_names = []
            for item in names_list:
                obj = item.get('valueObject', {})
                first = obj.get('firstName', {}).get('value', '')
                last = obj.get('lastName', {}).get('value', '')
                combined = (first + ' ' + last).strip()
                if combined:
                    full_names.append(combined)
            if full_names:
                name = full_names[0]
            # Extract phone from mobilePhones or companyPhones
            mobiles = fields.get('mobilePhones', {}).get('valueArray', [])
            if mobiles:
                phone = mobiles[0].get('valueString', '')
            if not phone:
                companies = fields.get('companyPhones', {}).get('valueArray', [])
                if companies:
                    phone = companies[0].get('valueString', '')
    except Exception:
        # In case of unexpected structure, return empty values
        pass
    return jsonify({'name': name, 'phone': phone})


# ---------------------------------------------------------------------------
# Database initialisation on import
# ---------------------------------------------------------------------------

# When using Flask 3.x and running under a WSGI server like Gunicorn, the
# ``before_first_request`` hook has been removed【793943381351773†L14-L21】.  To ensure
# that the database schema is present when the application starts, we
# initialise the database immediately after defining it.  ``init_db()`` uses
# ``app.app_context()`` internally, so this call is safe at import time.
init_db()


###############################################################################
# Utility functions
###############################################################################

def allowed_file(filename: str) -> bool:
    """Return True if the filename has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file_storage):
    """Save an uploaded file and return its safe filename.

    If the file is not provided or has an unsupported extension the
    function returns an empty string.
    """
    if not file_storage or file_storage.filename == '':
        return ''
    filename = secure_filename(file_storage.filename)
    if not allowed_file(filename):
        return ''
    # Ensure unique filenames by prefixing with an incrementing counter.
    basename, ext = os.path.splitext(filename)
    counter = 1
    unique_filename = filename
    while os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)):
        unique_filename = f"{basename}_{counter}{ext}"
        counter += 1
    file_storage.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
    return unique_filename


def generate_qr_code(data: str, filename: str) -> str:
    """Generate a QR code for the given data and save it to a file.

    The QR code is created using the ``qrcode`` library.  The PyPI
    documentation shows that you can call ``qrcode.make('Some data here')``
    to produce a QR code object and then save it using the ``.save``
    method【617998091682678†L124-L135】.  The file will be stored in the
    ``uploads`` directory and the function returns the relative filename.
    """
    if not data:
        return ''
    qr_img = qrcode.make(data)
    # Ensure the QR code filename does not conflict with existing files
    basename, ext = os.path.splitext(filename)
    if ext == '':
        ext = '.png'
    unique_filename = filename if filename.endswith(ext) else f"{filename}.png"
    counter = 1
    while os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)):
        unique_filename = f"{basename}_{counter}{ext}"
        counter += 1
    qr_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    qr_img.save(qr_path)
    return unique_filename


###############################################################################
# Templates
###############################################################################

# The templates are defined as multi‑line Python strings.  In a more
# conventional Flask project you would place these in separate HTML files,
# but for the purposes of this exercise – keeping everything in a
# single file – embedding the templates directly makes the script self‑
# contained.

# New dark-themed index page with card layout and QR scanning.  The
# header includes the total number of suppliers.  Each supplier is
# displayed as a card with its name, description or category, contact
# icons and rating.  A floating action button allows scanning a QR
# code to pre‑populate the add form.
INDEX_TEMPLATE = r"""
<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TradeLinkPro</title>
    <!-- Font Awesome for icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    <style>
        body {
            margin: 0;
            padding: 0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #1e2a38;
            color: #f5f5f5;
        }
        header {
            padding: 20px;
            background-color: #15202b;
            display: flex;
            flex-direction: column;
            position: relative;
        }
        header h1 {
            margin: 0;
            font-size: 24px;
            font-weight: bold;
        }
        header .subtitle {
            font-size: 13px;
            color: #a0b0c0;
            margin-top: 4px;
        }
        header .logout-link {
            position: absolute;
            top: 20px;
            right: 20px;
            color: #799bb9;
            font-size: 20px;
            text-decoration: none;
        }
        header .admin-link {
            position: absolute;
            top: 20px;
            right: 50px;
            color: #799bb9;
            font-size: 20px;
            text-decoration: none;
        }
        header .admin-users-link {
            position: absolute;
            top: 20px;
            right: 80px;
            color: #799bb9;
            font-size: 20px;
            text-decoration: none;
        }
        .container {
            padding: 20px;
        }
        .search-container {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .search-form {
            flex: 1;
            display: flex;
            align-items: center;
            background-color: #15202b;
            border-radius: 8px;
            padding: 8px 12px;
        }
        .search-form input {
            flex: 1;
            background: transparent;
            border: none;
            color: #f5f5f5;
            padding: 6px;
            outline: none;
        }
        .search-form button {
            background: none;
            border: none;
            color: #799bb9;
            font-size: 18px;
            cursor: pointer;
        }
        .cards {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .card {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            background-color: #273a4b;
            border-radius: 10px;
            padding: 16px;
        }
        .card .left {
            flex: 1;
        }
        .card .left .title {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 6px;
        }
        .card .left .desc {
            font-size: 14px;
            color: #c0d0e0;
            margin-bottom: 8px;
        }
        .card .left .icons a {
            color: #77a8cf;
            margin-right: 10px;
            font-size: 16px;
            text-decoration: none;
        }
        .card .right {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 8px;
            text-align: right;
        }
        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
        }
        .badge.category {
            background-color: #374d65;
            color: #9fbad0;
        }
        .badge.rating-green {
            background-color: #1c7430;
            color: #d4edda;
        }
        .badge.rating-yellow {
            background-color: #857902;
            color: #fff3cd;
        }
        .badge.rating-red {
            background-color: #721c24;
            color: #f8d7da;
        }
        .date {
            font-size: 12px;
            color: #8fa6bd;
        }
        .delete-btn {
            color: #d9534f;
            font-size: 16px;
            text-decoration: none;
        }
        /* Floating buttons for add and scan actions */
        .fab-btn {
            position: fixed;
            bottom: 20px;
            width: 56px;
            height: 56px;
            border-radius: 50%;
            background-color: #5b7bda;
            color: #fff;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 2px 5px rgba(0,0,0,0.4);
        }
        .fab-add {
            right: 20px;
            cursor: pointer;
        }
        .fab-scan {
            /* Place the scan button to the left of the add button */
            right: 90px;
            cursor: pointer;
        }
        /* Scan modal */
        #scanModal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: rgba(0,0,0,0.8);
            align-items: center;
            justify-content: center;
            z-index: 1000;
            flex-direction: column;
        }
        #qr-reader {
            width: 300px;
            height: 300px;
            margin-bottom: 10px;
        }
        .close-btn {
            background: transparent;
            border: none;
            color: #fff;
            font-size: 30px;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <header>
        <h1>TradeLinkPro</h1>
        <div class="subtitle">{{ username }} • {{ total_suppliers }} fournisseurs</div>
        <a href="{{ url_for('logout') }}" class="logout-link" title="Déconnexion"><i class="fa fa-sign-out-alt"></i></a>
        {% if is_admin %}
        <a href="{{ url_for('list_users') }}" class="admin-users-link" title="Gestion des utilisateurs"><i class="fa fa-users"></i></a>
        <a href="{{ url_for('register') }}" class="admin-link" title="Créer un utilisateur"><i class="fa fa-user-plus"></i></a>
        {% endif %}
    </header>
    <div class="container">
        <div class="search-container">
            <form method="get" action="{{ url_for('index') }}" class="search-form" style="flex: 1; display: flex; align-items: center; gap: 6px;">
                <input type="text" name="search" placeholder="Rechercher un fournisseur..." value="{{ search_query }}" autocomplete="off" style="flex: 1;">
                <button type="submit" style="background: none; border: none; color: #799bb9; font-size: 18px; cursor: pointer;"><i class="fa fa-search"></i></button>
                <select name="sort" onchange="this.form.submit()" style="background-color: #15202b; color: #f5f5f5; border: 1px solid #374d65; border-radius: 6px; padding: 6px;">
                    <option value="" {% if not sort_key %}selected{% endif %}>Tri par défaut</option>
                    <option value="category" {% if sort_key == 'category' %}selected{% endif %}>Catégorie</option>
                    <option value="rating" {% if sort_key == 'rating' %}selected{% endif %}>Couleur</option>
                </select>
            </form>
        </div>
        <div class="cards">
            {% for s in suppliers %}
            <div class="card">
                <div class="left">
                    <div class="title">{{ s['name'] }}</div>
                    <div class="desc">{{ s['description'] if s['description'] else ('Fournisseur de ' + s['category']) }}</div>
                    <div class="icons">
                        {% if s['contact'] %}
                            <a href="tel:{{ s['contact'] }}" title="Appeler"><i class="fa fa-phone"></i></a>
                        {% endif %}
                        {% if s['whatsapp_link'] %}
                            <a href="{{ s['whatsapp_link'] }}" title="WhatsApp" target="_blank"><i class="fab fa-whatsapp"></i></a>
                        {% endif %}
                        {% if s['wechat_link'] %}
                            <a href="{{ s['wechat_link'] }}" title="WeChat" target="_blank"><i class="fa fa-weixin"></i></a>
                        {% endif %}
                    </div>
                </div>
                <div class="right">
                    {% if s['rating'] == 'green' %}
                        <span class="badge rating-green">OK</span>
                    {% elif s['rating'] == 'yellow' %}
                        <span class="badge rating-yellow">Moyen</span>
                    {% elif s['rating'] == 'red' %}
                        <span class="badge rating-red">Mauvais</span>
                    {% endif %}
                    <span class="badge category">{{ s['category'] }}</span>
                    <span class="date">{{ s['created_at'][:10] if s['created_at'] else '' }}</span>
                    <a href="{{ url_for('delete_supplier', supplier_id=s['id']) }}" class="delete-btn" title="Supprimer" onclick="return confirm('Supprimer ce fournisseur ?');"><i class="fa fa-trash"></i></a>
                    <a href="{{ url_for('view_supplier', supplier_id=s['id']) }}" class="delete-btn" title="Détails"><i class="fa fa-eye"></i></a>
                    <a href="{{ url_for('edit_supplier', supplier_id=s['id']) }}" class="delete-btn" title="Modifier"><i class="fa fa-edit"></i></a>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    <!-- Floating buttons for adding and scanning -->
    <div class="fab-btn fab-add" title="Ajouter un fournisseur">
        <a href="{{ url_for('add_supplier') }}" style="color: inherit; text-decoration: none;">
            <i class="fa fa-plus fa-lg"></i>
        </a>
    </div>
    <div class="fab-btn fab-scan" onclick="startScanner()" title="Scanner un QR code">
        <i class="fa fa-qrcode fa-lg"></i>
    </div>
    <!-- Scan modal -->
    <div id="scanModal">
        <div id="qr-reader"></div>
        <button class="close-btn" onclick="closeScanner()">&times;</button>
    </div>
    <script src="https://unpkg.com/html5-qrcode@2.2.1/html5-qrcode.min.js"></script>
    <!-- Include Tesseract.js for client-side OCR of business card images.  The CDN
         provides a version that runs entirely in the browser without needing
         a server-side dependency. -->
    <script src="https://cdn.jsdelivr.net/npm/tesseract.js@2/dist/tesseract.min.js"></script>
    <script>
    let html5QrcodeScanner = null;

    /**
     * Parse a decoded QR string and attempt to extract a name and phone number.
     *
     * Supports several common QR code formats:
     *  - vCard (BEGIN:VCARD) with FN/N and TEL fields
     *  - MECARD with N and TEL fields
     *  - WhatsApp click‑to‑chat URLs (wa.me/<digits>)
     *  - Generic "key:value" pairs separated by commas/semicolons
     *
     * Returns an object with ``name`` and ``phone`` keys.  Either may be
     * empty if not found.  See the QR parser logic in the add/edit page
     * for similar behaviour.
     */
    function parseContact(decodedText) {
        // Attempt to extract name, phone and a WhatsApp link from a decoded QR string.
        let name = '';
        let phone = '';
        let whatsappLink = '';
        const text = decodedText.trim();
        // vCard format (BEGIN:VCARD)
        if (/BEGIN:VCARD/i.test(text)) {
            const lines = text.split(/\r?\n/);
            lines.forEach(line => {
                line = line.trim();
                if (/^(FN|N):/i.test(line)) {
                    const val = line.split(':')[1] || '';
                    const cleaned = val.replace(/;/g, ' ').trim();
                    if (cleaned && !name) {
                        name = cleaned;
                    }
                }
                if (/^TEL/i.test(line)) {
                    const match = line.match(/(\+?\d+)/);
                    if (match && !phone) {
                        phone = match[1];
                    }
                }
            });
        }
        // MECARD format
        else if (/^MECARD:/i.test(text)) {
            const content = text.substring(7);
            const pairs = content.split(';');
            pairs.forEach(pair => {
                const kv = pair.split(':');
                if (kv.length === 2) {
                    const key = kv[0].trim().toUpperCase();
                    const value = kv[1].trim();
                    if (key === 'N' && value && !name) {
                        name = value.replace(/,/g, ' ').trim();
                    } else if (key === 'TEL' && value && !phone) {
                        phone = value.trim();
                    }
                }
            });
        }
        // WhatsApp click‑to‑chat link
        else if (/wa\.me\//i.test(text)) {
            // If it contains a phone number after wa.me/
            const numMatch = text.match(/wa\.me\/([0-9]+)/i);
            if (numMatch) {
                phone = numMatch[1];
                whatsappLink = `https://wa.me/${numMatch[1]}`;
            } else {
                // For other wa.me links like wa.me/qr/<code> we can't extract the phone but keep the link
                whatsappLink = text;
            }
        }
        // Fallback: parse generic key:value pairs separated by comma/semicolon
        if (!name || !phone) {
            const parts = text.split(/[,;]/);
            for (let i = 0; i < parts.length; i++) {
                const segment = parts[i].trim();
                const kv = segment.split(/[:=]/);
                if (kv.length === 2) {
                    const key = kv[0].trim().toLowerCase();
                    const value = kv[1].trim();
                    if (!name && (key.includes('name') || key.includes('nom'))) {
                        name = value;
                    } else if (!phone && (key.includes('phone') || key.includes('tel') || key.includes('numéro') || key.includes('numero'))) {
                        phone = value;
                    }
                } else if (kv.length === 1) {
                    // Only consider segments without any ':' or '=' as potential values
                    if (!name && segment && isNaN(segment) && !segment.includes('http') && !segment.includes('/') ) {
                        name = segment;
                    } else if (!phone && segment && !isNaN(segment)) {
                        phone = segment;
                    }
                }
            }
        }
        return { name, phone, whatsappLink };
    }

    function onScanSuccess(decodedText, decodedResult) {
        const result = parseContact(decodedText);
        html5QrcodeScanner.stop().then(() => {
            html5QrcodeScanner.clear();
            html5QrcodeScanner = null;
            // Build redirect URL with query parameters
            let url = '{{ url_for('add_supplier') }}';
            const params = [];
            if (result.name) params.push('name=' + encodeURIComponent(result.name));
            if (result.phone) {
                params.push('contact=' + encodeURIComponent(result.phone));
            } else if (result.whatsappLink) {
                // If no phone number could be extracted but a WhatsApp link exists,
                // pass it so the add form can prefill the WhatsApp field.
                params.push('whatsapp=' + encodeURIComponent(result.whatsappLink));
            }
            if (params.length > 0) {
                url += '?' + params.join('&');
            }
            window.location.href = url;
        }).catch((err) => {
            console.error(err);
        });
    }

    function startScanner() {
        // Show the modal and start scanning
        document.getElementById('scanModal').style.display = 'flex';
        html5QrcodeScanner = new Html5Qrcode('qr-reader');
        html5QrcodeScanner.start(
            { facingMode: "environment" },
            { fps: 10, qrbox: 250 },
            onScanSuccess
        ).catch((err) => {
            console.error(err);
        });
    }

    function closeScanner() {
        // Hide modal and stop scanning
        if (html5QrcodeScanner) {
            html5QrcodeScanner.stop().then(() => {
                html5QrcodeScanner.clear();
                html5QrcodeScanner = null;
            }).catch((err) => {
                console.error(err);
            });
        }
        document.getElementById('scanModal').style.display = 'none';
    }
    </script>
</body>
</html>
"""


# Dark-themed add/edit form with optional QR scanning overlay.  The
# template accepts ``supplier`` (None for add), ``pre_name`` and
# ``pre_contact`` for prefilled values from QR scanning.
ADD_EDIT_TEMPLATE = r"""
<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ 'Modifier' if supplier else 'Ajouter' }} un fournisseur</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    <style>
        body {
            margin: 0;
            padding: 0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #1e2a38;
            color: #f5f5f5;
        }
        .container {
            max-width: 600px;
            margin: 40px auto;
            background-color: #273a4b;
            border-radius: 10px;
            padding: 20px 30px;
        }
        h1 {
            font-size: 22px;
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-top: 12px;
            font-weight: 500;
        }
        input[type="text"], textarea, select {
            width: 100%;
            padding: 8px;
            margin-top: 4px;
            border: 1px solid #374d65;
            border-radius: 6px;
            background-color: #15202b;
            color: #f5f5f5;
        }
        textarea {
            resize: vertical;
            min-height: 80px;
        }
        input[type="file"] {
            margin-top: 8px;
            color: #dcdcdc;
        }
        .actions {
            margin-top: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
        }
        .btn-primary {
            background-color: #5b7bda;
            color: #fff;
        }
        .btn-secondary {
            background-color: #495867;
            color: #dcdcdc;
            text-decoration: none;
        }
        /* Scan modal inside add/edit page */
        #scanModal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: rgba(0,0,0,0.8);
            align-items: center;
            justify-content: center;
            z-index: 1000;
            flex-direction: column;
        }
        #qr-reader {
            width: 300px;
            height: 300px;
            margin-bottom: 10px;
        }
        .close-btn {
            background: transparent;
            border: none;
            color: #fff;
            font-size: 30px;
            cursor: pointer;
        }
        .scan-btn {
            margin-top: 10px;
            background-color: #5b7bda;
            color: #fff;
            border: none;
            border-radius: 4px;
            padding: 6px 12px;
            cursor: pointer;
            font-size: 14px;
            display: inline-flex;
            align-items: center;
        }
        .scan-btn i {
            margin-right: 6px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>{{ 'Modifier' if supplier else 'Ajouter' }} un fournisseur</h1>
        <form method="post" enctype="multipart/form-data">
            <label for="name">Nom :</label>
            <input type="text" id="name" name="name" required value="{{ supplier['name'] if supplier else (pre_name if pre_name else '') }}">

            <label for="category">Catégorie :</label>
            <select id="category" name="category" required>
                <option value="">– Sélectionner –</option>
                {% for cat in categories %}
                    <option value="{{ cat }}" {% if (supplier and supplier['category'] == cat) %}selected{% endif %}>{{ cat.capitalize() }}</option>
                {% endfor %}
            </select>

            <label for="description">Description :</label>
            <textarea id="description" name="description">{{ supplier['description'] if supplier else '' }}</textarea>

            <label for="contact">Numéro de téléphone :</label>
            <input type="text" id="contact" name="contact" value="{{ supplier['contact'] if supplier else (pre_contact if pre_contact else '') }}">

            <label for="whatsapp">Lien WhatsApp :</label>
            <input type="text" id="whatsapp" name="whatsapp" value="{{ supplier['whatsapp_link'] if supplier else (pre_whatsapp if pre_whatsapp else '') }}" placeholder="https://wa.me/Numéro">

            <label for="wechat">Lien WeChat :</label>
            <input type="text" id="wechat" name="wechat" value="{{ supplier['wechat_link'] if supplier else '' }}" placeholder="Lien WeChat">

            <label for="rating">Notation :</label>
            <select id="rating" name="rating">
                <option value="">– Sélectionner –</option>
                <option value="red" {% if supplier and supplier['rating']=='red' %}selected{% endif %}>Mauvais (Rouge)</option>
                <option value="yellow" {% if supplier and supplier['rating']=='yellow' %}selected{% endif %}>Moyen (Jaune)</option>
                <option value="green" {% if supplier and supplier['rating']=='green' %}selected{% endif %}>Super (Vert)</option>
            </select>

            <label for="photo">Photo :</label>
            <input type="file" id="photo" name="photo">
            {% if supplier and supplier['photo_filename'] %}
                <p>Photo actuelle : <a href="{{ url_for('uploaded_file', filename=supplier['photo_filename']) }}" target="_blank">{{ supplier['photo_filename'] }}</a></p>
            {% endif %}

            <label for="catalog">Catalogue (PDF ou doc) :</label>
            <input type="file" id="catalog" name="catalog">
            {% if supplier and supplier['catalog_filename'] %}
                <p>Catalogue actuel : <a href="{{ url_for('uploaded_file', filename=supplier['catalog_filename']) }}" target="_blank">{{ supplier['catalog_filename'] }}</a></p>
            {% endif %}

            {% if not supplier %}
            <!-- Business card image input and button to trigger OCR analysis.  The user selects
                 a photo of a business card and clicks the button; the script uses
                 Tesseract.js to extract text and populate the name and phone fields. -->
            <label for="business_card">Carte de visite :</label>
            <!-- The capture attribute on mobile devices will open the camera directly.  When a photo is selected
                 the uploadCard() function sends it to the server for OCR via Azure Document Intelligence. -->
            <input type="file" id="business_card" accept="image/*" capture="environment" onchange="uploadCard()">
            <!-- The scan button triggers the file input if none has been chosen.  Once a file is selected the
                 onchange handler uploads it for OCR. -->
            <button type="button" class="scan-btn" onclick="triggerCardInput()"><i class="fa fa-id-card"></i> Scanner carte</button>
            {% endif %}

            <div class="actions">
                <button type="submit" class="btn btn-primary">{{ 'Mettre à jour' if supplier else 'Ajouter' }}</button>
                <a href="{{ url_for('index') }}" class="btn btn-secondary">Annuler</a>
            </div>
        </form>
        <!-- Button to open QR scanning modal -->
        {% if not supplier %}
        <button class="scan-btn" onclick="openScanModal()"><i class="fa fa-qrcode"></i> Scanner QR pour pré-remplir</button>
        {% endif %}
    </div>
    <!-- Scan modal -->
    <div id="scanModal">
        <div id="qr-reader"></div>
        <button class="close-btn" onclick="closeScanModal()">&times;</button>
    </div>
    <script src="https://unpkg.com/html5-qrcode@2.2.1/html5-qrcode.min.js"></script>
    <!-- Include Tesseract.js so that we can perform OCR on the client as a fallback if Azure Document Intelligence is unavailable. -->
    <script src="https://cdn.jsdelivr.net/npm/tesseract.js@2/dist/tesseract.min.js"></script>
    <script>
    let qrScanner = null;

    // Shared parser for QR codes that attempts to extract name, phone and a WhatsApp link
    function parseContact(decodedText) {
        let name = '';
        let phone = '';
        let whatsappLink = '';
        const text = decodedText.trim();
        // vCard format (BEGIN:VCARD)
        if (/BEGIN:VCARD/i.test(text)) {
            const lines = text.split(/\r?\n/);
            lines.forEach(line => {
                line = line.trim();
                if (/^(FN|N):/i.test(line)) {
                    const val = line.split(':')[1] || '';
                    const cleaned = val.replace(/;/g, ' ').trim();
                    if (cleaned && !name) {
                        name = cleaned;
                    }
                }
                if (/^TEL/i.test(line)) {
                    const match = line.match(/(\+?\d+)/);
                    if (match && !phone) {
                        phone = match[1];
                    }
                }
            });
        }
        // MECARD format
        else if (/^MECARD:/i.test(text)) {
            const content = text.substring(7);
            const pairs = content.split(';');
            pairs.forEach(pair => {
                const kv = pair.split(':');
                if (kv.length === 2) {
                    const key = kv[0].trim().toUpperCase();
                    const value = kv[1].trim();
                    if (key === 'N' && value && !name) {
                        name = value.replace(/,/g, ' ').trim();
                    } else if (key === 'TEL' && value && !phone) {
                        phone = value.trim();
                    }
                }
            });
        }
        // WhatsApp click‑to‑chat link
        else if (/wa\.me\//i.test(text)) {
            const numMatch = text.match(/wa\.me\/([0-9]+)/i);
            if (numMatch) {
                phone = numMatch[1];
                whatsappLink = `https://wa.me/${numMatch[1]}`;
            } else {
                whatsappLink = text;
            }
        }
        // Fallback: generic key:value pairs or plain segments
        if (!name || !phone) {
            const parts = text.split(/[,;]/);
            for (let i = 0; i < parts.length; i++) {
                const segment = parts[i].trim();
                const kv = segment.split(/[:=]/);
                if (kv.length === 2) {
                    const key = kv[0].trim().toLowerCase();
                    const value = kv[1].trim();
                    if (!name && (key.includes('name') || key.includes('nom'))) {
                        name = value;
                    } else if (!phone && (key.includes('phone') || key.includes('tel') || key.includes('numéro') || key.includes('numero'))) {
                        phone = value;
                    }
                } else if (kv.length === 1) {
                    // Only consider segments without any ':' or '=' as potential values
                    if (!name && segment && isNaN(segment) && !segment.includes('http') && !segment.includes('/')) {
                        name = segment;
                    } else if (!phone && segment && !isNaN(segment)) {
                        phone = segment;
                    }
                }
            }
        }
        return { name, phone, whatsappLink };
    }

    function onScanSuccess(decodedText, decodedResult) {
        const result = parseContact(decodedText);
        // Prefill fields if values were extracted.  We also support
        // populating the WhatsApp field when a wa.me link is present.
        if (result.name) {
            document.getElementById('name').value = result.name;
        }
        if (result.phone) {
            document.getElementById('contact').value = result.phone;
        }
        // If no phone could be extracted but we have a WhatsApp link, set it.
        if (!result.phone && result.whatsappLink) {
            document.getElementById('whatsapp').value = result.whatsappLink;
        } else if (result.whatsappLink) {
            // If both phone and link exist (e.g. wa.me/123456), we still fill the WhatsApp field
            document.getElementById('whatsapp').value = result.whatsappLink;
        }
        stopScanner();
    }

    function openScanModal() {
        document.getElementById('scanModal').style.display = 'flex';
        qrScanner = new Html5Qrcode('qr-reader');
        qrScanner.start(
            { facingMode: 'environment' },
            { fps: 10, qrbox: 250 },
            onScanSuccess
        ).catch(err => console.error(err));
    }

    function stopScanner() {
        if (qrScanner) {
            qrScanner.stop().then(() => {
                qrScanner.clear();
                qrScanner = null;
            }).catch(err => console.error(err));
        }
        document.getElementById('scanModal').style.display = 'none';
    }

    function closeScanModal() {
        stopScanner();
    }

    // Upload a selected business card image to the server for OCR via Azure.
    async function uploadCard() {
        const input = document.getElementById('business_card');
        if (!input || input.files.length === 0) {
            alert('Veuillez sélectionner une image de carte de visite.');
            return;
        }
        const file = input.files[0];
        // Disable the scan button while processing
        let cardBtn = null;
        document.querySelectorAll('button.scan-btn').forEach(b => {
            if (b.innerText && b.innerText.toLowerCase().includes('scanner carte')) {
                cardBtn = b;
            }
        });
        if (cardBtn) {
            cardBtn.disabled = true;
            cardBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Analyse…';
        }
        let success = false;
        // First, try sending the image to the server-side Azure OCR endpoint
        try {
            const formData = new FormData();
            formData.append('card_image', file);
            const resp = await fetch('{{ url_for("analyze_card") }}', {
                method: 'POST',
                body: formData
            });
            if (resp.ok) {
                const data = await resp.json();
                if (!data.error) {
                    // Fill name and phone if available
                    if (data.name) document.getElementById('name').value = data.name;
                    if (data.phone) document.getElementById('contact').value = data.phone;
                    success = true;
                }
            }
        } catch (err) {
            console.warn('Serveur Azure OCR indisponible :', err);
        }
        // If no result from Azure, attempt client-side OCR via Tesseract.js as a fallback
        if (!success) {
            try {
                const { data: { text } } = await Tesseract.recognize(file, 'eng', { logger: m => console.log(m) });
                const lines = text.split(/\n+/).map(l => l.trim()).filter(Boolean);
                let foundName = '';
                let foundPhone = '';
                // Try to pick the first non-empty line as the name (heuristic)
                for (const line of lines) {
                    if (!foundName && /[a-zA-Z]{2,}/.test(line) && !/\d/.test(line)) {
                        foundName = line;
                    }
                    // Look for a sequence of digits/spaces that resembles a phone number
                    if (!foundPhone) {
                        const m = line.match(/(\+?\d[\d\s]{6,15}\d)/);
                        if (m) {
                            foundPhone = m[1].replace(/\s+/g, '');
                        }
                    }
                    if (foundName && foundPhone) break;
                }
                if (foundName) document.getElementById('name').value = foundName;
                if (foundPhone) document.getElementById('contact').value = foundPhone;
            } catch (err) {
                console.error('Erreur OCR locale :', err);
                alert('Impossible d\'extraire les informations de la carte.');
            }
        }
        // Re-enable the scan button
        if (cardBtn) {
            cardBtn.disabled = false;
            cardBtn.innerHTML = '<i class="fa fa-id-card"></i> Scanner carte';
        }
    }

    // Trigger the file input for card scanning.  On mobile this opens the camera.
    function triggerCardInput() {
        const input = document.getElementById('business_card');
        if (input) {
            input.click();
        }
    }

    // There is a single triggerCardInput() defined above.  It simply opens the file selector.
    </script>
</body>
</html>
"""


# Dark-themed login page.  This template displays a form where users enter
# their username and password.  It also includes a link to the registration
# page for new users.  Error messages can be passed via the ``error``
# variable.
LOGIN_TEMPLATE = """
<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Connexion</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    <style>
        body { background-color: #1e2a38; color: #f5f5f5; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; }
        .container { max-width: 400px; margin: 80px auto; background-color: #273a4b; padding: 30px; border-radius: 10px; }
        h1 { font-size: 24px; margin-bottom: 20px; text-align: center; }
        label { display: block; margin-top: 12px; }
        input[type="text"], input[type="password"] { width: 100%; padding: 8px; margin-top: 4px; border: 1px solid #374d65; border-radius: 6px; background-color: #15202b; color: #f5f5f5; }
        .actions { margin-top: 20px; display: flex; justify-content: space-between; align-items: center; }
        .btn { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; }
        .btn-primary { background-color: #5b7bda; color: #fff; width: 100%; }
        .link { color: #77a8cf; text-decoration: none; font-size: 14px; display: block; text-align: center; margin-top: 12px; }
        .error { color: #f28c8c; margin-top: 10px; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Connexion</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="post">
            <label for="username">Adresse email :</label>
            <input type="text" id="username" name="username" required>

            <label for="password">Mot de passe :</label>
            <input type="password" id="password" name="password" required>

            <div class="actions">
                <button type="submit" class="btn btn-primary">Se connecter</button>
            </div>
        </form>
        {% if allow_register %}
        <a href="{{ url_for('register') }}" class="link">Créer un compte</a>
        {% endif %}
    </div>
</body>
</html>
"""


# Dark-themed registration page.  New users can choose a unique username and
# password.  A confirmation field ensures the password is typed correctly.
REGISTER_TEMPLATE = """
<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Inscription</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    <style>
        body { background-color: #1e2a38; color: #f5f5f5; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; }
        .container { max-width: 400px; margin: 80px auto; background-color: #273a4b; padding: 30px; border-radius: 10px; }
        h1 { font-size: 24px; margin-bottom: 20px; text-align: center; }
        label { display: block; margin-top: 12px; }
        input[type="text"], input[type="password"] { width: 100%; padding: 8px; margin-top: 4px; border: 1px solid #374d65; border-radius: 6px; background-color: #15202b; color: #f5f5f5; }
        .actions { margin-top: 20px; display: flex; justify-content: space-between; align-items: center; }
        .btn { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; }
        .btn-primary { background-color: #5b7bda; color: #fff; width: 100%; }
        .link { color: #77a8cf; text-decoration: none; font-size: 14px; display: block; text-align: center; margin-top: 12px; }
        .error { color: #f28c8c; margin-top: 10px; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Inscription</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="post">
            <label for="username">Adresse email :</label>
            <input type="text" id="username" name="username" required>

            <label for="password">Mot de passe :</label>
            <input type="password" id="password" name="password" required>

            <label for="confirm">Confirmer le mot de passe :</label>
            <input type="password" id="confirm" name="confirm" required>

            <div class="actions">
                <button type="submit" class="btn btn-primary">Créer un compte</button>
            </div>
        </form>
        <a href="{{ url_for('login') }}" class="link">Déjà inscrit ? Se connecter</a>
    </div>
</body>
</html>
"""


# Dark-themed user list for administrators.  Displays all registered users
# along with actions to change passwords.  Only accessible to the admin.
USERS_TEMPLATE = """
<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gestion des utilisateurs</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    <style>
        body { background-color: #1e2a38; color: #f5f5f5; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; }
        .container { max-width: 700px; margin: 40px auto; background-color: #273a4b; padding: 20px 30px; border-radius: 10px; }
        h1 { font-size: 24px; margin-bottom: 20px; text-align: center; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 10px; border-bottom: 1px solid #374d65; text-align: left; }
        th { color: #a0b0c0; font-weight: 500; }
        a { color: #5b7bda; text-decoration: none; }
        .btn { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
        .btn-primary { background-color: #5b7bda; color: #fff; }
        .link-back { display: inline-block; margin-top: 20px; color: #77a8cf; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Gestion des utilisateurs</h1>
        <table>
            <tr><th>Adresse email</th><th>Actions</th></tr>
            {% for u in users %}
            <tr>
                <td>{{ u['username'] }}</td>
                <td><a href="{{ url_for('edit_user', user_id=u['id']) }}">Modifier le mot de passe</a></td>
            </tr>
            {% endfor %}
        </table>
        <a href="{{ url_for('index') }}" class="link-back">Retour au tableau de bord</a>
    </div>
</body>
</html>
"""


# Dark-themed user password edit page for administrators.  Allows the admin
# to reset a user’s password.
USER_EDIT_TEMPLATE = """
<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Modifier le mot de passe</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    <style>
        body { background-color: #1e2a38; color: #f5f5f5; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; }
        .container { max-width: 400px; margin: 80px auto; background-color: #273a4b; padding: 20px 30px; border-radius: 10px; }
        h1 { font-size: 22px; margin-bottom: 20px; text-align: center; }
        label { display: block; margin-top: 12px; font-weight: 500; }
        input[type="password"] { width: 100%; padding: 8px; margin-top: 4px; border: 1px solid #374d65; border-radius: 6px; background-color: #15202b; color: #f5f5f5; }
        .actions { margin-top: 20px; display: flex; justify-content: space-between; align-items: center; }
        .btn { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; }
        .btn-primary { background-color: #5b7bda; color: #fff; }
        .btn-secondary { background-color: #495867; color: #dcdcdc; text-decoration: none; }
        .error { color: #f28c8c; margin-top: 10px; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Modifier le mot de passe</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="post">
            <label for="password">Nouveau mot de passe :</label>
            <input type="password" id="password" name="password" required>

            <label for="confirm">Confirmer le mot de passe :</label>
            <input type="password" id="confirm" name="confirm" required>

            <div class="actions">
                <button type="submit" class="btn btn-primary">Mettre à jour</button>
                <a href="{{ url_for('list_users') }}" class="btn btn-secondary">Annuler</a>
            </div>
        </form>
    </div>
</body>
</html>
"""


DETAIL_TEMPLATE = """
<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Détails du fournisseur</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    <style>
        body {
            margin: 0;
            padding: 0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #1e2a38;
            color: #f5f5f5;
        }
        .container {
            max-width: 700px;
            margin: 40px auto;
            background-color: #273a4b;
            padding: 20px 30px;
            border-radius: 10px;
        }
        h1 {
            font-size: 24px;
            margin-bottom: 20px;
        }
        .info {
            margin-bottom: 12px;
        }
        .info label {
            font-weight: bold;
            margin-right: 6px;
        }
        .badges {
            margin-top: 10px;
        }
        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 12px;
            margin-right: 6px;
        }
        .badge.category {
            background-color: #374d65;
            color: #9fbad0;
        }
        .badge.rating-green {
            background-color: #1c7430;
            color: #d4edda;
        }
        .badge.rating-yellow {
            background-color: #857902;
            color: #fff3cd;
        }
        .badge.rating-red {
            background-color: #721c24;
            color: #f8d7da;
        }
        .images img {
            max-width: 300px;
            max-height: 300px;
            margin-right: 10px;
            border-radius: 6px;
        }
        .actions a {
            color: #5b7bda;
            margin-right: 10px;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Détails du fournisseur</h1>
        <div class="info"><label>Nom :</label> {{ supplier['name'] }}</div>
        <div class="info"><label>Catégorie :</label> {{ supplier['category'] }}</div>
        <div class="info"><label>Description :</label> {{ supplier['description'] or '-' }}</div>
        <div class="info"><label>Numéro de téléphone :</label> {{ supplier['contact'] or '-' }}</div>
        <div class="info badges">
            {% if supplier['rating'] == 'green' %}
                <span class="badge rating-green"><i class="fa fa-star"></i> Top</span>
            {% elif supplier['rating'] == 'yellow' %}
                <span class="badge rating-yellow">Moyen</span>
            {% elif supplier['rating'] == 'red' %}
                <span class="badge rating-red">Mauvais</span>
            {% endif %}
            <span class="badge category">{{ supplier['category'] }}</span>
            {% if supplier['created_at'] %}<span class="badge">{{ supplier['created_at'][:10] }}</span>{% endif %}
        </div>
        <div class="images">
            {% if supplier['photo_filename'] %}
                <div><label>Photo :</label><br><img src="{{ url_for('uploaded_file', filename=supplier['photo_filename']) }}" alt="photo"></div>
            {% endif %}
            {% if supplier['catalog_filename'] %}
                <div><label>Catalogue :</label> <a href="{{ url_for('uploaded_file', filename=supplier['catalog_filename']) }}" target="_blank">Télécharger</a></div>
            {% endif %}
        </div>
        <div class="images">
            <div>
                <label>QR Code WhatsApp :</label><br>
                {% if whatsapp_qr %}
                    <img src="{{ url_for('uploaded_file', filename=whatsapp_qr) }}" alt="QR WhatsApp">
                {% else %}
                    Non disponible
                {% endif %}
            </div>
            <div>
                <label>QR Code WeChat :</label><br>
                {% if wechat_qr %}
                    <img src="{{ url_for('uploaded_file', filename=wechat_qr) }}" alt="QR WeChat">
                {% else %}
                    Non disponible
                {% endif %}
            </div>
        </div>
        <div class="actions" style="margin-top: 20px;">
            <a href="{{ url_for('edit_supplier', supplier_id=supplier['id']) }}"><i class="fa fa-edit"></i> Modifier</a>
            <a href="{{ url_for('index') }}"><i class="fa fa-arrow-left"></i> Retour</a>
        </div>
    </div>
</body>
</html>
"""


###############################################################################
# Routes
###############################################################################

@app.route('/')
@login_required
def index():
    """Display the list of suppliers belonging to the logged-in user.

    The search bar filters suppliers by name, category or description.  Only
    suppliers with a ``user_id`` matching the current session are returned.
    """
    # Retrieve search and sort parameters from the query string
    search_query = request.args.get('search', '').strip()
    sort_key = request.args.get('sort', '').strip()
    db = get_db()
    user_id = session['user_id']
    # Build the base SQL and parameters based on whether a search term was provided.
    sql = "SELECT * FROM suppliers WHERE user_id = ?"
    params = [user_id]
    if search_query:
        like_query = f'%{search_query}%'
        sql += " AND (name LIKE ? OR category LIKE ? OR description LIKE ?)"
        params.extend([like_query, like_query, like_query])
    # Apply sorting based on the sort_key.  Sorting by rating uses a CASE expression to
    # order green first, then yellow, then red.  For categories we sort alphabetically.
    if sort_key == 'category':
        sql += " ORDER BY category COLLATE NOCASE ASC, name COLLATE NOCASE ASC"
    elif sort_key == 'rating':
        sql += " ORDER BY CASE rating WHEN 'green' THEN 1 WHEN 'yellow' THEN 2 WHEN 'red' THEN 3 ELSE 4 END, created_at DESC, name COLLATE NOCASE ASC"
    else:
        # Default sort: newest first then name
        sql += " ORDER BY created_at DESC, name COLLATE NOCASE ASC"
    rows = db.execute(sql, tuple(params)).fetchall()
    total = len(rows)
    username = session.get('username', 'Utilisateur')
    return render_template_string(
        INDEX_TEMPLATE,
        suppliers=rows,
        search_query=search_query,
        sort_key=sort_key,
        total_suppliers=total,
        username=username,
        is_admin=is_admin()
    )


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Serve uploaded files from the uploads directory."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_supplier():
    """Add a new supplier for the current user."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        contact = request.form.get('contact', '').strip()
        whatsapp = request.form.get('whatsapp', '').strip()
        wechat = request.form.get('wechat', '').strip()
        rating = request.form.get('rating', '').strip()

        # Save uploaded files
        photo_filename = save_upload(request.files.get('photo'))
        catalog_filename = save_upload(request.files.get('catalog'))

        # Assign creation timestamp
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Insert into database with association to the logged-in user
        db = get_db()
        user_id = session['user_id']
        # Insert the new supplier into the database.  Note that the number of
        # placeholders must match the number of columns specified.  We have
        # eleven columns (name, category, description, contact, whatsapp_link,
        # wechat_link, rating, photo_filename, catalog_filename, created_at,
        # user_id), so we provide exactly eleven ``?`` placeholders.  If the
        # placeholder count and values do not match SQLite will raise a
        # ``sqlite3.ProgrammingError``.
        db.execute(
            "INSERT INTO suppliers (name, category, description, contact, whatsapp_link, wechat_link, rating, photo_filename, catalog_filename, created_at, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, category, description, contact, whatsapp, wechat, rating, photo_filename, catalog_filename, created_at, user_id)
        )
        db.commit()
        return redirect(url_for('index'))
    # Pre-fill name and contact from query parameters if provided
    pre_name = request.args.get('name', '').strip()
    pre_contact = request.args.get('contact', '').strip()
    # Pre‑fill WhatsApp link if provided in the query parameters.  This is used
    # when scanning a QR code that contains a wa.me link but not an explicit
    # phone number.
    pre_whatsapp = request.args.get('whatsapp', '').strip()
    username = session.get('username', 'Utilisateur')
    return render_template_string(
        ADD_EDIT_TEMPLATE,
        supplier=None,
        pre_name=pre_name,
        pre_contact=pre_contact,
        pre_whatsapp=pre_whatsapp,
        categories=CATEGORIES,
        username=username
    )


@app.route('/supplier/<int:supplier_id>')
@login_required
def view_supplier(supplier_id: int):
    """Display details for a single supplier and generate QR codes if needed.

    Access is restricted to the supplier owner.  Users attempting to view a
    supplier that they do not own will receive a 403 error.
    """
    db = get_db()
    supplier = db.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if supplier is None:
        abort(404)
    # Ensure the supplier belongs to the current user
    if supplier['user_id'] is not None and supplier['user_id'] != session.get('user_id'):
        abort(403)

    # Generate QR codes on demand.  The QR code images are stored in the
    # uploads directory so they can be served as static files.  If the
    # supplier already has a QR code file (e.g. generated previously) and
    # the corresponding data has not changed we simply reuse it.  Since
    # this basic implementation does not store the generated filenames in
    # the database, we always regenerate for simplicity.
    whatsapp_qr = ''
    wechat_qr = ''
    # For WhatsApp we accept either a full URL from the form or just a number.
    whatsapp_data = supplier['whatsapp_link']
    if whatsapp_data:
        # If the data is purely numeric we build a wa.me link automatically.
        if whatsapp_data.isdigit():
            whatsapp_link = f"https://wa.me/{whatsapp_data}"
        else:
            whatsapp_link = whatsapp_data
        whatsapp_qr = generate_qr_code(whatsapp_link, f"whatsapp_qr_{supplier_id}.png")

    wechat_data = supplier['wechat_link']
    if wechat_data:
        # WeChat links are used as provided; they might be from
        # scanning a user’s QR code, e.g. ``https://u.wechat.com/...``.
        wechat_qr = generate_qr_code(wechat_data, f"wechat_qr_{supplier_id}.png")

    return render_template_string(
        DETAIL_TEMPLATE,
        supplier=supplier,
        whatsapp_qr=whatsapp_qr,
        wechat_qr=wechat_qr
    )


@app.route('/edit/<int:supplier_id>', methods=['GET', 'POST'])
@login_required
def edit_supplier(supplier_id: int):
    """Edit an existing supplier owned by the current user."""
    db = get_db()
    supplier = db.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if supplier is None:
        abort(404)
    # Only allow editing if the supplier belongs to the current user
    if supplier['user_id'] is not None and supplier['user_id'] != session.get('user_id'):
        abort(403)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        contact = request.form.get('contact', '').strip()
        whatsapp = request.form.get('whatsapp', '').strip()
        wechat = request.form.get('wechat', '').strip()
        rating = request.form.get('rating', '').strip()

        # Handle photo replacement
        new_photo = request.files.get('photo')
        photo_filename = supplier['photo_filename']
        if new_photo and new_photo.filename:
            # Delete old photo file
            if photo_filename:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], photo_filename)
                if os.path.exists(old_path):
                    os.remove(old_path)
            photo_filename = save_upload(new_photo)

        # Handle catalog replacement
        new_catalog = request.files.get('catalog')
        catalog_filename = supplier['catalog_filename']
        if new_catalog and new_catalog.filename:
            if catalog_filename:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], catalog_filename)
                if os.path.exists(old_path):
                    os.remove(old_path)
            catalog_filename = save_upload(new_catalog)

        db.execute(
            """
            UPDATE suppliers
            SET name = ?, category = ?, description = ?, contact = ?, whatsapp_link = ?, wechat_link = ?, rating = ?,
                photo_filename = ?, catalog_filename = ?
            WHERE id = ?
            """,
            (name, category, description, contact, whatsapp, wechat, rating, photo_filename, catalog_filename, supplier_id)
        )
        db.commit()
        return redirect(url_for('index'))
    # Provide blank prefill values for edit form
    username = session.get('username', 'Utilisateur')
    return render_template_string(
        ADD_EDIT_TEMPLATE,
        supplier=supplier,
        pre_name='',
        pre_contact='',
        categories=CATEGORIES,
        username=username
    )


@app.route('/delete/<int:supplier_id>')
@login_required
def delete_supplier(supplier_id: int):
    """Delete a supplier and associated files owned by the current user."""
    db = get_db()
    supplier = db.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if supplier is None:
        abort(404)
    # Only allow deletion if the supplier belongs to the current user
    if supplier['user_id'] is not None and supplier['user_id'] != session.get('user_id'):
        abort(403)
    # Delete associated files
    for filename in (supplier['photo_filename'], supplier['catalog_filename']):
        if filename:
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(path):
                os.remove(path)
    # Delete potential QR codes generated
    qr_prefixes = [f"whatsapp_qr_{supplier_id}", f"wechat_qr_{supplier_id}"]
    for fname in os.listdir(app.config['UPLOAD_FOLDER']):
        for prefix in qr_prefixes:
            if fname.startswith(prefix):
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                except FileNotFoundError:
                    pass
    db.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
    db.commit()
    return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Register a new user.

    Registration is only allowed in two situations:
      1. When no users currently exist in the database (initial setup).  The
         account created during this phase should correspond to the
         administrator email configured in ``ADMIN_EMAIL``.
      2. When the logged-in user is the administrator.  The admin can create
         additional user profiles for others.

    All other attempts result in a 403 error.
    """
    db = get_db()
    # Count existing users
    count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c']
    # If users exist and the current user is not admin, deny access
    if count > 0 and not is_admin():
        abort(403)

    error = ''
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm', '').strip()
        if not username or not password:
            error = "Nom d'utilisateur et mot de passe requis."
        elif password != confirm:
            error = "Les mots de passe ne correspondent pas."
        else:
            existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if existing:
                error = "Ce nom d'utilisateur est déjà utilisé."
            else:
                password_hash = generate_password_hash(password)
                db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash)
                )
                db.commit()
                return redirect(url_for('login'))
    return render_template_string(REGISTER_TEMPLATE, error=error)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Log in an existing user.

    On successful authentication, the user_id and username are stored in the
    session.  If the user attempted to access a protected page, they are
    redirected back to that page via the ``next`` parameter.
    """
    error = ''
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        row = db.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        if row and check_password_hash(row['password_hash'], password):
            session['user_id'] = row['id']
            session['username'] = row['username']
            next_page = request.args.get('next')
            # Safety: prevent open redirect by ensuring next_page is relative
            if next_page and not next_page.startswith('/'):
                next_page = None
            return redirect(next_page or url_for('index'))
        else:
            error = "Nom d'utilisateur ou mot de passe incorrect."
    # Determine whether to display the registration link.  Allow only when
    # there are no users in the system (fresh install).
    db = get_db()
    count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c']
    allow_register = (count == 0)
    return render_template_string(LOGIN_TEMPLATE, error=error, allow_register=allow_register)


@app.route('/logout')
@login_required
def logout():
    """Log out the current user by clearing the session and redirecting to login."""
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Admin user management routes
# ---------------------------------------------------------------------------

@app.route('/admin/users')
@login_required
def list_users():
    """List all registered users for the administrator.

    Displays a table of user email addresses with actions to modify passwords.
    Accessible only to the admin.
    """
    if not is_admin():
        abort(403)
    db = get_db()
    users = db.execute("SELECT id, username FROM users ORDER BY username").fetchall()
    return render_template_string(USERS_TEMPLATE, users=users)


@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id: int):
    """Allow the administrator to change a user's password."""
    if not is_admin():
        abort(403)
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    error = ''
    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm', '').strip()
        if not password:
            error = "Le mot de passe est requis."
        elif password != confirm:
            error = "Les mots de passe ne correspondent pas."
        else:
            password_hash = generate_password_hash(password)
            db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, user_id)
            )
            db.commit()
            return redirect(url_for('list_users'))
    return render_template_string(USER_EDIT_TEMPLATE, error=error)


###############################################################################
# Main entry point
###############################################################################

def main():
    """Entry point for running the Flask application."""
    # Initialise database if necessary
    init_db()
    # Start the development server
    app.run(debug=True, port=5000)


if __name__ == '__main__':
    main()

###############################################################################
# PowerShell usage instructions
###############################################################################

# The following comments provide a guide on how to run this application on
# Windows using PowerShell.  To get started:
#
# 1. Ensure that Python 3.x is installed on your system.  You can verify
#    this by opening PowerShell and running `python --version`.  If
#    Python is not installed, download it from https://www.python.org/ and
#    install it, making sure to tick the option that adds Python to
#    your PATH.
#
# 2. Create a new folder for the project and copy `supplier_app.py` into
#    it.  Then open PowerShell and navigate to that folder using the
#    `cd` command, for example:
#       cd C:\Users\VotreNom\Documents\salon_suppliers
#
# 3. (Optional but recommended) Create a virtual environment so that
#    dependencies remain isolated.  Run the following commands:
#       python -m venv venv
#       .\venv\Scripts\Activate.ps1
#    You should see the prompt change to indicate the environment is
#    active.
#
# 4. Install the required Python packages.  The application depends on
#    `flask` for the web framework and `qrcode[pil]` for QR code
#    generation.  Install them with pip:
#       pip install flask qrcode[pil]
#    The ``qrcode`` package documentation shows that installation via
#    pip is as simple as ``pip install qrcode``【617998091682678†L101-L115】.  The
#    optional ``[pil]`` extra pulls in Pillow for image handling.
#
# 5. Start the application by running the script:
#       python supplier_app.py
#    On startup the script will create the SQLite database file
#    `suppliers.db` and the `uploads` directory if they do not already
#    exist.  You should see output similar to:
#       * Serving Flask app 'supplier_app'
#       * Debug mode: on
#       * Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)
#
# 6. Open your web browser and navigate to `http://localhost:5000/`.
#    You can now add suppliers, upload photos and catalogue files,
#    generate QR codes for WhatsApp and WeChat links, edit records,
#    search suppliers by category and delete them when necessary.
#
# 7. When you are finished, stop the server by pressing `Ctrl+C` in the
#    PowerShell window.  To deactivate the virtual environment, run
#    `deactivate`.
#
# The application stores all data locally within the project folder.
# Moving or deleting the `suppliers.db` file or the `uploads` folder
# will reset the data.  Consider backing up these files if you plan to
# retain the supplier records.