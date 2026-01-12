from django.db import models
from django.contrib.auth.models import User
from datetime import date

class Categoria(models.Model):
    TIPO_CHOICES = (
        ('R', 'Receita'),
        ('D', 'Despesa'),
    )
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    
    nome = models.CharField(max_length=50)
    tipo = models.CharField(max_length=1, choices=TIPO_CHOICES)
    
    def __str__(self):
        return self.nome

class Transacao(models.Model):
    TIPO_FIXO_VAR = (
        ('F', 'Fixa'),
        ('V', 'Variável'),
    )
    
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True)
    descricao = models.CharField(max_length=100) # Ex: Salário, Luz
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data = models.DateField(default=date.today)
    tipo_custo = models.CharField(max_length=1, choices=TIPO_FIXO_VAR, default='V') # Fixo ou Variável
    observacao = models.TextField(blank=True, null=True)
    pago = models.BooleanField(default=True, verbose_name="Pago?") # Default True facilita para quem lança na hora
    data_pagamento = models.DateField(null=True, blank=True, verbose_name="Data do Pagamento")

    def __str__(self):
        return f"{self.descricao} - {self.valor}"

class CartaoCredito(models.Model):
    CORES_CHOICES = (
        ('#820AD1', 'Roxo (Nubank)'),
        ('#FF8700', 'Laranja (Inter/Itaú)'),
        ('#CC092F', 'Vermelho (Bradesco/Santander)'),
        ('#FFD700', 'Dourado/Amarelo'),
        ('#005CAA', 'Azul (Caixa/Azul)'),
        ('#000000', 'Preto (Black/C6)'),
        ('#28a745', 'Verde (Padrão)'),
        ('#6c757d', 'Cinza (Outros)'),
    )

    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=50) # Ex: Nubank
    ultimos_digitos = models.CharField(max_length=4) # Ex: 1234

    dia_vencimento = models.IntegerField(default=1, verbose_name="Dia do Vencimento")
    
    cor = models.CharField(max_length=7, choices=CORES_CHOICES, default='#28a745')

    def __str__(self):
        return f"{self.nome} final {self.ultimos_digitos}"

class Terceiro(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=100)
    # CORREÇÃO ABAIXO: Removemos o placeholder daqui
    relacionamento = models.CharField(max_length=50, blank=True, null=True)
    
    def __str__(self):
        if self.relacionamento:
            return f"{self.nome} ({self.relacionamento})"
        return self.nome

class CompraCartao(models.Model):
    cartao = models.ForeignKey(CartaoCredito, on_delete=models.CASCADE)
    descricao = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data_compra = models.DateField(default=date.today)
    
    # Parcelamento
    is_parcelado = models.BooleanField(default=False, verbose_name="É parcelado?")
    qtd_parcelas = models.IntegerField(default=1, verbose_name="Qtd Parcelas")
    
    # Terceiros
    is_terceiro = models.BooleanField(default=False, verbose_name="É compra de terceiro?")
    
    # --- MUDANÇA AQUI: Trocamos CharField por ForeignKey ---
    # removemos nome_terceiro antigo e colocamos o link para a tabela nova
    terceiro = models.ForeignKey(Terceiro, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Pessoa")
    pago = models.BooleanField(default=False, verbose_name="Conferido?")

    def __str__(self):
        return f"{self.descricao} - {self.valor}"

class MetaMensal(models.Model):
    TIPO_CHOICES = (
        ('C', 'Por Categoria'),
        ('K', 'Cartão(ões) de Crédito'),
        ('E', 'Economia (Guardar)'),
        ('G', 'Orçamento Global (Teto de Gastos)'), # Novo
    )
    
    PERIODO_CHOICES = (
        ('M', 'Mensal (Mês Atual)'),
        ('A', 'Anual (Ano Atual)'),
    )

    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    tipo = models.CharField(max_length=1, choices=TIPO_CHOICES, default='C')
    periodo = models.CharField(max_length=1, choices=PERIODO_CHOICES, default='M', verbose_name="Período")
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, null=True, blank=True)
    valor_limite = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor da Meta")
    
    class Meta:
        unique_together = ('usuario', 'tipo', 'categoria', 'periodo')

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.valor_limite}"