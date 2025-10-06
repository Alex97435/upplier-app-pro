"""
supplier_app.py - Version Postgres
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, redirect, url_for, send_from_directory, abort,
    render_template_string, session, flash, jsonify
)

import requests
import time
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode


###############################################################################
# Configuration
###############################################################################

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'tradeLinkPro-secret-key')

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, "uploads"))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'pdf', 'doc', 'docx'}

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

ADMIN_EMAIL = 'alexandrebetonpro@gmail.com'


###############################################################################
# Database helpers - POSTGRES VERSION
###############################################################################

def get_db():
    """Return a Postgres database connection."""
    database_url = os.environ.get('POSTGRES_DATABASE_URL')
    if not database_url:
        raise ValueError("POSTGRES_DATABASE_URL n'est pas définie")
    
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    return conn


def init_db():
    """Initialize Postgres database tables."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Table suppliers
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            contact TEXT,
            whatsapp_link TEXT,
            wechat_link TEXT,
            rating TEXT,
            photo_filename TEXT,
            catalog_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER
        )
    """)
    
    # Table users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    
    conn.commit()
    cursor.close()
    conn.close()


###############################################################################
# Authentication utilities
###############################################################################

def login_required(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return func(*args, **kwargs)
    return wrapped


def is_admin() -> bool:
    return session.get('username') == ADMIN_EMAIL


###############################################################################
# Azure Document Intelligence route
###############################################################################

@app.route('/analyze_card', methods=['POST'])
@login_required
def analyze_card():
    # Force l'utilisation de Tesseract.js côté client
    # En retournant une erreur, le frontend utilisera automatiquement l'OCR local
    return jsonify({'error': 'Utilisation OCR local'}), 500


###############################################################################
# Initialize database on startup
###############################################################################

try:
    init_db()
except Exception as e:
    print(f"Erreur initialisation DB: {e}")


###############################################################################
# Utility functions
###############################################################################

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file_storage):
    if not file_storage or file_storage.filename == '':
        return ''
    filename = secure_filename(file_storage.filename)
    if not allowed_file(filename):
        return ''
    basename, ext = os.path.splitext(filename)
    counter = 1
    unique_filename = filename
    while os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)):
        unique_filename = f"{basename}_{counter}{ext}"
        counter += 1
    file_storage.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
    return unique_filename


def generate_qr_code(data: str, filename: str) -> str:
    if not data:
        return ''
    qr_img = qrcode.make(data)
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
# Templates (unchanged)
###############################################################################

INDEX_TEMPLATE = r"""
<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TradeLinkPro</title>
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
            flex-direction: column;
            gap: 12px;
            margin-bottom: 20px;
        }
        .search-form {
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
        .filters-section {
            background-color: #15202b;
            border-radius: 8px;
            padding: 12px;
        }
        .filter-toggle {
            color: #799bb9;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            font-weight: 500;
            margin-bottom: 12px;
        }
        .filter-toggle:hover {
            color: #9fb9d9;
        }
        .filters-content {
            display: none;
        }
        .filters-content.active {
            display: block;
        }
        .filter-group {
            margin-bottom: 12px;
        }
        .filter-group-title {
            color: #a0b0c0;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 6px;
        }
        .filter-options {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .filter-checkbox {
            display: flex;
            align-items: center;
            gap: 4px;
            padding: 4px 10px;
            background-color: #273a4b;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            transition: background-color 0.2s;
        }
        .filter-checkbox:hover {
            background-color: #344b65;
        }
        .filter-checkbox input[type="checkbox"] {
            cursor: pointer;
        }
        .filter-actions {
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }
        .filter-btn {
            padding: 6px 14px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
        }
        .filter-btn-apply {
            background-color: #5b7bda;
            color: #fff;
        }
        .filter-btn-reset {
            background-color: #495867;
            color: #dcdcdc;
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
            right: 90px;
            cursor: pointer;
        }
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
            <form method="get" action="{{ url_for('index') }}" class="search-form">
                <input type="text" name="search" placeholder="Rechercher un fournisseur..." value="{{ search_query }}" autocomplete="off">
                <button type="submit"><i class="fa fa-search"></i></button>
            </form>
            
            <div class="filters-section">
                <div class="filter-toggle" onclick="toggleFilters()">
                    <i class="fa fa-filter"></i>
                    <span>Filtres avancés</span>
                    <i class="fa fa-chevron-down" id="filter-arrow"></i>
                </div>
                
                <div class="filters-content" id="filters-content">
                    <form method="get" action="{{ url_for('index') }}" id="filter-form">
                        <input type="hidden" name="search" value="{{ search_query }}">
                        
                        <div class="filter-group">
                            <div class="filter-group-title">Notation</div>
                            <div class="filter-options">
                                <label class="filter-checkbox">
                                    <input type="checkbox" name="rating" value="green" {% if 'green' in selected_ratings %}checked{% endif %}>
                                    <span>✓ Vert (Super)</span>
                                </label>
                                <label class="filter-checkbox">
                                    <input type="checkbox" name="rating" value="yellow" {% if 'yellow' in selected_ratings %}checked{% endif %}>
                                    <span>⚠ Jaune (Moyen)</span>
                                </label>
                                <label class="filter-checkbox">
                                    <input type="checkbox" name="rating" value="red" {% if 'red' in selected_ratings %}checked{% endif %}>
                                    <span>✗ Rouge (Mauvais)</span>
                                </label>
                            </div>
                        </div>
                        
                        <div class="filter-group">
                            <div class="filter-group-title">Catégories</div>
                            <div class="filter-options">
                                {% for cat in all_categories %}
                                <label class="filter-checkbox">
                                    <input type="checkbox" name="category" value="{{ cat }}" {% if cat in selected_categories %}checked{% endif %}>
                                    <span>{{ cat.capitalize() }}</span>
                                </label>
                                {% endfor %}
                            </div>
                        </div>
                        
                        <div class="filter-group">
                            <div class="filter-group-title">Trier par</div>
                            <select name="sort" style="background-color: #273a4b; color: #f5f5f5; border: 1px solid #374d65; border-radius: 6px; padding: 6px; width: 100%;">
                                <option value="" {% if not sort_key %}selected{% endif %}>Date d'ajout (récent)</option>
                                <option value="name" {% if sort_key == 'name' %}selected{% endif %}>Nom (A-Z)</option>
                                <option value="category" {% if sort_key == 'category' %}selected{% endif %}>Catégorie</option>
                                <option value="rating" {% if sort_key == 'rating' %}selected{% endif %}>Notation (meilleurs d'abord)</option>
                            </select>
                        </div>
                        
                        <div class="filter-actions">
                            <button type="submit" class="filter-btn filter-btn-apply">
                                <i class="fa fa-check"></i> Appliquer
                            </button>
                            <button type="button" class="filter-btn filter-btn-reset" onclick="resetFilters()">
                                <i class="fa fa-undo"></i> Réinitialiser
                            </button>
                        </div>
                    </form>
                </div>
            </div>
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
                    <span class="date">{{ s['created_at'].strftime('%Y-%m-%d') if s['created_at'] else '' }}</span>
                    <a href="{{ url_for('delete_supplier', supplier_id=s['id']) }}" class="delete-btn" title="Supprimer" onclick="return confirm('Supprimer ce fournisseur ?');"><i class="fa fa-trash"></i></a>
                    <a href="{{ url_for('view_supplier', supplier_id=s['id']) }}" class="delete-btn" title="Détails"><i class="fa fa-eye"></i></a>
                    <a href="{{ url_for('edit_supplier', supplier_id=s['id']) }}" class="delete-btn" title="Modifier"><i class="fa fa-edit"></i></a>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    <div class="fab-btn fab-add" title="Ajouter un fournisseur">
        <a href="{{ url_for('add_supplier') }}" style="color: inherit; text-decoration: none;">
            <i class="fa fa-plus fa-lg"></i>
        </a>
    </div>
    <div class="fab-btn fab-scan" onclick="startScanner()" title="Scanner un QR code">
        <i class="fa fa-qrcode fa-lg"></i>
    </div>
    <div id="scanModal">
        <div id="qr-reader"></div>
        <button class="close-btn" onclick="closeScanner()">&times;</button>
    </div>
    <script src="https://unpkg.com/html5-qrcode@2.2.1/html5-qrcode.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/tesseract.js@2/dist/tesseract.min.js"></script>
    <script>
    let html5QrcodeScanner = null;

    function parseContact(decodedText) {
        let name = '';
        let phone = '';
        let whatsappLink = '';
        let wechatLink = '';
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
        // WeChat link
        else if (/u\.wechat\.com|weixin\.qq\.com/i.test(text)) {
            wechatLink = text;
        }
        // WhatsApp link - AMÉLIORATION : extraire le numéro si possible
        else if (/wa\.me\//i.test(text)) {
            const numMatch = text.match(/wa\.me\/([0-9]+)/i);
            if (numMatch) {
                phone = numMatch[1];
                whatsappLink = `https://wa.me/${numMatch[1]}`;
            } else {
                // Lien WhatsApp type /message/CODE sans numéro extractible
                whatsappLink = text;
            }
        }
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
                    if (!name && segment && isNaN(segment) && !segment.includes('http') && !segment.includes('/') ) {
                        name = segment;
                    } else if (!phone && segment && !isNaN(segment)) {
                        phone = segment;
                    }
                }
            }
        }
        return { name, phone, whatsappLink, wechatLink };
    }

    function onScanSuccess(decodedText, decodedResult) {
        const result = parseContact(decodedText);
        html5QrcodeScanner.stop().then(() => {
            html5QrcodeScanner.clear();
            html5QrcodeScanner = null;
            let url = '{{ url_for('add_supplier') }}';
            const params = [];
            if (result.name) params.push('name=' + encodeURIComponent(result.name));
            if (result.phone) {
                params.push('contact=' + encodeURIComponent(result.phone));
            }
            if (result.whatsappLink) {
                params.push('whatsapp=' + encodeURIComponent(result.whatsappLink));
            }
            if (result.wechatLink) {
                params.push('wechat=' + encodeURIComponent(result.wechatLink));
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
    
    function toggleFilters() {
        const content = document.getElementById('filters-content');
        const arrow = document.getElementById('filter-arrow');
        
        if (content.classList.contains('active')) {
            content.classList.remove('active');
            arrow.style.transform = 'rotate(0deg)';
        } else {
            content.classList.add('active');
            arrow.style.transform = 'rotate(180deg)';
        }
    }
    
    function resetFilters() {
        // Décocher toutes les checkboxes
        document.querySelectorAll('#filter-form input[type="checkbox"]').forEach(cb => {
            cb.checked = false;
        });
        // Réinitialiser le tri
        document.querySelector('#filter-form select[name="sort"]').value = '';
        // Soumettre le formulaire
        document.getElementById('filter-form').submit();
    }
    
    // Ouvrir automatiquement les filtres s'il y en a d'actifs
    document.addEventListener('DOMContentLoaded', function() {
        const hasActiveFilters = {{ 'true' if (selected_ratings or selected_categories) else 'false' }};
        if (hasActiveFilters) {
            toggleFilters();
        }
    });
    </script>
</body>
</html>
"""

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
        input[readonly] {
            background-color: #1a2633;
            cursor: pointer;
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
        .link-container {
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .link-container input {
            flex: 1;
        }
        .link-btn {
            padding: 8px 12px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            color: white;
            font-size: 14px;
            display: flex;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
        }
        .link-btn.whatsapp {
            background: #25D366;
        }
        .link-btn.wechat {
            background: #09B83E;
        }
        .link-btn.edit {
            background: #5b7bda;
            min-width: 40px;
            justify-content: center;
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
            <div class="link-container">
                <input type="text" id="whatsapp" name="whatsapp" value="{{ supplier['whatsapp_link'] if supplier else (pre_whatsapp if pre_whatsapp else '') }}" placeholder="https://wa.me/Numéro" readonly>
                <button type="button" class="link-btn edit" onclick="toggleEdit('whatsapp')" title="Modifier">
                    <i class="fa fa-edit"></i>
                </button>
                <button type="button" id="openWhatsApp" class="link-btn whatsapp" onclick="openLink('whatsapp')" style="display: none;">
                    <i class="fab fa-whatsapp"></i> Ouvrir
                </button>
            </div>

            <label for="wechat">Lien WeChat :</label>
            <div class="link-container">
                <input type="text" id="wechat" name="wechat" value="{{ supplier['wechat_link'] if supplier else (pre_wechat if pre_wechat else '') }}" placeholder="Lien WeChat" readonly>
                <button type="button" class="link-btn edit" onclick="toggleEdit('wechat')" title="Modifier">
                    <i class="fa fa-edit"></i>
                </button>
                <button type="button" id="openWeChat" class="link-btn wechat" onclick="openLink('wechat')" style="display: none;">
                    <i class="fab fa-weixin"></i> Ouvrir
                </button>
            </div>

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
            <label for="business_card">Carte de visite :</label>
            <input type="file" id="business_card" accept="image/*" onchange="uploadCard()">
            <button type="button" class="scan-btn" onclick="triggerCardInput()"><i class="fa fa-id-card"></i> Scanner carte</button>
            {% endif %}

            <div class="actions">
                <button type="submit" class="btn btn-primary">{{ 'Mettre à jour' if supplier else 'Ajouter' }}</button>
                <a href="{{ url_for('index') }}" class="btn btn-secondary">Annuler</a>
            </div>
        </form>
        {% if not supplier %}
        <button class="scan-btn" onclick="openScanModal()"><i class="fa fa-qrcode"></i> Scanner QR pour pré-remplir</button>
        {% endif %}
    </div>
    <div id="scanModal">
        <div id="qr-reader"></div>
        <button class="close-btn" onclick="closeScanModal()">&times;</button>
    </div>
    <script src="https://unpkg.com/html5-qrcode@2.2.1/html5-qrcode.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/tesseract.js@2/dist/tesseract.min.js"></script>
    <script>
    let qrScanner = null;

    function parseContact(decodedText) {
        let name = '';
        let phone = '';
        let whatsappLink = '';
        let wechatLink = '';
        const text = decodedText.trim();
        
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
        // WeChat link
        else if (/u\.wechat\.com|weixin\.qq\.com/i.test(text)) {
            wechatLink = text;
        }
        // WhatsApp link - AMÉLIORATION : extraire le numéro
        else if (/wa\.me\//i.test(text)) {
            const numMatch = text.match(/wa\.me\/([0-9]+)/i);
            if (numMatch) {
                phone = numMatch[1];
                whatsappLink = `https://wa.me/${numMatch[1]}`;
            } else {
                whatsappLink = text;
            }
        }
        
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
                    if (!name && segment && isNaN(segment) && !segment.includes('http') && !segment.includes('/')) {
                        name = segment;
                    } else if (!phone && segment && !isNaN(segment)) {
                        phone = segment;
                    }
                }
            }
        }
        return { name, phone, whatsappLink, wechatLink };
    }

    function onScanSuccess(decodedText, decodedResult) {
        const result = parseContact(decodedText);
        if (result.name) {
            document.getElementById('name').value = result.name;
        }
        if (result.phone) {
            document.getElementById('contact').value = result.phone;
        }
        if (result.whatsappLink) {
            document.getElementById('whatsapp').value = result.whatsappLink;
        }
        if (result.wechatLink) {
            document.getElementById('wechat').value = result.wechatLink;
        }
        
        updateLinkButtons();
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

    async function uploadCard() {
        const input = document.getElementById('business_card');
        if (!input || input.files.length === 0) {
            alert('Veuillez sélectionner une image de carte de visite.');
            return;
        }
        const file = input.files[0];
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
                    if (data.name) document.getElementById('name').value = data.name;
                    if (data.phone) document.getElementById('contact').value = data.phone;
                    success = true;
                }
            }
        } catch (err) {
            console.warn('Serveur Azure OCR indisponible :', err);
        }
        if (!success) {
            try {
                const { data: { text } } = await Tesseract.recognize(file, 'eng+fra', { logger: m => console.log(m) });
                const lines = text.split(/\n+/).map(l => l.trim()).filter(Boolean);
                let foundName = '';
                let foundPhone = '';
                
                for (const line of lines) {
                    if (!foundPhone) {
                        const intlMatch = line.match(/\+\d{1,4}[\s\-]?\d{2,4}[\s\-]?\d{2,4}[\s\-]?\d{2,4}[\s\-]?\d{0,4}/);
                        if (intlMatch) {
                            foundPhone = intlMatch[0].replace(/[\s\-]/g, '');
                            continue;
                        }
                        const phoneMatch = line.match(/(\d[\d\s\-]{8,15}\d)/);
                        if (phoneMatch) {
                            foundPhone = phoneMatch[1].replace(/[\s\-]/g, '');
                        }
                    }
                }
                
                for (const line of lines) {
                    if (!foundName) {
                        if (line.length < 5 || /\d/.test(line)) continue;
                        const nameMatch = line.match(/^([A-ZÀ-Ö][a-zà-ö]+(?:\s+[A-ZÀ-Ö][a-zà-ö]+)+)$/);
                        if (nameMatch) {
                            foundName = nameMatch[1];
                            continue;
                        }
                        const words = line.split(/\s+/).filter(w => w.length > 2 && /^[A-Za-zÀ-ÖØ-öø-ÿ]+$/.test(w));
                        if (words.length >= 2) {
                            foundName = words.slice(0, 2).join(' ');
                        }
                    }
                    if (foundName && foundPhone) break;
                }
                
                if (foundName) document.getElementById('name').value = foundName;
                if (foundPhone) document.getElementById('contact').value = foundPhone;
                
                updateLinkButtons();
                
                if (!foundName && !foundPhone) {
                    alert('Impossible de lire la carte. Réessayez avec une photo plus nette.');
                }
            } catch (err) {
                console.error('Erreur OCR locale :', err);
                alert('Impossible d\'extraire les informations de la carte.');
            }
        }
        if (cardBtn) {
            cardBtn.disabled = false;
            cardBtn.innerHTML = '<i class="fa fa-id-card"></i> Scanner carte';
        }
    }

    function triggerCardInput() {
        const input = document.getElementById('business_card');
        if (input) {
            input.click();
        }
    }
    
    // Basculer entre lecture seule et éditable
    function toggleEdit(fieldName) {
        const input = document.getElementById(fieldName);
        if (!input) return;
        
        if (input.hasAttribute('readonly')) {
            input.removeAttribute('readonly');
            input.focus();
            input.style.backgroundColor = '#15202b';
        } else {
            input.setAttribute('readonly', 'readonly');
            input.style.backgroundColor = '#1a2633';
        }
    }
    
    // Ouvrir les liens WhatsApp/WeChat
    function openLink(type) {
        const input = document.getElementById(type);
        if (input && input.value) {
            window.open(input.value, '_blank');
        }
    }
    
    // Afficher/cacher les boutons "Ouvrir" selon le contenu
    function updateLinkButtons() {
        const whatsappInput = document.getElementById('whatsapp');
        const wechatInput = document.getElementById('wechat');
        const whatsappBtn = document.getElementById('openWhatsApp');
        const wechatBtn = document.getElementById('openWeChat');
        
        if (whatsappInput && whatsappBtn) {
            whatsappBtn.style.display = whatsappInput.value ? 'flex' : 'none';
        }
        if (wechatInput && wechatBtn) {
            wechatBtn.style.display = wechatInput.value ? 'flex' : 'none';
        }
    }
    
    // Initialisation au chargement
    document.addEventListener('DOMContentLoaded', function() {
        updateLinkButtons();
        
        const whatsappInput = document.getElementById('whatsapp');
        const wechatInput = document.getElementById('wechat');
        
        if (whatsappInput) {
            whatsappInput.addEventListener('input', updateLinkButtons);
            // Cliquer sur le champ en readonly ouvre le lien
            whatsappInput.addEventListener('click', function() {
                if (this.hasAttribute('readonly') && this.value) {
                    openLink('whatsapp');
                }
            });
        }
        if (wechatInput) {
            wechatInput.addEventListener('input', updateLinkButtons);
            // Cliquer sur le champ en readonly ouvre le lien
            wechatInput.addEventListener('click', function() {
                if (this.hasAttribute('readonly') && this.value) {
                    openLink('wechat');
                }
            });
        }
    });
    </script>
</body>
</html>
"""

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
        <a href="{{ url_for('login') }}" class="link">Déjà inscrit ? Se connecter</a>
    </div>
</body>
</html>
"""

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
        <div class="info">
            <label>Contacts :</label>
            {% if supplier['whatsapp_link'] %}
                <a href="{{ supplier['whatsapp_link'] }}" target="_blank" style="color: #25D366; margin-right: 15px; text-decoration: none; font-size: 18px;" title="Ouvrir WhatsApp">
                    <i class="fab fa-whatsapp"></i> WhatsApp
                </a>
            {% endif %}
            {% if supplier['wechat_link'] %}
                <a href="{{ supplier['wechat_link'] }}" target="_blank" style="color: #09B83E; text-decoration: none; font-size: 18px;" title="Ouvrir WeChat">
                    <i class="fab fa-weixin"></i> WeChat
                </a>
            {% endif %}
            {% if not supplier['whatsapp_link'] and not supplier['wechat_link'] %}
                -
            {% endif %}
        </div>
        <div class="info badges">
            {% if supplier['rating'] == 'green' %}
                <span class="badge rating-green"><i class="fa fa-star"></i> Top</span>
            {% elif supplier['rating'] == 'yellow' %}
                <span class="badge rating-yellow">Moyen</span>
            {% elif supplier['rating'] == 'red' %}
                <span class="badge rating-red">Mauvais</span>
            {% endif %}
            <span class="badge category">{{ supplier['category'] }}</span>
            {% if supplier['created_at'] %}<span class="badge">{{ supplier['created_at'].strftime('%Y-%m-%d') if supplier['created_at'] else '' }}</span>{% endif %}
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
    search_query = request.args.get('search', '').strip()
    sort_key = request.args.get('sort', '').strip()
    
    # Récupérer les filtres multiples
    selected_ratings = request.args.getlist('rating')  # Liste des couleurs cochées
    selected_categories = request.args.getlist('category')  # Liste des catégories cochées
    
    conn = get_db()
    cursor = conn.cursor()
    user_id = session['user_id']
    
    sql = "SELECT * FROM suppliers WHERE user_id = %s"
    params = [user_id]
    
    # Filtre de recherche
    if search_query:
        like_query = f'%{search_query}%'
        sql += " AND (name ILIKE %s OR category ILIKE %s OR description ILIKE %s)"
        params.extend([like_query, like_query, like_query])
    
    # Filtre par notation (couleurs)
    if selected_ratings:
        placeholders = ','.join(['%s'] * len(selected_ratings))
        sql += f" AND rating IN ({placeholders})"
        params.extend(selected_ratings)
    
    # Filtre par catégories
    if selected_categories:
        placeholders = ','.join(['%s'] * len(selected_categories))
        sql += f" AND category IN ({placeholders})"
        params.extend(selected_categories)
    
    # Tri
    if sort_key == 'name':
        sql += " ORDER BY name ASC"
    elif sort_key == 'category':
        sql += " ORDER BY category ASC, name ASC"
    elif sort_key == 'rating':
        sql += " ORDER BY CASE rating WHEN 'green' THEN 1 WHEN 'yellow' THEN 2 WHEN 'red' THEN 3 ELSE 4 END, created_at DESC, name ASC"
    else:
        sql += " ORDER BY created_at DESC, name ASC"
    
    cursor.execute(sql, tuple(params))
    rows = cursor.fetchall()
    total = len(rows)
    username = session.get('username', 'Utilisateur')
    
    cursor.close()
    conn.close()
    
    return render_template_string(
        INDEX_TEMPLATE,
        suppliers=rows,
        search_query=search_query,
        sort_key=sort_key,
        selected_ratings=selected_ratings,
        selected_categories=selected_categories,
        all_categories=CATEGORIES,
        total_suppliers=total,
        username=username,
        is_admin=is_admin()
    )


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_supplier():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        contact = request.form.get('contact', '').strip()
        whatsapp = request.form.get('whatsapp', '').strip()
        wechat = request.form.get('wechat', '').strip()
        rating = request.form.get('rating', '').strip()

        photo_filename = save_upload(request.files.get('photo'))
        catalog_filename = save_upload(request.files.get('catalog'))

        conn = get_db()
        cursor = conn.cursor()
        user_id = session['user_id']
        
        cursor.execute(
            """INSERT INTO suppliers (name, category, description, contact, whatsapp_link, wechat_link, rating, photo_filename, catalog_filename, user_id) 
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (name, category, description, contact, whatsapp, wechat, rating, photo_filename, catalog_filename, user_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        return redirect(url_for('index'))
    
    pre_name = request.args.get('name', '').strip()
    pre_contact = request.args.get('contact', '').strip()
    pre_whatsapp = request.args.get('whatsapp', '').strip()
    pre_wechat = request.args.get('wechat', '').strip()
    username = session.get('username', 'Utilisateur')
    
    return render_template_string(
        ADD_EDIT_TEMPLATE,
        supplier=None,
        pre_name=pre_name,
        pre_contact=pre_contact,
        pre_whatsapp=pre_whatsapp,
        pre_wechat=pre_wechat,
        categories=CATEGORIES,
        username=username
    )


@app.route('/supplier/<int:supplier_id>')
@login_required
def view_supplier(supplier_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM suppliers WHERE id = %s", (supplier_id,))
    supplier = cursor.fetchone()
    cursor.close()
    
    if supplier is None:
        conn.close()
        abort(404)
    
    if supplier['user_id'] is not None and supplier['user_id'] != session.get('user_id'):
        conn.close()
        abort(403)

    whatsapp_qr = ''
    wechat_qr = ''
    
    whatsapp_data = supplier['whatsapp_link']
    if whatsapp_data:
        if whatsapp_data.isdigit():
            whatsapp_link = f"https://wa.me/{whatsapp_data}"
        else:
            whatsapp_link = whatsapp_data
        whatsapp_qr = generate_qr_code(whatsapp_link, f"whatsapp_qr_{supplier_id}.png")

    wechat_data = supplier['wechat_link']
    if wechat_data:
        wechat_qr = generate_qr_code(wechat_data, f"wechat_qr_{supplier_id}.png")

    conn.close()
    
    return render_template_string(
        DETAIL_TEMPLATE,
        supplier=supplier,
        whatsapp_qr=whatsapp_qr,
        wechat_qr=wechat_qr
    )


@app.route('/edit/<int:supplier_id>', methods=['GET', 'POST'])
@login_required
def edit_supplier(supplier_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM suppliers WHERE id = %s", (supplier_id,))
    supplier = cursor.fetchone()
    
    if supplier is None:
        cursor.close()
        conn.close()
        abort(404)
    
    if supplier['user_id'] is not None and supplier['user_id'] != session.get('user_id'):
        cursor.close()
        conn.close()
        abort(403)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        contact = request.form.get('contact', '').strip()
        whatsapp = request.form.get('whatsapp', '').strip()
        wechat = request.form.get('wechat', '').strip()
        rating = request.form.get('rating', '').strip()

        new_photo = request.files.get('photo')
        photo_filename = supplier['photo_filename']
        if new_photo and new_photo.filename:
            if photo_filename:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], photo_filename)
                if os.path.exists(old_path):
                    os.remove(old_path)
            photo_filename = save_upload(new_photo)

        new_catalog = request.files.get('catalog')
        catalog_filename = supplier['catalog_filename']
        if new_catalog and new_catalog.filename:
            if catalog_filename:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], catalog_filename)
                if os.path.exists(old_path):
                    os.remove(old_path)
            catalog_filename = save_upload(new_catalog)

        cursor.execute(
            """UPDATE suppliers
               SET name = %s, category = %s, description = %s, contact = %s, whatsapp_link = %s, wechat_link = %s, rating = %s,
                   photo_filename = %s, catalog_filename = %s
               WHERE id = %s""",
            (name, category, description, contact, whatsapp, wechat, rating, photo_filename, catalog_filename, supplier_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        return redirect(url_for('index'))
    
    username = session.get('username', 'Utilisateur')
    cursor.close()
    conn.close()
    
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
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM suppliers WHERE id = %s", (supplier_id,))
    supplier = cursor.fetchone()
    
    if supplier is None:
        cursor.close()
        conn.close()
        abort(404)
    
    if supplier['user_id'] is not None and supplier['user_id'] != session.get('user_id'):
        cursor.close()
        conn.close()
        abort(403)
    
    for filename in (supplier['photo_filename'], supplier['catalog_filename']):
        if filename:
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(path):
                os.remove(path)
    
    qr_prefixes = [f"whatsapp_qr_{supplier_id}", f"wechat_qr_{supplier_id}"]
    for fname in os.listdir(app.config['UPLOAD_FOLDER']):
        for prefix in qr_prefixes:
            if fname.startswith(prefix):
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                except FileNotFoundError:
                    pass
    
    cursor.execute("DELETE FROM suppliers WHERE id = %s", (supplier_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS c FROM users")
    count = cursor.fetchone()['c']
    
    if count > 0 and not is_admin():
        cursor.close()
        conn.close()
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
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            existing = cursor.fetchone()
            if existing:
                error = "Ce nom d'utilisateur est déjà utilisé."
            else:
                password_hash = generate_password_hash(password)
                cursor.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                    (username, password_hash)
                )
                conn.commit()
                cursor.close()
                conn.close()
                return redirect(url_for('login'))
    
    cursor.close()
    conn.close()
    return render_template_string(REGISTER_TEMPLATE, error=error)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = ''
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (username,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if row and check_password_hash(row['password_hash'], password):
            session['user_id'] = row['id']
            session['username'] = row['username']
            next_page = request.args.get('next')
            if next_page and not next_page.startswith('/'):
                next_page = None
            return redirect(next_page or url_for('index'))
        else:
            error = "Nom d'utilisateur ou mot de passe incorrect."
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS c FROM users")
    count = cursor.fetchone()['c']
    cursor.close()
    conn.close()
    
    allow_register = (count == 0)
    return render_template_string(LOGIN_TEMPLATE, error=error, allow_register=allow_register)


@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/admin/users')
@login_required
def list_users():
    if not is_admin():
        abort(403)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM users ORDER BY username")
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template_string(USERS_TEMPLATE, users=users)


@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id: int):
    if not is_admin():
        abort(403)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    
    if user is None:
        cursor.close()
        conn.close()
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
            cursor.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (password_hash, user_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            return redirect(url_for('list_users'))
    
    cursor.close()
    conn.close()
    return render_template_string(USER_EDIT_TEMPLATE, error=error)


if __name__ == '__main__':
    app.run(debug=True, port=5000)
