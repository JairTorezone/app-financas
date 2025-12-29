# criar_admin.py
import os
import django

# Configura o Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth.models import User

def criar():
    # Defina aqui a senha e usuario que voce quer
    USERNAME = 'admin'
    EMAIL = 'jairtorezone@gmail.com'
    SENHA = 'Peixe@121ADMIN' # Troque por uma senha forte

    if not User.objects.filter(username=USERNAME).exists():
        print(f"Criando superusuário {USERNAME}...")
        User.objects.create_superuser(USERNAME, EMAIL, SENHA)
        print("Superusuário criado com sucesso!")
    else:
        print(f"Superusuário {USERNAME} já existe.")

if __name__ == "__main__":
    criar()