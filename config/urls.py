from django.contrib import admin
from django.urls import path, include # Adicione include
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')), # URLs prontas de login/logout
    path('registro/', views.registro, name='registro'), # Nossa view de cadastro
    path('', include('core.urls')), # Aponta a raiz para o core
]