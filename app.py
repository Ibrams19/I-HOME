from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
import os
import secrets
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', '191e6c143b195840f3a65d0584a6641407fc8e251918ef169d2124a61a624ad0')

# Configuration Cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True
)

# ==================== CONFIGURATIONS ====================

# CSRF
csrf = CSRFProtect()
csrf.init_app(app)
app.config['WTF_CSRF_ENABLED'] = False
app.config['WTF_CSRF_SECRET_KEY'] = os.environ.get('CSRF_SECRET_KEY', secrets.token_hex(32))
app.config['WTF_CSRF_TIME_LIMIT'] = 3600

# Logs
if not os.path.exists('logs'):
    os.makedirs('logs')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Base de données
database_url = os.environ.get('DATABASE_URL')
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    logger.info("✅ Connexion à PostgreSQL (mode production)")
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
    logger.info("⚠️ Mode développement : utilisation de SQLite locale")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ====================== MODÈLES ======================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), nullable=True)
    password = db.Column(db.String(200), nullable=False)
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    is_owner = db.Column(db.Boolean, default=False)
    is_broker = db.Column(db.Boolean, default=False)
    agency_name = db.Column(db.String(100), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    free_listings_used = db.Column(db.Integer, default=0)
    subscription_type = db.Column(db.String(20), default='free')
    subscription_end = db.Column(db.DateTime, nullable=True)
    rating = db.Column(db.Float, default=0)
    total_ratings = db.Column(db.Integer, default=0)
    privacy_accepted = db.Column(db.Boolean, default=False)
    privacy_accepted_date = db.Column(db.DateTime, nullable=True)
    cookies_consent = db.Column(db.String(20), nullable=True)

    @property
    def can_publish(self):
        return self.is_owner or self.is_broker

class Listing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    property_type = db.Column(db.String(50), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)
    neighborhood = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    price_type = db.Column(db.String(20), default='month')
    description = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(300), default='/static/default.jpg')
    images = db.Column(db.Text, nullable=True)
    lat = db.Column(db.Float, default=14.6937)
    lng = db.Column(db.Float, default=-17.4441)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    views = db.Column(db.Integer, default=0)
    is_paid = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=False)
    is_taken = db.Column(db.Boolean, default=False)
    taken_date = db.Column(db.DateTime, nullable=True)
    is_free_global = db.Column(db.Boolean, default=False)
    payment_id = db.Column(db.String(100), nullable=True)
    payment_date = db.Column(db.DateTime, nullable=True)
    payment_amount = db.Column(db.Integer, default=700)
    auteur = db.relationship('User', backref='annonces', foreign_keys=[user_id])

class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey('listing.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='favorites')
    listing = db.relationship('Listing', backref='favorited_by')

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reviewed_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewer = db.relationship('User', foreign_keys=[reviewer_id])
    reviewed = db.relationship('User', foreign_keys=[reviewed_id])

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(300), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='notifications')

class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('listing.id'), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    last_message = db.Column(db.Text, nullable=True)
    last_message_date = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    listing = db.relationship('Listing', backref='conversations')
    owner = db.relationship('User', foreign_keys=[owner_id], backref='owner_conversations')
    tenant = db.relationship('User', foreign_keys=[tenant_id], backref='tenant_conversations')
    messages = db.relationship('Message', backref='conversation', lazy=True, cascade='all, delete-orphan')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship('User', foreign_keys=[sender_id])

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

# ====================== FONCTIONS ======================

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def create_wave_payment(amount, phone_number, listing_id):
    try:
        payment_id = f"WAVE_SIM_{listing_id}_{int(datetime.now().timestamp())}"
        return {'success': True, 'payment_id': payment_id}
    except Exception as e:
        logger.error(f"Erreur paiement Wave: {e}")
        return {'success': False, 'error': str(e)}

def send_email_notification(to_email, subject, body_html):
    try:
        smtp_user = os.environ.get('EMAIL_USER', '')
        smtp_password = os.environ.get('EMAIL_PASSWORD', '')
        
        if not smtp_user or not smtp_password:
            print("❌ Email non configuré")
            return False
        
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html'))
        
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Email envoyé à {to_email}")
        return True
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False

# ====================== ROUTES ======================

