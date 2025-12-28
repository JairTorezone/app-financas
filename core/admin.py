from django.contrib import admin
from .models import Categoria, Transacao, CartaoCredito, CompraCartao

@admin.register(Transacao)
class TransacaoAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'valor', 'data', 'categoria', 'tipo_custo')
    list_filter = ('data', 'categoria__tipo', 'tipo_custo') # Filtros laterais

@admin.register(CompraCartao)
class CompraCartaoAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'valor', 'data_compra', 'cartao')
    list_filter = ('cartao', 'data_compra')

# Registro simples
admin.site.register(Categoria)
admin.site.register(CartaoCredito)