from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkeylocapp2026')

# ==================== CONFIGURATION BASE DE DONNÉES ====================
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
if app.config['SQLALCHEMY_DATABASE_URI'] and app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 Mo max

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ====================== MODÈLES ======================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_owner = db.Column(db.Boolean, default=False)

class Listing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    property_type = db.Column(db.String(50), nullable=False)      # studio, appartement, chambre
    transaction_type = db.Column(db.String(20), nullable=False)   # louer, acheter
    neighborhood = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(300), default='/static/default.jpg')
    lat = db.Column(db.Float, default=14.6937)
    lng = db.Column(db.Float, default=-17.4441)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Création des tables
with app.app_context():
    db.create_all()

# ====================== ROUTES ======================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        is_owner = 'is_owner' in request.form

        if User.query.filter_by(username=username).first():
            flash("Ce nom d'utilisateur existe déjà.", "danger")
        else:
            new_user = User(username=username, password=password, is_owner=is_owner)
            db.session.add(new_user)
            db.session.commit()
            flash("Compte créé avec succès !", "success")
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            session['is_owner'] = user.is_owner
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
                try:
                    img = Image.open(filepath)
                    img.thumbnail((800, 600))
                    img.save(filepath)
                except:
                    pass
                image_url = f'/uploads/{filename}'

        new_listing = Listing(
            user_id=current_user.id,
            title=title,
            property_type=property_type,
            transaction_type=transaction_type,
            neighborhood=neighborhood,
            price=price,
            description=description,
            image_url=image_url,
            lat=lat,
            lng=lng
        )
        db.session.add(new_listing)
        db.session.commit()

        flash("Annonce publiée avec succès !", "success")
        return redirect(url_for('listings'))

    return render_template('publish.html')

@app.route('/listings')
def listings():
    property_type = request.args.get('type')
    transaction_type = request.args.get('transaction')
    neighborhood = request.args.get('neighborhood', '').strip()
    min_price = request.args.get('min_price', type=int)
    max_price = request.args.get('max_price', type=int)

    query = Listing.query

    if property_type:
        query = query.filter_by(property_type=property_type)
    if transaction_type:
        query = query.filter_by(transaction_type=transaction_type)
    if neighborhood:
        query = query.filter(Listing.neighborhood.ilike(f"%{neighborhood}%"))
    if min_price is not None:
        query = query.filter(Listing.price >= min_price)
    if max_price is not None:
        query = query.filter(Listing.price <= max_price)

    annonces = query.order_by(Listing.date_posted.desc()).all()

    return render_template('listings.html', annonces=annonces)

@app.route('/listing/<int:listing_id>')
def listing_detail(listing_id):
    annonce = Listing.query.get_or_404(listing_id)
    return render_template('detail.html', annonce=annonce)

# Servir les images uploadées
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)