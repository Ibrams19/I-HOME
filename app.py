from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "supersecretkeylocapp2026"
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 Mo max

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

GOOGLE_MAPS_API_KEY = "TA_CLE_API_GOOGLE"  # ← Remplace par ta clé !

def get_db():
    db = sqlite3.connect('instance/database.db')
    db.row_factory = sqlite3.Row
    return db

# Création tables + colonne lat/lng pour la carte
with get_db() as db:
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_owner BOOLEAN DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            property_type TEXT,
            transaction_type TEXT,
            neighborhood TEXT,
            price INTEGER,
            description TEXT,
            image_url TEXT,
            lat REAL DEFAULT 14.6937,   -- coordonnées par défaut Dakar
            lng REAL DEFAULT -17.4441,
            date_posted TEXT
        );
    ''')

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return User(user['id'], user['username']) if user else None

# Route pour servir les images uploadées
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        is_owner = 'is_owner' in request.form

        try:
            with get_db() as db:
                db.execute("INSERT INTO users (username, password, is_owner) VALUES (?, ?, ?)",
                          (username, password, is_owner))
                db.commit()
            flash("Compte créé ! Tu peux maintenant te connecter.", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Ce nom d'utilisateur existe déjà.", "danger")
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if user and check_password_hash(user['password'], password):
                login_user(User(user['id'], user['username']))
                session['is_owner'] = bool(user['is_owner'])
                flash("Connexion réussie !", "success")
                return redirect(url_for('listings'))
            flash("Identifiants incorrects.", "danger")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Déconnexion réussie.", "info")
    return redirect(url_for('index'))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

@app.route('/publish', methods=['GET', 'POST'])
@login_required
def publish():
    if not session.get('is_owner'):
        flash("Seuls les propriétaires peuvent publier une annonce.", "danger")
        return redirect(url_for('listings'))

    if request.method == 'POST':
        title = request.form['title']
        property_type = request.form['property_type']
        transaction_type = request.form['transaction_type']
        neighborhood = request.form['neighborhood']
        price = int(request.form['price'])
        description = request.form['description']
        lat = float(request.form.get('lat', 14.6937))
        lng = float(request.form.get('lng', -17.4441))

        image_url = '/static/default.jpg'
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                # Redimensionner pour optimiser
                img = Image.open(filepath)
                img.thumbnail((800, 600))
                img.save(filepath)
                image_url = f'/uploads/{filename}'

        with get_db() as db:
            db.execute('''
                INSERT INTO listings 
                (user_id, title, property_type, transaction_type, neighborhood, price, description, image_url, lat, lng, date_posted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (current_user.id, title, property_type, transaction_type, neighborhood, 
                  price, description, image_url, lat, lng, datetime.now().strftime("%Y-%m-%d")))
            db.commit()

        flash("Annonce publiée avec succès !", "success")
        return redirect(url_for('listings'))

    return render_template('publish.html', google_maps_key=None)

@app.route('/listings')
def listings():
    property_type = request.args.get('type')
    transaction_type = request.args.get('transaction')
    neighborhood = request.args.get('neighborhood', '').strip()
    min_price = request.args.get('min_price', type=int)
    max_price = request.args.get('max_price', type=int)

    query = "SELECT * FROM listings WHERE 1=1"
    params = []

    if property_type:
        query += " AND property_type = ?"
        params.append(property_type)
    if transaction_type:
        query += " AND transaction_type = ?"
        params.append(transaction_type)
    if neighborhood:
        query += " AND neighborhood LIKE ?"
        params.append(f"%{neighborhood}%")
    if min_price is not None:
        query += " AND price >= ?"
        params.append(min_price)
    if max_price is not None:
        query += " AND price <= ?"
        params.append(max_price)

    query += " ORDER BY date_posted DESC"

    with get_db() as db:
        annonces = db.execute(query, params).fetchall()

    return render_template('listings.html', 
                         annonces=annonces,
                         google_maps_key=None,
                         filters={
                             'type': property_type,
                             'transaction': transaction_type,
                             'neighborhood': neighborhood,
                             'min_price': min_price,
                             'max_price': max_price
                         })

@app.route('/listing/<int:listing_id>')
def listing_detail(listing_id):
    with get_db() as db:
        annonce = db.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not annonce:
        flash("Annonce introuvable.", "danger")
        return redirect(url_for('listings'))
    return render_template('detail.html', annonce=annonce, google_maps_key=None)

if __name__ == '__main__':
    os.makedirs('instance', exist_ok=True)
    app.run(debug=True)