"""
scripts/seed_demo.py — Add 3 demo model profiles for local Mini App testing.

Usage:
  DATABASE_URL="postgres://..." python scripts/seed_demo.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import init_db
from database.models import init_models_db, get_all_models, add_model

init_db()
init_models_db()

existing = get_all_models()
if existing:
    print(f"⚠️  Database already has {len(existing)} model(s). Skipping seed.")
    print("   Existing models:")
    for m in existing:
        print(f"   #{m['id']} {m['name']} (age {m.get('age', '?')})")
    sys.exit(0)

models = [
    ("Анастасия", "15.05.1999", "nastya_test",
     "Нежная и страстная 🔥 Обожаю общаться с новыми людьми!\n"
     "Каждый разговор — маленькое приключение 💫"),
    ("Виктория",  "22.08.2000", "victoria_m",
     "Загадочная красотка из Кишинёва ✨\n"
     "Открыта к любым разговорам — от лёгкого флирта до глубоких тем 💬"),
    ("Елена",     "10.03.1998", "elena_m",
     "Умная, красивая, весёлая 💎\n"
     "Люблю музыку, путешествия и хорошие разговоры 🎵"),
]

for name, dob, username, desc in models:
    mid = add_model(name, dob, username, desc)
    print(f"✅ Added model #{mid}: {name}")

print("\n🎉 Demo data seeded! Run the API server to see the Mini App.")
print("   MINI_APP_DEV=1 DATABASE_URL=... BOT_TOKEN=... uvicorn api.server:app --port 8080 --reload")
