# init_db.py
from app import app, db

with app.app_context():
    # Supprimer toutes les tables existantes
    db.drop_all()
    print("✅ Anciennes tables supprimées")
    
    # Créer les nouvelles tables avec tous les modèles
    db.create_all()
    print("✅ Nouvelles tables créées avec succès !")
    print("   - User (avec phone_number, subscription, etc.)")
    print("   - Listing (avec paiement)")
    print("   - Conversation (messagerie)")
    print("   - Message (messages individuels)")