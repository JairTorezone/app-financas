from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db.models import Sum, Q
from datetime import date, datetime, timedelta
import calendar
import json

from .models import CompraCartao, Transacao, Categoria, CartaoCredito, Terceiro
from .forms import CompraCartaoForm, TransacaoForm, CartaoCreditoForm, CadastroForm, RelatorioFiltroForm
from django.contrib.auth import login

@login_required
def home(request):
    # --- 1. Filtros de Data (Blindado) ---
    try:
        mes_atual = int(request.GET.get('mes', ''))
    except (ValueError, TypeError):
        mes_atual = date.today().month

    try:
        ano_atual = int(request.GET.get('ano', ''))
    except (ValueError, TypeError):
        ano_atual = date.today().year
    
    # Filtros base de Data
    filtro_data = {'data__month': mes_atual, 'data__year': ano_atual}
    filtro_cartao = {'data_compra__month': mes_atual, 'data_compra__year': ano_atual}

    # --- 2. Cálculos de Totais (COM FILTRO DE USUÁRIO) ---
    
    # Receitas
    total_receitas = Transacao.objects.filter(
        usuario=request.user, 
        categoria__tipo='R', 
        **filtro_data
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    # Despesas Fixas (Conta/Dinheiro)
    total_despesas_fixas = Transacao.objects.filter(
        usuario=request.user, 
        categoria__tipo='D', 
        **filtro_data
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    # Cartão Total (Fatura Cheia)
    total_cartao = CompraCartao.objects.filter(
        cartao__usuario=request.user, 
        **filtro_cartao
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    # --- NOVO: CÁLCULO DE TERCEIROS E PESSOAL ---
    
    # Soma apenas compras marcadas como "Terceiro"
    gastos_terceiros = CompraCartao.objects.filter(
        cartao__usuario=request.user,
        is_terceiro=True,
        **filtro_cartao
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    # Totais Gerais
    total_despesas_geral = total_despesas_fixas + total_cartao
    saldo_bancario = total_receitas - total_despesas_geral

    # Totais Pessoais (Realidade do Usuário)
    # Despesa Pessoal = Tudo que gastou MENOS o que é de terceiros
    despesas_pessoais = total_despesas_geral - gastos_terceiros
    
    # Saldo Pessoal = Receita MENOS despesas pessoais (considerando que terceiros vão pagar)
    saldo_pessoal = total_receitas - despesas_pessoais

    # --- 3. Listas Detalhadas ---
    
    # Lista de Receitas
    receitas_detalhadas = Transacao.objects.filter(
        usuario=request.user, 
        categoria__tipo='R', 
        **filtro_data
    ).values('categoria__nome')\
     .annotate(total=Sum('valor'))\
     .order_by('-total')

    # Lista de Despesas (Banco)
    despesas_query = Transacao.objects.filter(
        usuario=request.user, 
        categoria__tipo='D', 
        **filtro_data
    ).values('categoria__nome')\
     .annotate(total=Sum('valor'))
    
    lista_despesas = list(despesas_query)

    # Adiciona o total do cartão como uma "categoria"
    if total_cartao > 0:
        lista_despesas.append({
            'categoria__nome': 'Cartão de Crédito',
            'total': total_cartao,
            'is_cartao': True
        })

    # Ordena despesas (maior para menor)
    lista_despesas.sort(key=lambda x: x['total'], reverse=True)

    tem_cartoes = CartaoCredito.objects.filter(usuario=request.user).exists()

    # --- 4. Contexto Final ---
    contexto = {
        'mes_atual': mes_atual,
        'ano_atual': ano_atual,
        
        # Dados Bancários (Reais)
        'receitas': total_receitas,
        'despesas': total_despesas_geral,
        'saldo': saldo_bancario,
        
        # Dados de Terceiros / Pessoal
        'gastos_cartao': total_cartao,
        'gastos_terceiros': gastos_terceiros,
        'despesas_pessoais': despesas_pessoais,
        'saldo_pessoal': saldo_pessoal,

        # Listas
        'lista_receitas': receitas_detalhadas,
        'lista_despesas': lista_despesas,
        'tem_cartoes': tem_cartoes
    }

    return render(request, 'core/home.html', contexto)


@login_required
def detalhe_cartao(request):
    mes = int(request.GET.get('mes', date.today().month))
    ano = int(request.GET.get('ano', date.today().year))

    # 1. Filtro de Usuário e campo ultimos_digitos adicionados
    faturas = CompraCartao.objects.filter(
        cartao__usuario=request.user, # <--- CORREÇÃO: Só do usuário logado
        data_compra__month=mes, 
        data_compra__year=ano
    ).values(
        'cartao__id', 
        'cartao__nome', 
        'cartao__cor', 
        'cartao__ultimos_digitos' # <--- FEATURE: Pegando os dígitos
    ).annotate(total=Sum('valor')).order_by('-total')

    # 2. Itens individuais (também filtrado por usuário)
    itens = CompraCartao.objects.filter(
        cartao__usuario=request.user, # <--- CORREÇÃO
        data_compra__month=mes, 
        data_compra__year=ano
    ).select_related('cartao').order_by('data_compra')

    return render(request, 'core/detalhe_cartao.html', {
        'faturas': faturas, 
        'itens': itens,
        'mes': mes, 
        'ano': ano,
        'lista_meses': range(1, 13)
    })

@login_required
def adicionar_transacao(request, tipo):
    tipo_codigo = 'R' if tipo == 'receita' else 'D'
    titulo = 'Nova Receita' if tipo == 'receita' else 'Nova Despesa'
    
    # --- LÓGICA DE DATA INICIAL ---
    try:
        mes = int(request.GET.get('mes', date.today().month))
        ano = int(request.GET.get('ano', date.today().year))
        
        # Se for mês atual, dia de hoje. Se for mês passado/futuro, dia 1.
        if mes == date.today().month and ano == date.today().year:
            data_obj = date.today()
        else:
            data_obj = date(ano, mes, 1)
    except:
        data_obj = date.today()

    # TRUQUE: Converter para string YYYY-MM-DD
    data_formatada = data_obj.strftime('%Y-%m-%d')
    # ------------------------------

    if request.method == 'POST':
        form = TransacaoForm(request.POST, tipo_filtro=tipo_codigo, user=request.user)
        if form.is_valid():
            transacao = form.save(commit=False)
            transacao.usuario = request.user
            transacao.save()
            return redirect(f"/?mes={transacao.data.month}&ano={transacao.data.year}")
    else:
        # Passamos a data formatada
        form = TransacaoForm(
            tipo_filtro=tipo_codigo, 
            user=request.user, 
            initial={'data': data_formatada} 
        )

    return render(request, 'core/form_generico.html', {'form': form, 'titulo': titulo})

@login_required
def adicionar_compra(request):
    if not CartaoCredito.objects.filter(usuario=request.user).exists():
        return redirect('cadastrar_cartao')

    # Lógica de Data Inicial (Mantida igual)
    try:
        mes = int(request.GET.get('mes', date.today().month))
        ano = int(request.GET.get('ano', date.today().year))
        if mes == date.today().month and ano == date.today().year:
            data_obj = date.today()
        else:
            data_obj = date(ano, mes, 1)
    except:
        data_obj = date.today()
    
    data_formatada = data_obj.strftime('%Y-%m-%d')

    # --- REMOVIDO: A lógica antiga de buscar 'nomes_terceiros' foi apagada ---
    # O form.terceiro (Select) já faz isso sozinho agora.

    if request.method == 'POST':
        form = CompraCartaoForm(request.POST, user=request.user)
        if form.is_valid():
            compra = form.save()
            return redirect(f"/?mes={compra.data_compra.month}&ano={compra.data_compra.year}")
    else:
        form = CompraCartaoForm(
            initial={'data_compra': data_formatada}, 
            user=request.user
        )
    
    return render(request, 'core/form_generico.html', {
        'form': form, 
        'titulo': 'Nova Compra no Cartão'
    })

@login_required
@require_POST
def criar_terceiro_rapido(request):
    try:
        dados = json.loads(request.body)
        nome = dados.get('nome')
        relacionamento = dados.get('relacionamento')

        if not nome:
            return JsonResponse({'status': 'erro', 'msg': 'Nome é obrigatório'}, status=400)

        # Cria no banco
        novo = Terceiro.objects.create(
            usuario=request.user,
            nome=nome,
            relacionamento=relacionamento
        )
        
        # Retorna os dados para o Javascript atualizar o Select
        return JsonResponse({
            'status': 'ok',
            'id': novo.id,
            'nome': str(novo) # Vai retornar "Ana (Prima)" por causa do __str__
        })
    except Exception as e:
        return JsonResponse({'status': 'erro', 'msg': str(e)}, status=500)

@login_required
def cadastrar_cartao(request):
    if request.method == 'POST':
        form = CartaoCreditoForm(request.POST)
        if form.is_valid():
            cartao = form.save(commit=False)
            cartao.usuario = request.user
            cartao.save()
            # Após criar o cartão, redireciona para adicionar a compra que ele queria fazer
            return redirect('adicionar_compra')
    else:
        form = CartaoCreditoForm()
    
    return render(request, 'core/form_generico.html', {
        'form': form, 
        'titulo': 'Cadastre seu primeiro Cartão'
    })

@login_required
@require_POST
def criar_categoria_rapida(request):
    try:
        dados = json.loads(request.body)
        nome = dados.get('nome')
        tipo = dados.get('tipo')

        if not nome:
            return JsonResponse({'status': 'erro', 'msg': 'Nome é obrigatório'}, status=400)

        # Cria a categoria vinculada ao usuário
        nova_cat = Categoria.objects.create(
            usuario=request.user,
            nome=nome, 
            tipo=tipo
        )
        
        return JsonResponse({
            'status': 'ok',
            'id': nova_cat.id,
            'nome': nova_cat.nome
        })
    except Exception as e:
        return JsonResponse({'status': 'erro', 'msg': str(e)}, status=500)

@login_required
@require_POST
def criar_cartao_rapido(request):
    try:
        dados = json.loads(request.body)
        nome = dados.get('nome')
        digitos = dados.get('digitos')
        cor = dados.get('cor', '#000000')

        if not nome or not digitos:
            return JsonResponse({'status': 'erro', 'msg': 'Nome e dígitos são obrigatórios'}, status=400)

        # Usando o model correto: CartaoCredito (e não Conta)
        novo_cartao = CartaoCredito.objects.create(
            usuario=request.user,
            nome=nome,
            ultimos_digitos=digitos, # Atenção: no seu model o campo chama ultimos_digitos
            cor=cor
        )

        # Retorna formatado para o Select do HTML
        return JsonResponse({
            'status': 'ok',
            'id': novo_cartao.id,
            'nome': f"{novo_cartao.nome} final {novo_cartao.ultimos_digitos}"
        })
    except Exception as e:
        return JsonResponse({'status': 'erro', 'msg': str(e)}, status=500)

def registro(request):
    if request.method == 'POST':
        form = CadastroForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Faz o login automático após o cadastro e redireciona para a Home
            login(request, user)
            return redirect('home')
    else:
        form = CadastroForm()
    
    return render(request, 'registration/register.html', {'form': form})

@login_required
def dash_terceiros(request):
    try:
        mes = int(request.GET.get('mes', date.today().month))
        ano = int(request.GET.get('ano', date.today().year))
    except:
        mes = date.today().month
        ano = date.today().year

    # --- CORREÇÃO: Agrupar por ID para o link funcionar ---
    terceiros = CompraCartao.objects.filter(
        cartao__usuario=request.user,
        is_terceiro=True,
        data_compra__month=mes,
        data_compra__year=ano
    ).exclude(terceiro__isnull=True) \
    .values(
        'terceiro__id',             # ID para o link
        'terceiro__nome',           # Nome para exibir
        'terceiro__relacionamento'  # Relacionamento
    ).annotate(total=Sum('valor')).order_by('-total')

    total_geral = CompraCartao.objects.filter(
        cartao__usuario=request.user, 
        is_terceiro=True,
        data_compra__month=mes,
        data_compra__year=ano
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    return render(request, 'core/terceiros_list.html', {
        'terceiros': terceiros,
        'total_geral': total_geral,
        'mes': mes, 
        'ano': ano
    })

@login_required
def detalhe_terceiro(request, terceiro_id):
    try:
        mes = int(request.GET.get('mes', date.today().month))
        ano = int(request.GET.get('ano', date.today().year))
    except:
        mes = date.today().month
        ano = date.today().year

    pessoa = get_object_or_404(Terceiro, id=terceiro_id, usuario=request.user)

    # 1. Lista de compras DO MÊS (para a tabela)
    compras_mes = CompraCartao.objects.filter(
        cartao__usuario=request.user,
        is_terceiro=True,
        terceiro__id=terceiro_id,
        data_compra__month=mes,
        data_compra__year=ano
    ).order_by('-data_compra')

    # 2. Total DO MÊS
    total_mes = compras_mes.aggregate(Sum('valor'))['valor__sum'] or 0

    # 3. NOVO: Total GERAL (Acumulado de todas as datas)
    # Aqui removemos os filtros de mês e ano para pegar tudo
    total_geral = CompraCartao.objects.filter(
        cartao__usuario=request.user,
        is_terceiro=True,
        terceiro__id=terceiro_id
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    return render(request, 'core/terceiros_detalhe.html', {
        'nome': pessoa.nome,
        'relacionamento': pessoa.relacionamento, # Passando relacionamento se quiser exibir
        'compras': compras_mes,
        'total': total_mes,          # Total só deste mês
        'total_geral': total_geral,  # Total acumulado da vida toda
        'mes': mes,
        'ano': ano
    })


@login_required
def relatorio_financeiro(request):
    import calendar
    
    hoje = date.today()
    ultimo_dia_mes = calendar.monthrange(hoje.year, hoje.month)[1]
    
    data_inicio = hoje.replace(day=1)
    data_fim = hoje.replace(day=ultimo_dia_mes)

    form = RelatorioFiltroForm(request.GET or None)
    
    if form.is_valid():
        if form.cleaned_data['data_inicio']:
            data_inicio = form.cleaned_data['data_inicio']
        if form.cleaned_data['data_fim']:
            data_fim = form.cleaned_data['data_fim']

    # --- CONSULTAS BLINDADAS (USUARIO=REQUEST.USER) ---

    # 1. RECEITAS
    receitas = Transacao.objects.filter(
        usuario=request.user,  # <--- SEGURANÇA: Só do usuário logado
        categoria__tipo='R',
        data__range=[data_inicio, data_fim]
    ).values('categoria__nome', 'categoria__id').annotate(total=Sum('valor')).order_by('-total')

    total_receitas = Transacao.objects.filter(
        usuario=request.user, # <--- SEGURANÇA
        categoria__tipo='R',
        data__range=[data_inicio, data_fim]
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    # 2. DESPESAS DE CONTA
    despesas_conta = Transacao.objects.filter(
        usuario=request.user, # <--- SEGURANÇA
        categoria__tipo='D',
        data__range=[data_inicio, data_fim]
    ).values('categoria__nome', 'categoria__id').annotate(total=Sum('valor')).order_by('-total')

    total_despesas_conta = Transacao.objects.filter(
        usuario=request.user, # <--- SEGURANÇA
        categoria__tipo='D',
        data__range=[data_inicio, data_fim]
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    # 3. CARTÃO DE CRÉDITO
    # CompraCartao -> CartaoCredito -> Usuario
    gastos_cartao = CompraCartao.objects.filter(
        cartao__usuario=request.user, # <--- SEGURANÇA
        data_compra__range=[data_inicio, data_fim]
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    # 4. TOTAIS
    total_despesas_geral = total_despesas_conta + gastos_cartao
    saldo = total_receitas - total_despesas_geral

    context = {
        'form': form,
        'receitas': receitas,
        'despesas_conta': despesas_conta,
        'total_receitas': total_receitas,
        'total_despesas_conta': total_despesas_conta,
        'total_cartao': gastos_cartao,
        'total_despesas_geral': total_despesas_geral,
        'saldo': saldo,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
    }

    return render(request, 'core/relatorio.html', context)

@login_required
def relatorio_detalhe_categoria(request, categoria_id):
    data_inicio_str = request.GET.get('data_inicio')
    data_fim_str = request.GET.get('data_fim')
    
    # SEGURANÇA: Garante que a categoria pertence ao usuário (ou é global se você usar sistema misto)
    # Aqui assumo que Categorias são do usuário ou globais acessíveis. 
    # Melhor filtrar a transação pelo usuário direto:
    
    categoria = get_object_or_404(Categoria, id=categoria_id) # Precisamos importar get_object_or_404
    
    transacoes = Transacao.objects.filter(
        usuario=request.user, # <--- SEGURANÇA
        categoria_id=categoria_id,
        data__range=[data_inicio_str, data_fim_str]
    ).order_by('data')
    
    total = transacoes.aggregate(Sum('valor'))['valor__sum'] or 0

    context = {
        'titulo': f"Detalhes: {categoria.nome}",
        'transacoes': transacoes,
        'total': total,
        'data_inicio': data_inicio_str,
        'data_fim': data_fim_str,
        'is_cartao': False # Flag para o template saber que é tabela de transação comum
    }
    return render(request, 'core/relatorio_detalhe.html', context)

# --- NOVA VIEW PARA CARTÃO ---
@login_required
def relatorio_detalhe_cartao(request):
    data_inicio_str = request.GET.get('data_inicio')
    data_fim_str = request.GET.get('data_fim')
    
    # Filtra COMPRAS DE CARTÃO do usuário
    compras = CompraCartao.objects.filter(
        cartao__usuario=request.user, # <--- SEGURANÇA
        data_compra__range=[data_inicio_str, data_fim_str]
    ).order_by('data_compra')
    
    total = compras.aggregate(Sum('valor'))['valor__sum'] or 0

    context = {
        'titulo': "Detalhes: Fatura Cartão de Crédito",
        'transacoes': compras, # Mandamos as compras na variavel 'transacoes' para reutilizar o template
        'total': total,
        'data_inicio': data_inicio_str,
        'data_fim': data_fim_str,
        'is_cartao': True # Flag para mudar as colunas no HTML
    }
    return render(request, 'core/relatorio_detalhe.html', context)