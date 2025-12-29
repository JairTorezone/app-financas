from django import forms
from django.db.models import Q
from .models import CompraCartao, Transacao, Categoria, CartaoCredito
from dateutil.relativedelta import relativedelta
import copy

# core/forms.py
from django import forms
from django.db.models import Q
from .models import CompraCartao, Transacao, Categoria, CartaoCredito, Terceiro
from dateutil.relativedelta import relativedelta
from decimal import Decimal
import copy

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

# --- MIXIN PARA REUTILIZAR A LIMPEZA DE VALOR ---
class MoneyCleanMixin:
    def clean_valor(self):
        valor = self.cleaned_data.get('valor')
        if not valor:
            return None
        
        # Se o valor vier como string (ex: "R$ 1.200,50"), limpamos
        if isinstance(valor, str):
            # Remove o 'R$', remove espaços, remove pontos de milhar
            # Troca vírgula decimal por ponto
            valor_limpo = valor.replace('R$', '').replace('.', '').replace(',', '.').strip()
            try:
                return Decimal(valor_limpo)
            except:
                raise forms.ValidationError("Valor inválido")
        return valor

# --- FORMULÁRIO DE COMPRA ---
class CompraCartaoForm(MoneyCleanMixin, forms.ModelForm):
    # O campo valor continua igual
    valor = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control money-mask', 'placeholder': 'R$ 0,00'})
    )

    class Meta:
        model = CompraCartao
        # AQUI ESTAVA O ERRO: Troque 'nome_terceiro' por 'terceiro'
        fields = ['cartao', 'descricao', 'valor', 'data_compra', 
                  'is_parcelado', 'qtd_parcelas', 
                  'is_terceiro', 'terceiro'] 
        
        widgets = {
            'data_compra': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'cartao': forms.Select(attrs={'class': 'form-select'}),
            'descricao': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Padaria, Uber...'}),
            
            'is_parcelado': forms.RadioSelect(choices=[(True, 'Sim'), (False, 'Não')], attrs={'class': 'radio-inline'}),
            
            # Widgets de Terceiro atualizados
            'is_terceiro': forms.RadioSelect(choices=[(True, 'Sim'), (False, 'Não')], attrs={'class': 'radio-inline'}),
            
            # AQUI TAMBÉM: Removemos o widget do nome_terceiro antigo e deixamos o Select do novo
            'terceiro': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None) 
        super().__init__(*args, **kwargs)
        if user:
            self.fields['cartao'].queryset = CartaoCredito.objects.filter(usuario=user)
            # Filtra os terceiros apenas desse usuário
            self.fields['terceiro'].queryset = Terceiro.objects.filter(usuario=user)

        if self.instance.pk is None: 
            self.initial.setdefault('is_parcelado', False)
            self.initial.setdefault('is_terceiro', False)

    def clean(self):
        cleaned_data = super().clean()
        
        # --- CORREÇÃO 1: PARCELAMENTO ---
        # Se 'is_parcelado' for False, forçamos Qtd = 1
        is_parcelado = str(cleaned_data.get('is_parcelado')) == 'True'
        if not is_parcelado:
            cleaned_data['qtd_parcelas'] = 1
            # Limpa erros de validação desse campo, pois acabamos de corrigir
            if 'qtd_parcelas' in self._errors: del self._errors['qtd_parcelas']

        # --- CORREÇÃO 2: TERCEIRO ---
        # Se 'is_terceiro' for False, garantimos que terceiro seja None
        is_terceiro = str(cleaned_data.get('is_terceiro')) == 'True'
        if not is_terceiro:
            cleaned_data['terceiro'] = None
            if 'terceiro' in self._errors: del self._errors['terceiro']
        else:
            # Se for True, obriga a ter alguém selecionado
            if not cleaned_data.get('terceiro'):
                 self.add_error('terceiro', 'Selecione uma pessoa da lista.')
            
        return cleaned_data

    def save(self, commit=True):
        # 1. Pega a instância mas não salva no banco ainda
        instancia = super().save(commit=False)
        
        # Garante booleanos corretos
        instancia.is_parcelado = str(self.cleaned_data.get('is_parcelado')) == 'True'
        instancia.is_terceiro = str(self.cleaned_data.get('is_terceiro')) == 'True'
        
        # Pega a quantidade de parcelas (se vazio, assume 1)
        qtd = self.cleaned_data.get('qtd_parcelas') or 1
        
        # Lógica de Parcelamento
        if instancia.is_parcelado and qtd > 1:
            # Calcula valor de cada parcela
            valor_total = instancia.valor
            valor_parcela = valor_total / qtd
            
            # Ajusta a PRIMEIRA parcela (a instância atual)
            instancia.valor = valor_parcela
            descricao_original = instancia.descricao
            instancia.descricao = f"{descricao_original} (1/{qtd})"
            
            if commit:
                instancia.save() # Salva a parcela 1

            # Cria as demais parcelas (2 até qtd)
            for i in range(1, qtd):
                nova_compra = copy.copy(instancia)
                nova_compra.pk = None # Importante: Define como novo registro
                nova_compra.descricao = f"{descricao_original} ({i+1}/{qtd})"
                nova_compra.data_compra = instancia.data_compra + relativedelta(months=i)
                
                # O copy.copy deve levar o 'terceiro', mas por garantia:
                nova_compra.terceiro = instancia.terceiro 
                
                if commit:
                    nova_compra.save()
                    
            return instancia
            
        else:
            # Se NÃO for parcelado, salva normal com o valor total
            if commit:
                instancia.save()
            return instancia

# --- FORMULÁRIO DE TRANSAÇÃO ---
class TransacaoForm(MoneyCleanMixin, forms.ModelForm): # Adicione o Mixin aqui
    # Redefinimos valor para CharField
    valor = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control money-mask', 'placeholder': 'R$ 0,00'})
    )

    class Meta:
        model = Transacao
        fields = ['categoria','descricao', 'valor', 'data',  'observacao']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'descricao': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Salário, Conta de Luz'}),
            # valor removido daqui
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        tipo_filtro = kwargs.pop('tipo_filtro', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if tipo_filtro and user:
            self.fields['categoria'].queryset = Categoria.objects.filter(
                Q(usuario=user) | Q(usuario__isnull=True),
                tipo=tipo_filtro
            ).order_by('nome')

# --- FORMULÁRIO DE CADASTRO DE CARTÃO (NOVA CLASSE) ---
class CartaoCreditoForm(forms.ModelForm):
   class Meta:
        model = CartaoCredito
        # Apenas os campos solicitados
        fields = ['nome', 'ultimos_digitos', 'cor']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Nubank, Inter...'}),
            'ultimos_digitos': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 9999', 'maxlength': '4'}),
            # O campo 'cor' usa Select automaticamente se tiver choices no Model,
            # mas podemos forçar a classe do bootstrap para ficar bonito.
            'cor': forms.Select(attrs={'class': 'form-select'}), 
        }

# --- ADICIONE ESTE FORMULÁRIO NOVO ---
class CadastroForm(UserCreationForm):
    # Sobrescrevemos o campo de email para torná-lo obrigatório (required=True)
    email = forms.EmailField(
        required=True, 
        label="E-mail", 
        help_text="Necessário para recuperar a senha caso você esqueça."
    )

    class Meta:
        model = User
        # Define a ordem dos campos: Usuário primeiro, depois E-mail
        # As senhas (1 e 2) o Django adiciona automaticamente no final
        fields = ("username", "email")

    # Opcional: Validação extra para garantir que o email não seja usado por outro usuário
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Este e-mail já está cadastrado. Tente recuperar sua senha.")
        return email