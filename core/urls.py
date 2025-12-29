from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('cartoes/', views.detalhe_cartao, name='detalhe_cartao'), # Nova
    path('adicionar-compra/', views.adicionar_compra, name='adicionar_compra'),
    path('adicionar/<str:tipo>/', views.adicionar_transacao, name='adicionar_transacao'),
    path('cadastrar-cartao/', views.cadastrar_cartao, name='cadastrar_cartao'),
    
    path('criar-categoria-rapida/', views.criar_categoria_rapida, name='criar_categoria_rapida'),
    path('criar-cartao-rapido/', views.criar_cartao_rapido, name='criar_cartao_rapido'), 
    path('terceiros/', views.dash_terceiros, name='dash_terceiros'),
    path('terceiros/<int:terceiro_id>/', views.detalhe_terceiro, name='detalhe_terceiro'),
    path('api/criar-terceiro/', views.criar_terceiro_rapido, name='criar_terceiro_rapido'),
    path('relatorio/', views.relatorio_financeiro, name='relatorio'),
    path('relatorio/detalhes/<int:categoria_id>/', views.relatorio_detalhe_categoria, name='relatorio_detalhe'),
    path('relatorio/detalhes-cartao/', views.relatorio_detalhe_cartao, name='relatorio_detalhe_cartao'),
]