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
    path('terceiros/resumo/', views.lista_gastos_terceiros, name='lista_gastos_terceiros'),
    
    # Rota para a lista completa pessoal
    path('relatorios/pessoal/', views.detalhe_despesas_pessoais, name='detalhe_despesas_pessoais'),
    path('configuracoes/', views.gerenciar_cadastros, name='gerenciar_cadastros'),
    
    # Rota para Excluir itens
    path('excluir/<str:tipo>/<int:id_item>/', views.excluir_item, name='excluir_item'),
    path('compra/editar/<int:compra_id>/', views.editar_compra, name='editar_compra'),
    path('compra/excluir/<int:compra_id>/', views.excluir_compra, name='excluir_compra'),
    path('transacao/editar/<int:id_transacao>/', views.editar_transacao, name='editar_transacao'),
    path('transacao/excluir/<int:id_transacao>/', views.excluir_transacao, name='excluir_transacao'),

    # Nova rota Genérica para Editar Configurações (Renomear)
    path('config/editar/<str:tipo>/<int:id_item>/', views.editar_item_config, name='editar_item_config'),
    path('transacoes/copiar-fixas/', views.copiar_despesas_fixas, name='copiar_despesas_fixas'),
    path('receitas/copiar-fixas/', views.copiar_receitas_fixas, name='copiar_receitas_fixas'),

    path('cartao/importar/', views.importar_fatura, name='importar_fatura'),
    # Adicione esta linha nas urlpatterns
    path('editar/<str:tipo>/<int:id>/', views.editar_item, name='editar_item'),
    path('pagar/<str:tipo>/<int:id_item>/', views.alternar_pagamento, name='alternar_pagamento'),
    path('pagar-fatura/<int:cartao_id>/<int:mes>/<int:ano>/', views.pagar_fatura_inteira, name='pagar_fatura_inteira'),
    path('metas/', views.definir_metas, name='definir_metas'),
    path('metas/excluir/<int:id_meta>/', views.excluir_meta, name='excluir_meta'),
    # Adicione ou verifique se tem essas rotas
    path('metas/acompanhar/', views.acompanhar_metas, name='acompanhar_metas'),
    path('metas/definir/', views.definir_metas, name='definir_metas'),
    path('metas/editar/<int:id_meta>/', views.editar_meta, name='editar_meta'),
    path('pagar-categoria/<int:categoria_id>/<int:mes>/<int:ano>/', views.pagar_categoria_inteira, name='pagar_categoria_inteira'),
]
