from django.contrib import admin
from .models import Categoria, Transacao, CartaoCredito, CompraCartao, Terceiro

@admin.register(Transacao)
class TransacaoAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'valor', 'data', 'categoria', 'tipo_custo')
    list_filter = ('data', 'categoria__tipo', 'tipo_custo') # Filtros laterais

@admin.register(CompraCartao)
class CompraCartaoAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'valor', 'data_compra', 'cartao', 'terceiro')
    list_filter = ('cartao', 'data_compra')

@admin.register(Terceiro)
class TerceiroAdmin(admin.ModelAdmin):
    list_display = ('nome', 'relacionamento', 'usuario')
    search_fields = ('nome',)

# Registro simples
admin.site.register(Categoria)
admin.site.register(CartaoCredito)