@app.route('/')
def index():
    recent_annonces = Listing.query.filter_by(is_active=True, is_taken=False).order_by(Listing.date_posted.desc()).limit(6).all()
    return render_template('index.html', recent_annonces=recent_annonces)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        user_type = request.form.get('user_type', 'tenant')
        
        if not username or not password:
            flash("Veuillez remplir tous les champs obligatoires.", "danger")
            return redirect(url_for('register'))
        
        if len(password) < 8:
            flash("Le mot de passe doit contenir au moins 8 caractères.", "danger")
            return redirect(url_for('register'))
        
        if not any(c.isalpha() for c in password):
            flash("Le mot de passe doit contenir au moins une lettre.", "danger")
            return redirect(url_for('register'))
        
        if not any(c.isdigit() for c in password):
            flash("Le mot de passe doit contenir au moins un chiffre.", "danger")
            return redirect(url_for('register'))
        
        if password != confirm_password:
            flash("Les mots de passe ne correspondent pas.", "danger")
            return redirect(url_for('register'))
        
        if email == '':
            email = None
        
        is_owner = (user_type == 'owner')
        is_broker = (user_type == 'broker')
        agency_name = request.form.get('agency_name', '') if is_broker else None

        if User.query.filter_by(username=username).first():
            flash("Ce nom d'utilisateur existe déjà.", "danger")
            return redirect(url_for('register'))
        
        if email and User.query.filter_by(email=email).first():
            flash("Cet email est déjà utilisé.", "danger")
            return redirect(url_for('register'))
        
        new_user = User(
            username=username,
            email=email,
            password=generate_password_hash(password),
            is_owner=is_owner,
            is_broker=is_broker,
            agency_name=agency_name
        )
        db.session.add(new_user)
        db.session.commit()
        
        login_user(new_user)
        session['can_publish'] = new_user.can_publish
        session['is_broker'] = new_user.is_broker
        session['is_owner'] = new_user.is_owner
        
        if new_user.can_publish:
            flash("Compte créé avec succès ! Veuillez compléter votre profil.", "success")
            return redirect(url_for('profile'))
        else:
            flash("Compte créé avec succès ! Vous pouvez maintenant consulter les annonces.", "success")
            return redirect(url_for('listings'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username_or_email = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username_or_email or not password:
            flash("Veuillez entrer votre nom d'utilisateur/email et votre mot de passe.", "danger")
            return redirect(url_for('login'))
        
        # Chercher par nom d'utilisateur OU par email
        user = User.query.filter(
            (User.username == username_or_email) | (User.email == username_or_email)
        ).first()
        
        if not user:
            flash("Ce nom d'utilisateur ou email n'existe pas.", "danger")
            return redirect(url_for('login'))
        
        if check_password_hash(user.password, password):
            login_user(user)
            session['can_publish'] = user.can_publish
            session['is_broker'] = user.is_broker
            session['is_owner'] = user.is_owner
            flash(f"Bienvenue {user.username} !", "success")
            
            if user.can_publish and (not user.phone_number or not user.email):
                flash("Veuillez compléter votre profil avec votre email et numéro WhatsApp.", "warning")
                return redirect(url_for('profile'))
            
            return redirect(url_for('index'))
        else:
            flash("Mot de passe incorrect.", "danger")
            return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    
    if not user or user.reset_token_expiry < datetime.utcnow():
        flash("Le lien de réinitialisation est invalide ou a expiré.", "danger")
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if not password:
            flash("Veuillez entrer un mot de passe.", "danger")
        elif password != confirm_password:
            flash("Les mots de passe ne correspondent pas.", "danger")
        elif len(password) < 6:
            flash("Le mot de passe doit contenir au moins 6 caractères.", "danger")
        else:
            user.password = generate_password_hash(password)
            user.reset_token = None
            user.reset_token_expiry = None
            db.session.commit()
            flash("Votre mot de passe a été réinitialisé avec succès.", "success")
            return redirect(url_for('login'))
    
    return render_template('reset_password.html', token=token)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    # Pour les propriétaires et courtiers : formulaire complet
    if current_user.can_publish:
        profil_complet = current_user.phone_number and current_user.email
        
        if request.method == 'POST':
            phone_number = request.form.get('phone_number', '').strip()
            email = request.form.get('email', '').strip()
            
            if not phone_number:
                flash("Le numéro WhatsApp est obligatoire pour publier des annonces.", "danger")
                return redirect(url_for('profile'))
            
            if not email:
                flash("L'adresse email est obligatoire pour publier des annonces.", "danger")
                return redirect(url_for('profile'))
            
            current_user.phone_number = phone_number
            current_user.email = email
            
            if current_user.is_broker:
                agency_name = request.form.get('agency_name', '').strip()
                current_user.agency_name = agency_name
            
            db.session.commit()
            flash("Profil mis à jour avec succès ! Vous pouvez maintenant publier des annonces.", "success")
            return redirect(url_for('publish'))
        
        return render_template('profile.html', user=current_user, profil_complet=profil_complet)
    
    # Pour les locataires : page simplifiée pour changer le mot de passe uniquement
    else:
        if request.method == 'POST':
            # Changement de mot de passe pour locataire
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            if not check_password_hash(current_user.password, current_password):
                flash("Mot de passe actuel incorrect.", "danger")
                return redirect(url_for('profile'))
            
            if not new_password:
                flash("Veuillez entrer un nouveau mot de passe.", "danger")
                return redirect(url_for('profile'))
            
            if new_password != confirm_password:
                flash("Les nouveaux mots de passe ne correspondent pas.", "danger")
                return redirect(url_for('profile'))
            
            if len(new_password) < 6:
                flash("Le mot de passe doit contenir au moins 6 caractères.", "danger")
                return redirect(url_for('profile'))
            
            current_user.password = generate_password_hash(new_password)
            db.session.commit()
            flash("✅ Votre mot de passe a été modifié avec succès.", "success")
            return redirect(url_for('profile'))
        
        return render_template('tenant_profile.html', user=current_user)

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.username != 'admin':
        flash("Accès non autorisé.", "danger")
        return redirect(url_for('index'))
    
    # Statistiques
    total_users = User.query.count()
    total_listings = Listing.query.count()
    active_listings = Listing.query.filter_by(is_active=True, is_taken=False).count()
    total_messages = Message.query.count()
    total_conversations = Conversation.query.count()
    
    # Derniers utilisateurs
    recent_users = User.query.order_by(User.id.desc()).limit(10).all()
    
    # Dernières annonces
    recent_listings = Listing.query.order_by(Listing.date_posted.desc()).limit(10).all()
    
    # Utilisateurs par type
    owners_count = User.query.filter_by(is_owner=True).count()
    brokers_count = User.query.filter_by(is_broker=True).count()
    tenants_count = User.query.filter_by(is_owner=False, is_broker=False).count()
    
    return render_template('admin_dashboard.html',
                          total_users=total_users,
                          total_listings=total_listings,
                          active_listings=active_listings,
                          total_messages=total_messages,
                          total_conversations=total_conversations,
                          recent_users=recent_users,
                          recent_listings=recent_listings,
                          owners_count=owners_count,
                          brokers_count=brokers_count,
                          tenants_count=tenants_count)

@app.route('/create-admin-now')
def create_admin_now():
    from werkzeug.security import generate_password_hash
    
    with app.app_context():
        # Vérifier si l'admin existe déjà
        admin = User.query.filter_by(username='admin').first()
        
        if admin:
            return f"""
            <div style="text-align: center; padding: 50px;">
                <h2>⚠️ Admin existe déjà</h2>
                <p>Nom d'utilisateur: <strong>{admin.username}</strong></p>
                <p>Email: <strong>{admin.email}</strong></p>
                <p>Mot de passe: <strong>Admin123!</strong> (par défaut)</p>
                <a href="/login">🔑 Se connecter</a>
            </div>
            """
        else:
            # Créer l'admin
            new_admin = User(
                username='admin',
                email='admin@i-home.sn',
                password=generate_password_hash('Admin123!'),
                is_owner=True,
                is_broker=False,
                phone_number='+221 71 150 42 43'
            )
            db.session.add(new_admin)
            db.session.commit()
            
            return f"""
            <div style="text-align: center; padding: 50px; background: #d4fc79;">
                <h2 style="color: green;">✅ Admin créé avec succès !</h2>
                <p><strong>👤 Nom d'utilisateur :</strong> admin</p>
                <p><strong>🔑 Mot de passe :</strong> Admin123!</p>
                <p><strong>📧 Email :</strong> admin@i-home.sn</p>
                <a href="/login" style="background: blue; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                    🔑 Se connecter
                </a>
            </div>
            """

@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    
    if not check_password_hash(current_user.password, current_password):
        flash("Mot de passe actuel incorrect.", "danger")
        return redirect(url_for('profile'))
    
    if not new_password:
        flash("Veuillez entrer un nouveau mot de passe.", "danger")
        return redirect(url_for('profile'))
    
    if new_password != confirm_password:
        flash("Les nouveaux mots de passe ne correspondent pas.", "danger")
        return redirect(url_for('profile'))
    
    if len(new_password) < 6:
        flash("Le mot de passe doit contenir au moins 6 caractères.", "danger")
        return redirect(url_for('profile'))
    
    current_user.password = generate_password_hash(new_password)
    db.session.commit()
    flash("✅ Votre mot de passe a été modifié avec succès.", "success")
    return redirect(url_for('profile'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()
        
        if user:
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expiry = datetime.utcnow() + timedelta(hours=24)
            db.session.commit()
            reset_link = url_for('reset_password', token=token, _external=True)
            flash("Un email de réinitialisation a été envoyé.", "success")
            flash(f"Lien de test : {reset_link}", "info")
        else:
            flash("Aucun compte associé à cet email.", "danger")
        
        return redirect(url_for('login'))
    
    return render_template('forgot_password.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Déconnexion réussie. À bientôt !", "info")
    return redirect(url_for('index'))

@app.route('/publish', methods=['GET', 'POST'])
@login_required
def publish():
    if not current_user.can_publish:
        flash("Seuls les propriétaires et courtiers peuvent publier des annonces.", "danger")
        return redirect(url_for('listings'))
    
    if not current_user.phone_number or not current_user.email:
        flash("Veuillez d'abord compléter votre profil avec votre email et votre numéro WhatsApp.", "warning")
        return redirect(url_for('profile', next='publish'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        property_type = request.form.get('property_type')
        transaction_type = request.form.get('transaction_type')
        neighborhood = request.form.get('neighborhood', '').strip()
        price = int(request.form.get('price', 0))
        price_type = request.form.get('price_type', 'month')
        description = request.form.get('description', '').strip()
        
        lat_str = request.form.get('lat', '')
        lat = float(lat_str) if lat_str and lat_str.strip() else 14.6937
        lng_str = request.form.get('lng', '')
        lng = float(lng_str) if lng_str and lng_str.strip() else -17.4441

        image_url = '/static/default.jpg'
        images_list = []
        
        if 'images' in request.files:
            files = request.files.getlist('images')
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    try:
                        upload_result = cloudinary.uploader.upload(file)
                        img_url = upload_result['secure_url']
                        images_list.append(img_url)
                        if image_url == '/static/default.jpg':
                            image_url = img_url
                    except Exception as e:
                        logger.error(f"Erreur upload Cloudinary: {e}")
                        flash("Erreur lors de l'upload de l'image.", "danger")
        
        images_str = ','.join(images_list) if images_list else None

        # Phase de lancement : TOUTES les annonces sont gratuites
        new_listing = Listing(
            user_id=current_user.id,
            title=title,
            property_type=property_type,
            transaction_type=transaction_type,
            neighborhood=neighborhood,
            price=price,
            price_type=price_type,
            description=description,
            image_url=image_url,
            images=images_str,
            lat=lat,
            lng=lng,
            is_paid=True,      # Gratuit pendant le lancement
            is_active=True,    # Directement actif
            is_free_global=True
        )
        db.session.add(new_listing)
        db.session.commit()
        
        flash("✅ Votre annonce a été publiée avec succès ! (Phase de lancement - 100% gratuit)", "success")
        return redirect(url_for('listing_detail', listing_id=new_listing.id))
        
    return render_template('publish.html')

@app.route('/manual-payment/<int:listing_id>')
@login_required
def manual_payment(listing_id):
    annonce = Listing.query.get_or_404(listing_id)
    
    if annonce.user_id != current_user.id:
        flash("Non autorisé.", "danger")
        return redirect(url_for('listings'))
    
    return render_template('manual_payment.html', annonce=annonce, amount=700)

@app.route('/confirm-manual-payment/<int:listing_id>', methods=['POST'])
@login_required
def confirm_manual_payment(listing_id):
    annonce = Listing.query.get_or_404(listing_id)
    
    if annonce.user_id != current_user.id:
        flash("Non autorisé.", "danger")
        return redirect(url_for('listings'))
    
    # Créer une notification pour l'admin
    admin = User.query.filter_by(username='admin').first()
    if admin:
        notification = Notification(
            user_id=admin.id,
            title="💰 Nouveau paiement manuel à vérifier",
            message=f"{current_user.username} a signalé un paiement pour l'annonce '{annonce.title}'",
            link=url_for('listing_detail', listing_id=annonce.id)
        )
        db.session.add(notification)
        db.session.commit()
    
    flash("✅ Merci ! Nous avons bien reçu votre demande. Votre annonce sera activée après vérification du paiement (24h max).", "success")
    return redirect(url_for('my_listings'))

@app.route('/payment/<int:listing_id>', methods=['GET', 'POST'])
@login_required
def payment_page(listing_id):
    annonce = Listing.query.get_or_404(listing_id)
    
    if annonce.user_id != current_user.id:
        flash("Vous n'êtes pas autorisé.", "danger")
        return redirect(url_for('listings'))
    
    if annonce.is_paid and annonce.is_active:
        flash("Cette annonce est déjà en ligne.", "info")
        return redirect(url_for('listing_detail', listing_id=annonce.id))
    
    if request.method == 'POST':
        phone_number = request.form.get('phone_number')
        if not phone_number:
            flash("Veuillez entrer votre numéro Wave.", "danger")
            return redirect(url_for('payment_page', listing_id=listing_id))
        
        result = create_wave_payment(700, phone_number, listing_id)
        if result['success']:
            annonce.payment_id = result['payment_id']
            db.session.commit()
            return redirect(url_for('payment_pending', listing_id=listing_id, payment_id=result['payment_id']))
        else:
            flash("Erreur lors du paiement.", "danger")
    
    return render_template('payment.html', annonce=annonce, amount=700)

@app.route('/payment/pending/<int:listing_id>/<payment_id>')
def payment_pending(listing_id, payment_id):
    annonce = Listing.query.get_or_404(listing_id)
    return render_template('payment_pending.html', annonce=annonce, payment_id=payment_id)

@app.route('/payment/simulate/<int:listing_id>')
@login_required
def simulate_payment(listing_id):
    annonce = Listing.query.get_or_404(listing_id)
    if annonce.user_id != current_user.id:
        flash("Non autorisé.", "danger")
        return redirect(url_for('listings'))
    
    annonce.is_paid = True
    annonce.is_active = True
    annonce.payment_date = datetime.utcnow()
    db.session.commit()
    flash("✅ (SIMULATION) Paiement confirmé ! Votre annonce est en ligne.", "success")
    return redirect(url_for('listing_detail', listing_id=annonce.id))

@app.route('/payment/check/<int:listing_id>')
def payment_check(listing_id):
    annonce = Listing.query.get_or_404(listing_id)
    return jsonify({'status': 'completed' if annonce.is_paid and annonce.is_active else 'pending'})

@app.route('/my-listings')
@login_required
def my_listings():
    if not current_user.can_publish:
        flash("Accès réservé aux propriétaires et courtiers.", "danger")
        return redirect(url_for('index'))
    
    annonces = Listing.query.filter_by(user_id=current_user.id).order_by(Listing.date_posted.desc()).all()
    user = User.query.get(current_user.id)
    
    return render_template('my_listings.html', 
                          annonces=annonces, 
                          user=user)

@app.route('/subscription')
@login_required
def subscription():
    if not current_user.can_publish:
        flash("Accès réservé aux propriétaires et courtiers.", "danger")
        return redirect(url_for('index'))
    
    # Phase de lancement : tout est gratuit, pas de compteur d'annonces
    return render_template('subscription.html', user=current_user)

@app.route('/subscribe/<plan>', methods=['POST'])
@login_required
def subscribe(plan):
    if not current_user.can_publish:
        return jsonify({'error': 'Non autorisé'}), 403
    
    # Phase de lancement : abonnements désactivés
    flash("🎉 Phase de lancement : tous les services sont GRATUITS ! Les abonnements seront disponibles prochainement.", "info")
    return redirect(url_for('subscription'))

@app.route('/cancel-subscription')
@login_required
def cancel_subscription():
    current_user.subscription_type = 'free'
    current_user.subscription_end = None
    db.session.commit()
    flash("Votre abonnement a été annulé.", "info")
    return redirect(url_for('my_listings'))

@app.route('/listings')
def listings():
    page = request.args.get('page', 1, type=int)
    per_page = 12
    
    property_type = request.args.get('type')
    transaction_type = request.args.get('transaction')
    neighborhood = request.args.get('neighborhood', '').strip()
    min_price = request.args.get('min_price', type=int)
    max_price = request.args.get('max_price', type=int)

    query = Listing.query.filter_by(is_active=True, is_taken=False)

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

    all_listings = query.all()
    
    def get_priority(listing):
        user = listing.auteur
        if user.subscription_type == 'pro' or user.subscription_type == 'annual':
            return 0  # Plus haute priorité (Pro et Annuel)
        elif user.subscription_type == 'premium':
            return 1
        elif user.subscription_type == 'basic':
            return 2
        else:
            return 3
    
    sorted_listings = sorted(all_listings, key=get_priority)
    
    total = len(sorted_listings)
    start = (page - 1) * per_page
    end = start + per_page
    annonces = sorted_listings[start:end]
    
    pagination = {
        'page': page,
        'per_page': per_page,
        'total': total,
        'pages': (total + per_page - 1) // per_page,
        'has_prev': page > 1,
        'has_next': end < total,
        'prev_num': page - 1 if page > 1 else None,
        'next_num': page + 1 if end < total else None,
        'iter_pages': lambda: range(1, ((total + per_page - 1) // per_page) + 1)
    }
    
    return render_template('listings.html', annonces=annonces, pagination=pagination)

@app.route('/listings/type/<type>')
def listings_by_type(type):
    if type == 'appartement':
        property_types = ['appartement']
        title = "Appartements"
        icon = "fa-building"
    elif type == 'appartement_meuble':
        property_types = ['appartement_meuble']
        title = "Appartements meublés"
        icon = "fa-building"
    elif type == 'chambre':
        property_types = ['chambre']
        title = "Chambres simples"
        icon = "fa-bed"
    elif type == 'chambre_meublee':
        property_types = ['chambre_meublee']
        title = "Chambres meublées"
        icon = "fa-bed"
    elif type == 'studio':
        property_types = ['studio']
        title = "Studios"
        icon = "fa-city"
    elif type == 'studio_meuble':
        property_types = ['studio_meuble']
        title = "Studios meublés"
        icon = "fa-city"
    elif type == 'magasin':
        property_types = ['magasin']
        title = "Magasins"
        icon = "fa-store"
    elif type == 'depot':
        property_types = ['depot']
        title = "Dépôts / Entrepôts"
        icon = "fa-warehouse"
    else:
        return redirect(url_for('listings'))
    
    query = Listing.query.filter_by(is_active=True, is_taken=False)
    query = query.filter(Listing.property_type.in_(property_types))
    annonces = query.order_by(Listing.date_posted.desc()).all()
    
    return render_template('listings_by_type.html', annonces=annonces, title=title, icon=icon, type=type)

@app.route('/listing/<int:listing_id>')
@login_required
def listing_detail(listing_id):
    annonce = Listing.query.get_or_404(listing_id)
    annonce.views += 1
    db.session.commit()
    return render_template('detail.html', annonce=annonce)

@app.route('/favorite/<int:listing_id>', methods=['POST'])
@login_required
def add_favorite(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    existing = Favorite.query.filter_by(user_id=current_user.id, listing_id=listing_id).first()
    if existing:
        db.session.delete(existing)
        flash("Annonce retirée des favoris.", "info")
    else:
        favorite = Favorite(user_id=current_user.id, listing_id=listing_id)
        db.session.add(favorite)
        flash("Annonce ajoutée aux favoris.", "success")
    
    db.session.commit()
    return redirect(request.referrer or url_for('listings'))

@app.route('/favorites')
@login_required
def favorites():
    favorites = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()
    return render_template('favorites.html', favorites=favorites)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/cgu')
def cgu():
    now = datetime.utcnow()
    return render_template('cgu.html', now=now)

@app.route('/mentions-legales')
def mentions_legales():
    return render_template('mentions_legales.html')

@app.route('/politique-confidentialite')
def politique_confidentialite():
    return render_template('politique_confidentialite.html')

@app.route('/cookies-consent', methods=['POST'])
def cookies_consent():
    data = request.get_json()
    consent = data.get('consent')
    if current_user.is_authenticated:
        current_user.cookies_consent = consent
        db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/privacy-consent', methods=['POST'])
def privacy_consent():
    if current_user.is_authenticated:
        current_user.privacy_accepted = True
        current_user.privacy_accepted_date = datetime.utcnow()
        db.session.commit()
    return jsonify({'status': 'ok'})

# ====================== MESSAGERIE ======================

@app.route('/start-conversation/<int:listing_id>')
@login_required
def start_conversation(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    if current_user.can_publish and listing.user_id == current_user.id:
        conversations = Conversation.query.filter_by(listing_id=listing_id, owner_id=current_user.id).order_by(Conversation.last_message_date.desc()).all()
        return render_template('conversations.html', conversations=conversations, listing=listing)
    else:
        conversation = Conversation.query.filter_by(listing_id=listing_id, tenant_id=current_user.id).first()
        if not conversation:
            conversation = Conversation(
                listing_id=listing_id,
                owner_id=listing.user_id,
                tenant_id=current_user.id
            )
            db.session.add(conversation)
            db.session.commit()
        return redirect(url_for('chat', conversation_id=conversation.id))

@app.route('/chat/<int:conversation_id>')
@login_required
def chat(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)
    
    if current_user.id not in [conversation.owner_id, conversation.tenant_id]:
        flash("Non autorisé.", "danger")
        return redirect(url_for('listings'))
    
    for msg in conversation.messages:
        if msg.sender_id != current_user.id and not msg.is_read:
            msg.is_read = True
    db.session.commit()
    
    return render_template('chat.html', conversation=conversation, listing=conversation.listing)

@app.route('/send_message/<int:conversation_id>', methods=['POST'])
@login_required
def send_message(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)
    
    if current_user.id not in [conversation.owner_id, conversation.tenant_id]:
        flash("Non autorisé.", "danger")
        return redirect(url_for('listings'))
    
    content = request.form.get('content', '').strip()
    if not content:
        flash("Message vide.", "danger")
        return redirect(url_for('chat', conversation_id=conversation_id))
    
    message = Message(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=content
    )
    conversation.last_message = content[:100]
    conversation.last_message_date = datetime.utcnow()
    
    db.session.add(message)
    db.session.commit()
    
    if conversation.owner_id == current_user.id:
        destinataire = conversation.tenant
    else:
        destinataire = conversation.owner
    
    if destinataire.email:
        subject = f"📬 Nouveau message sur I-HOME - {conversation.listing.title}"
        body = f"""
        <h2>Nouveau message sur I-HOME</h2>
        <p><strong>De :</strong> {current_user.username}</p>
        <p><strong>Annonce :</strong> {conversation.listing.title}</p>
        <p><strong>Message :</strong></p>
        <p style="background: #f0f0f0; padding: 15px; border-radius: 10px;">{content}</p>
        <p><a href="{url_for('chat', conversation_id=conversation.id, _external=True)}" style="background: #2563eb; color: white; padding: 10px 20px; text-decoration: none; border-radius: 50px;">Répondre maintenant</a></p>
        <hr>
        <p style="font-size: 12px; color: gray;">I-HOME - Plateforme immobilière du Sénégal</p>
        """
        send_email_notification(destinataire.email, subject, body)
    
    return redirect(url_for('chat', conversation_id=conversation.id))

@app.route('/my-conversations')
@login_required
def my_conversations():
    if current_user.can_publish:
        conversations = Conversation.query.filter_by(owner_id=current_user.id).order_by(Conversation.last_message_date.desc()).all()
    else:
        conversations = Conversation.query.filter_by(tenant_id=current_user.id).order_by(Conversation.last_message_date.desc()).all()
    
    return render_template('my_conversations.html', conversations=conversations)

@app.route('/get_messages/<int:conversation_id>')
@login_required
def get_messages(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)
    
    if current_user.id not in [conversation.owner_id, conversation.tenant_id]:
        return jsonify({'error': 'Non autorisé'}), 403
    
    messages = []
    for msg in conversation.messages:
        messages.append({
            'id': msg.id,
            'sender_id': msg.sender_id,
            'sender_name': msg.sender.username,
            'content': msg.content,
            'created_at': msg.created_at.strftime('%H:%M'),
            'is_mine': msg.sender_id == current_user.id
        })
    
    return jsonify(messages)

@app.route('/api/unread-count')
@login_required
def unread_count():
    if current_user.can_publish:
        conversations = Conversation.query.filter_by(owner_id=current_user.id).all()
    else:
        conversations = Conversation.query.filter_by(tenant_id=current_user.id).all()
    
    unread_count = 0
    for conv in conversations:
        for msg in conv.messages:
            if not msg.is_read and msg.sender_id != current_user.id:
                unread_count += 1
    
    return jsonify({'count': unread_count})

@app.route('/api/recent-messages')
@login_required
def recent_messages():
    if current_user.can_publish:
        conversations = Conversation.query.filter_by(owner_id=current_user.id).order_by(Conversation.last_message_date.desc()).limit(5).all()
    else:
        conversations = Conversation.query.filter_by(tenant_id=current_user.id).order_by(Conversation.last_message_date.desc()).limit(5).all()
    
    messages = []
    for conv in conversations:
        last_msg = conv.messages[-1] if conv.messages else None
        if last_msg:
            is_unread = not last_msg.is_read and last_msg.sender_id != current_user.id
            messages.append({
                'conversation_id': conv.id,
                'listing_title': conv.listing.title,
                'sender_name': last_msg.sender.username,
                'content': last_msg.content[:100],
                'time': last_msg.created_at.strftime('%d/%m %H:%M'),
                'unread': is_unread
            })
    
    return jsonify({'messages': messages})

@app.route('/send-email-to-user/<int:user_id>/<int:listing_id>', methods=['POST'])
@login_required
def send_email_to_user(user_id, listing_id):
    destinataire = User.query.get_or_404(user_id)
    annonce = Listing.query.get_or_404(listing_id)
    
    sender_email = request.form.get('sender_email', current_user.email)
    subject = request.form.get('subject', '')
    message = request.form.get('message', '')
    
    if not subject or not message:
        flash("Veuillez remplir tous les champs.", "danger")
        return redirect(url_for('listing_detail', listing_id=listing_id))
    
    if not sender_email:
        sender_email = current_user.email if current_user.email else "non-renseigné@i-home.sn"
    
    conversation = Conversation.query.filter_by(listing_id=annonce.id, owner_id=annonce.user_id, tenant_id=current_user.id).first()
    if not conversation:
        conversation = Conversation(
            listing_id=annonce.id,
            owner_id=annonce.user_id,
            tenant_id=current_user.id
        )
        db.session.add(conversation)
        db.session.commit()
    
    auto_message = Message(
        conversation_id=conversation.id,
        sender_id=current_user.id,
        content=f"[Email envoyé] {message[:200]}..."
    )
    db.session.add(auto_message)
    conversation.last_message = auto_message.content[:100]
    conversation.last_message_date = datetime.utcnow()
    db.session.commit()
    
    if destinataire.email:
        conversation_url = url_for('chat', conversation_id=conversation.id, _external=True)
        
        body_destinataire = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ padding: 20px; background: #f9fafb; }}
                .footer {{ text-align: center; padding: 15px; font-size: 12px; color: gray; }}
                .button {{ background: #2563eb; color: white; padding: 10px 20px; text-decoration: none; border-radius: 50px; }}
                .info {{ background: #e0e7ff; padding: 10px; border-radius: 10px; margin: 15px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>📬 Nouveau message I-HOME</h2>
                </div>
                <div class="content">
                    <p><strong>👤 De :</strong> {current_user.username} (<a href="mailto:{sender_email}">{sender_email}</a>)</p>
                    <p><strong>🏠 Annonce :</strong> <a href="{url_for('listing_detail', listing_id=annonce.id, _external=True)}">{annonce.title}</a></p>
                    <p><strong>📝 Objet :</strong> {subject}</p>
                    <div class="info">
                        <strong>💬 Message :</strong><br>
                        {message.replace(chr(10), '<br>')}
                    </div>
                    <p>Vous pouvez répondre directement à : <a href="mailto:{sender_email}">{sender_email}</a></p>
                    <p style="margin-top: 20px;">
                        <a href="{conversation_url}" class="button" style="background: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 50px; display: inline-block;">
                            📱 Répondre sur I-HOME
                        </a>
                    </p>
                </div>
                <div class="footer">
                    <p>I-HOME - Plateforme immobilière du Sénégal</p>
                </div>
            </div>
        </body>
        </html>
        """
        send_email_notification(destinataire.email, subject, body_destinataire)
        flash("✅ Votre message a été envoyé avec succès !", "success")
    else:
        flash("❌ Le destinataire n'a pas d'email renseigné.", "danger")
    
    return redirect(url_for('listing_detail', listing_id=listing_id))

# ====================== ROUTES ANNONCES PRISES ======================

@app.route('/mark-as-taken/<int:listing_id>', methods=['POST'])
@login_required
def mark_as_taken(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    if listing.user_id != current_user.id:
        flash("Vous n'êtes pas autorisé à modifier cette annonce.", "danger")
        return redirect(url_for('listings'))
    
    if listing.is_taken:
        flash("Cette annonce est déjà marquée comme prise.", "warning")
        return redirect(url_for('my_listings'))
    
    listing.is_taken = True
    listing.is_active = False
    listing.taken_date = datetime.utcnow()
    db.session.commit()
    
    flash(f"✅ L'annonce '{listing.title}' a été marquée comme prise. Elle n'apparaît plus dans les recherches.", "success")
    return redirect(url_for('my_listings'))

@app.route('/reactivate-listing/<int:listing_id>', methods=['POST'])
@login_required
def reactivate_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    if listing.user_id != current_user.id:
        flash("Vous n'êtes pas autorisé.", "danger")
        return redirect(url_for('listings'))
    
    listing.is_taken = False
    listing.is_active = True
    listing.taken_date = None
    db.session.commit()
    
    flash(f"✅ L'annonce '{listing.title}' a été réactivée.", "success")
    return redirect(url_for('my_listings'))

# ====================== GESTION DES ERREURS ======================

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

@app.errorhandler(403)
def forbidden(e):
    flash("Erreur de sécurité. Veuillez réessayer.", "danger")
    return redirect(url_for('index'))

@app.errorhandler(401)
def unauthorized(e):
    flash("Vous devez être connecté pour accéder à cette page.", "warning")
    return redirect(url_for('login'))

@app.before_request
def log_request_info():
    if request.method == 'POST':
        logger.info(f"Requête POST sur {request.endpoint}")

@app.after_request
def log_response_info(response):
    if response.status_code >= 400:
        logger.warning(f"Réponse {response.status_code} sur {request.endpoint}")
    return response

@app.route('/admin/logs')
@login_required
def view_logs():
    if current_user.username != 'admin':
        flash("Accès non autorisé.", "danger")
        return redirect(url_for('index'))
    
    try:
        with open('logs/app.log', 'r', encoding='utf-8') as f:
            logs = f.read().split('\n')[-100:]
        return render_template('logs.html', logs=logs)
    except:
        return render_template('logs.html', logs=["Aucun log disponible"])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)