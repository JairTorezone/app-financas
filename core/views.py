from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from datetime import date
import json
import calendar

from .models import CompraCartao, Transacao, Categoria, CartaoCredito, Terceiro, MetaMensal
from .forms import (
    CompraCartaoForm, TransacaoForm, CartaoCreditoForm, CadastroForm, 
    RelatorioFiltroForm, CategoriaForm, TerceiroForm, ImportarFaturaForm, MetaMensalForm)

from django.contrib.auth import login

from django.db.models import ProtectedError
from django.contrib import messages

from django.shortcuts import get_object_or_404
from dateutil.relativedelta import relativedelta

import pandas as pd
from ofxparse import OfxParser

from django.db import IntegrityError

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
    
    # Lista de Receitas: ADICIONADO 'categoria__id' no values()
    receitas_detalhadas = Transacao.objects.filter(
        usuario=request.user, 
        categoria__tipo='R', 
        **filtro_data
    ).values('categoria__nome', 'categoria__id')\
     .annotate(total=Sum('valor'))\
     .order_by('-total')

    # Lista de Despesas (Banco): ADICIONADO 'categoria__id' no values()
    despesas_query = Transacao.objects.filter(
        usuario=request.user, 
        categoria__tipo='D', 
        **filtro_data
    ).values('categoria__nome', 'categoria__id')\
     .annotate(
         total=Sum('valor'),
         pendentes=Count('id', filter=Q(pago=False)) # <--- NOVO: Conta quantos não foram pagos
     )
    
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
    ultimo_dia = calendar.monthrange(ano_atual, mes_atual)[1]

    # --- 4. Contexto Final ---
    contexto = {
        'mes_atual': mes_atual,
        'ano_atual': ano_atual,
        'ultimo_dia': ultimo_dia,
        
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
        'cartao__ultimos_digitos',
        'cartao__dia_vencimento' # <--- ADICIONE ISSO AQUI
    ).annotate(
        total=Sum('valor'),
        # NOVA LÓGICA: Conta quantos itens NÃO estão pagos (pago=False)
        pendentes=Count('id', filter=Q(pago=False)) 
    ).order_by('-total')

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
def pagar_fatura_inteira(request, cartao_id, mes, ano):
    # Busca todas as compras daquele cartão/mês/ano
    compras = CompraCartao.objects.filter(
        cartao__usuario=request.user,
        cartao_id=cartao_id,
        data_compra__month=mes,
        data_compra__year=ano
    )
    
    # Lógica de Toggle (Alternar):
    # Se tiver ALGUMA pendente -> Marca TUDO como pago.
    # Se estiver TUDO pago -> Marca TUDO como não pago (caso tenha clicado errado).
    
    tem_pendencia = compras.filter(pago=False).exists()
    
    # Atualiza em massa (Bulk update)
    compras.update(pago=tem_pendencia)
    
    return redirect(f'/cartoes/?mes={mes}&ano={ano}')

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
    from datetime import date # Garante import
    
    # 1. Pega mês/ano da URL ou usa Hoje
    try:
        mes_url = request.GET.get('mes')
        ano_url = request.GET.get('ano')
        
        if mes_url and ano_url:
            # Cria data: Dia 01 do mês selecionado
            # Ex: Se URL é mes=6, cria 2025-06-01
            data_inicial = date(int(ano_url), int(mes_url), 1)
        else:
            data_inicial = date.today()
    except:
        data_inicial = date.today()

    # Formata YYYY-MM-DD para o input HTML
    data_formatada = data_inicial.strftime('%Y-%m-%d')

    if request.method == 'POST':
        # Passa o usuário para filtrar cartões
        form = CompraCartaoForm(request.POST, user=request.user)
        if form.is_valid():
            compra = form.save()
            # Redireciona para o mês onde a compra caiu
            return redirect(f"/?mes={compra.data_compra.month}&ano={compra.data_compra.year}")
    else:
        # INICIALIZA O FORMULÁRIO COM A DATA CERTA
        form = CompraCartaoForm(
            user=request.user, 
            initial={'data_compra': data_formatada}
        )

    return render(request, 'core/form_generico.html', {
        'form': form, 
        'titulo': 'Nova Compra Cartão'
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
        dia_vencimento = dados.get('dia_vencimento', 1) # Pega o dia ou usa 1 padrão

        if not nome or not digitos:
            return JsonResponse({'status': 'erro', 'msg': 'Nome e dígitos são obrigatórios'}, status=400)

        # Usando o model correto: CartaoCredito (e não Conta)
        novo_cartao = CartaoCredito.objects.create(
            usuario=request.user,
            nome=nome,
            ultimos_digitos=digitos, # Atenção: no seu model o campo chama ultimos_digitos
            cor=cor,
            dia_vencimento=dia_vencimento
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
    from .models import MetaMensal # Garanta a importação
    
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

    # --- 1. RECEITAS E DESPESAS (CÓDIGO QUE VOCÊ JÁ TINHA) ---
    # Mantive igual, apenas resumindo para focar na novidade
    
    receitas = Transacao.objects.filter(
        usuario=request.user, 
        categoria__tipo='R', 
        data__range=[data_inicio, data_fim]
    ).values('categoria__nome', 'categoria__id').annotate(total=Sum('valor')).order_by('-total')

    total_receitas = Transacao.objects.filter(
        usuario=request.user, categoria__tipo='R', data__range=[data_inicio, data_fim]
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    despesas_conta = Transacao.objects.filter(
        usuario=request.user, categoria__tipo='D', data__range=[data_inicio, data_fim]
    ).values('categoria__nome', 'categoria__id').annotate(total=Sum('valor'))

    total_despesas_conta = Transacao.objects.filter(
        usuario=request.user, categoria__tipo='D', data__range=[data_inicio, data_fim]
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    # Agrupa gastos de cartão por CATEGORIA (importante para bater com a meta)
    gastos_cartao_cat = CompraCartao.objects.filter(
        cartao__usuario=request.user, 
        data_compra__range=[data_inicio, data_fim]
    ).values('cartao__nome').annotate(total=Sum('valor')) # Cartão geralmente não tem categoria no seu model atual, então tratamos como um total separado ou se tiver categoria, agrupe aqui.
    
    # Nota: No seu model atual, CompraCartao NÃO tem categoria. 
    # Então vamos considerar o total do cartão como um "gasto" geral para fins de saldo, 
    # mas as metas funcionarão melhor para Despesas de Conta (Categoria D) por enquanto.
    
    total_cartao = CompraCartao.objects.filter(
        cartao__usuario=request.user,
        data_compra__range=[data_inicio, data_fim]
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    total_despesas_geral = total_despesas_conta + total_cartao
    saldo = total_receitas - total_despesas_geral

    # --- 2. LÓGICA DAS METAS (NOVIDADE) 🎯 ---
    
    # Pega todas as metas definidas pelo usuário
    metas_definidas = MetaMensal.objects.filter(usuario=request.user).select_related('categoria')
    relatorio_metas = []
    
    for meta in metas_definidas:
        gasto_atual = 0
        is_savings = False # Flag para inverter as cores (Economia: Quanto mais melhor)

        # A) META DE CATEGORIA (Gasto em dinheiro/conta naquela categoria)
        if meta.tipo == 'C' and meta.categoria:
            gasto_atual = Transacao.objects.filter(
                usuario=request.user,
                categoria=meta.categoria,
                data__range=[data_inicio, data_fim]
            ).aggregate(Sum('valor'))['valor__sum'] or 0
            
            nome_meta = meta.categoria.nome

        # B) META GLOBAL DE CARTÕES (Soma de TODAS as faturas)
        elif meta.tipo == 'K':
            gasto_atual = total_cartao # Variável que já calculamos acima
            nome_meta = "Total Cartões de Crédito"

        # C) META DE ECONOMIA (Quanto sobrou: Receita - Despesa Total)
        elif meta.tipo == 'E':
            gasto_atual = saldo # Variável saldo calculada acima
            nome_meta = "Meta de Economia (Saldo)"
            is_savings = True

        # --- CÁLCULO DA PORCENTAGEM ---
        if meta.valor_limite > 0:
            porcentagem = (gasto_atual / meta.valor_limite) * 100
        else:
            porcentagem = 0
            
        # --- DEFINIÇÃO DE CORES ---
        if is_savings:
            # Lógica INVERSA para Economia:
            # < 50% Ruim (Vermelho), < 100% Ok (Amarelo), >= 100% Ótimo (Verde)
            estourou = False # Não existe "estourar" economia, só não atingir
            if porcentagem < 50: cor = 'bg-danger'
            elif porcentagem < 100: cor = 'bg-warning'
            else: cor = 'bg-success'
        else:
            # Lógica Padrão para Gastos:
            # < 70% Bom (Verde), < 100% Atenção (Amarelo), > 100% Estourou (Vermelho)
            estourou = porcentagem > 100
            if porcentagem < 70: cor = 'bg-success'
            elif porcentagem < 100: cor = 'bg-warning'
            else: cor = 'bg-danger'

        relatorio_metas.append({
            'categoria': nome_meta,
            'limite': meta.valor_limite,
            'gasto': gasto_atual,
            'porcentagem': min(porcentagem, 100), # Trava visual em 100%
            'valor_percentual': porcentagem,      # Valor real para mostrar no texto
            'estourou': estourou,
            'cor': cor,
            'tipo': meta.tipo
        })

    # Ordena: Quem estourou a meta aparece primeiro
    relatorio_metas.sort(key=lambda x: x['porcentagem'], reverse=True)

    context = {
        'form': form,
        'receitas': receitas,
        'despesas_conta': despesas_conta,
        'total_receitas': total_receitas,
        'total_despesas_conta': total_despesas_conta,
        'total_cartao': total_cartao,
        'total_despesas_geral': total_despesas_geral,
        'saldo': saldo,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'relatorio_metas': relatorio_metas, # <--- Enviando para o template
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

@login_required
def lista_gastos_terceiros(request):
    import calendar
    
    # 1. Recupera Data da URL ou Hoje
    try:
        mes = int(request.GET.get('mes', date.today().month))
        ano = int(request.GET.get('ano', date.today().year))
    except:
        mes = date.today().month
        ano = date.today().year

    ultimo_dia = calendar.monthrange(ano, mes)[1]
    data_inicio = date(ano, mes, 1)
    data_fim = date(ano, mes, ultimo_dia)
    
    # 2. Agrupa gastos por Terceiro
    # Isso cria aquela lista: Jaime: R$ 350, Paulo: R$ 75...
    # Ajuste 'terceiro__nome' se o seu campo for diferente
    terceiros_agrupados = CompraCartao.objects.filter(
        cartao__usuario=request.user,
        is_terceiro=True,
        data_compra__range=[data_inicio, data_fim]
    ).values('terceiro__nome', 'terceiro__parentesco', 'terceiro__id').annotate(total=Sum('valor')).order_by('-total')

    total_geral = CompraCartao.objects.filter(
        cartao__usuario=request.user,
        is_terceiro=True,
        data_compra__range=[data_inicio, data_fim]
    ).aggregate(Sum('valor'))['valor__sum'] or 0

    return render(request, 'core/lista_terceiros.html', {
        'terceiros': terceiros_agrupados,
        'total_geral': total_geral,
        'mes': mes, 'ano': ano,
        'data_inicio': data_inicio, 'data_fim': data_fim
    })

@login_required
def detalhe_despesas_pessoais(request):
    import calendar
    
    try:
        mes = int(request.GET.get('mes', date.today().month))
        ano = int(request.GET.get('ano', date.today().year))
    except:
        mes = date.today().month
        ano = date.today().year

    ultimo_dia = calendar.monthrange(ano, mes)[1]
    data_inicio = date(ano, mes, 1)
    data_fim = date(ano, mes, ultimo_dia)

    # 1. Despesas em Dinheiro (Contas, Pix, etc)
    despesas_conta = Transacao.objects.filter(
        usuario=request.user,
        categoria__tipo='D', # Somente Despesas
        data__range=[data_inicio, data_fim]
    ).order_by('data')

    # 2. Despesas Cartão (Somente as suas, is_terceiro=False)
    despesas_cartao = CompraCartao.objects.filter(
        cartao__usuario=request.user,
        is_terceiro=False, # <--- O segredo está aqui
        data_compra__range=[data_inicio, data_fim]
    ).order_by('data_compra')

    # Totais
    total_conta = despesas_conta.aggregate(Sum('valor'))['valor__sum'] or 0
    total_cartao = despesas_cartao.aggregate(Sum('valor'))['valor__sum'] or 0
    total_geral = total_conta + total_cartao

    return render(request, 'core/despesas_pessoais.html', {
        'despesas_conta': despesas_conta,
        'despesas_cartao': despesas_cartao,
        'total_conta': total_conta,
        'total_cartao': total_cartao,
        'total_geral': total_geral,
        'mes': mes, 'ano': ano
    })

@login_required
def gerenciar_cadastros(request):
    # Busca tudo que pertence ao usuário
    categorias = Categoria.objects.filter(usuario=request.user).order_by('tipo', 'nome')
    cartoes = CartaoCredito.objects.filter(usuario=request.user)
    terceiros = Terceiro.objects.filter(usuario=request.user)
    
    return render(request, 'core/gerenciar_cadastros.html', {
        'categorias': categorias,
        'cartoes': cartoes,
        'terceiros': terceiros
    })

@login_required
def excluir_item(request, tipo, id_item):
    # Dicionário para mapear a string da URL para o Modelo real
    mapa_modelos = {
        'categoria': Categoria,
        'cartao': CartaoCredito,
        'terceiro': Terceiro
    }
    
    Modelo = mapa_modelos.get(tipo)
    
    if not Modelo:
        messages.error(request, "Item inválido.")
        return redirect('gerenciar_cadastros')
    
    # Tenta pegar o item (Garante que pertence ao usuário logado)
    try:
        obj = Modelo.objects.get(id=id_item, usuario=request.user)
    except Modelo.DoesNotExist:
        messages.error(request, "Item não encontrado.")
        return redirect('gerenciar_cadastros')

    # Tenta Excluir
    try:
        # Verifica dependências manualmente antes de deletar para dar msg amigável
        if tipo == 'cartao' and CompraCartao.objects.filter(cartao=obj).exists():
            messages.warning(request, f"Não é possível excluir o cartão '{obj.nome}' pois ele tem compras registradas.")
            
        elif tipo == 'categoria' and Transacao.objects.filter(categoria=obj).exists():
            messages.warning(request, f"A categoria '{obj.nome}' está em uso em lançamentos e não pode ser excluída.")
            
        elif tipo == 'terceiro' and CompraCartao.objects.filter(terceiro=obj).exists():
            messages.warning(request, f"O terceiro '{obj.nome}' possui dívidas registradas e não pode ser excluído.")
            
        else:
            obj.delete()
            messages.success(request, f"{tipo.capitalize()} excluído com sucesso!")
            
    except Exception as e:
        messages.error(request, "Erro ao excluir o item.")

    return redirect('gerenciar_cadastros')

@login_required
def editar_compra(request, compra_id):
    # Busca a compra garantindo que pertence a um cartão do usuário logado (Segurança)
    compra = get_object_or_404(CompraCartao, id=compra_id, cartao__usuario=request.user)
    
    if request.method == 'POST':
        form = CompraCartaoForm(request.POST, instance=compra, user=request.user)
        if form.is_valid():
            compra_editada = form.save()
            # Redireciona para o mês da compra editada
            return redirect(f"/?mes={compra_editada.data_compra.month}&ano={compra_editada.data_compra.year}")
    else:
        # Preenche o formulário com os dados atuais
        form = CompraCartaoForm(instance=compra, user=request.user)
    
    return render(request, 'core/form_generico.html', {
        'form': form, 
        'titulo': f'Editar: {compra.descricao}'
    })

@login_required
def excluir_compra(request, compra_id):
    compra = get_object_or_404(CompraCartao, id=compra_id, cartao__usuario=request.user)
    
    # Guarda o mês/ano para redirecionar o usuário de volta para o lugar certo
    mes = compra.data_compra.month
    ano = compra.data_compra.year
    
    compra.delete()
    
    # Opcional: Adicionar mensagem de sucesso
    # messages.success(request, 'Compra removida com sucesso.')
    
    # Se você estava na tela de detalhes da fatura, o ideal seria voltar pra lá.
    # Mas como simplificação, voltamos para a Home filtrada no mês.
    return redirect(f"/?mes={mes}&ano={ano}")

@login_required
def editar_transacao(request, id_transacao):
    # Busca a transação garantindo que é do usuário
    transacao = get_object_or_404(Transacao, id=id_transacao, usuario=request.user)
    
    # Descobre o tipo (R ou D) baseado na categoria atual para filtrar o form corretamente
    tipo_atual = transacao.categoria.tipo if transacao.categoria else 'D'
    
    if request.method == 'POST':
        form = TransacaoForm(request.POST, instance=transacao, tipo_filtro=tipo_atual, user=request.user)
        if form.is_valid():
            form.save()
            return redirect(f"/?mes={transacao.data.month}&ano={transacao.data.year}")
    else:
        form = TransacaoForm(instance=transacao, tipo_filtro=tipo_atual, user=request.user)
    
    tipo_label = "Receita" if tipo_atual == 'R' else "Despesa"
    
    return render(request, 'core/form_generico.html', {
        'form': form, 
        'titulo': f'Editar {tipo_label}'
    })

@login_required
def excluir_transacao(request, id_transacao):
    transacao = get_object_or_404(Transacao, id=id_transacao, usuario=request.user)
    
    mes = transacao.data.month
    ano = transacao.data.year
    
    transacao.delete()
    messages.success(request, "Item excluído com sucesso.")
    
    return redirect(f"/?mes={mes}&ano={ano}")

@login_required
def editar_item_config(request, tipo, id_item):
    # Dicionário de configuração: mapeia a string da URL para (Modelo, Form)
    config = {
        'categoria': (Categoria, CategoriaForm),
        'cartao': (CartaoCredito, CartaoCreditoForm),
        'terceiro': (Terceiro, TerceiroForm)
    }
    
    # Verifica se o tipo é válido
    if tipo not in config:
        return redirect('gerenciar_cadastros')
    
    Modelo, FormClass = config[tipo]
    
    # Busca o objeto (segurança por usuário)
    obj = get_object_or_404(Modelo, id=id_item, usuario=request.user)
    
    if request.method == 'POST':
        form = FormClass(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Alteração salva com sucesso!")
            return redirect('gerenciar_cadastros')
    else:
        form = FormClass(instance=obj)
    
    return render(request, 'core/form_generico.html', {
        'form': form,
        'titulo': f'Editar {tipo.capitalize()}'
    })

@login_required
def copiar_despesas_fixas(request):
    # 1. Pega o mês/ano de DESTINO (que está na URL ou é o atual)
    try:
        mes_atual = int(request.GET.get('mes', date.today().month))
        ano_atual = int(request.GET.get('ano', date.today().year))
    except:
        mes_atual = date.today().month
        ano_atual = date.today().year

    data_atual = date(ano_atual, mes_atual, 1)
    
    # 2. Calcula o mês ANTERIOR (Origem)
    data_anterior = data_atual - relativedelta(months=1)
    
    # 3. Busca as despesas FIXAS do mês anterior
    despesas_fixas_anterior = Transacao.objects.filter(
        usuario=request.user,
        categoria__tipo='D', # Apenas Despesas
        tipo_custo='F',      # Apenas as marcadas como FIXA ('F')
        data__month=data_anterior.month,
        data__year=data_anterior.year
    )
    
    if not despesas_fixas_anterior.exists():
        messages.warning(request, "Nenhuma despesa fixa encontrada no mês passado para copiar.")
        return redirect(f"/?mes={mes_atual}&ano={ano_atual}")

    # 4. Cria as cópias no mês ATUAL
    contador = 0
    for despesa in despesas_fixas_anterior:
        # Verifica se já não existe uma igual neste mês (para evitar duplicar se clicar 2x)
        # Critério: Mesma descrição e mesmo valor (pode ajustar se quiser)
        ja_existe = Transacao.objects.filter(
            usuario=request.user,
            descricao=despesa.descricao,
            valor=despesa.valor,
            data__month=mes_atual,
            data__year=ano_atual
        ).exists()
        
        if not ja_existe:
            # Cria a cópia
            nova_despesa = Transacao.objects.create(
                usuario=request.user,
                categoria=despesa.categoria,
                descricao=despesa.descricao,
                valor=despesa.valor,
                tipo_custo='F', # Continua sendo fixa
                observacao=f"Copiado de {data_anterior.strftime('%m/%Y')}",
                # Mantém o mesmo dia (ex: dia 05), mas no mês/ano atual
                data=date(ano_atual, mes_atual, despesa.data.day) 
            )
            contador += 1

    if contador > 0:
        messages.success(request, f"{contador} despesas fixas copiadas com sucesso!")
    else:
        messages.info(request, "As despesas fixas do mês passado já foram lançadas neste mês.")

    return redirect(f"/?mes={mes_atual}&ano={ano_atual}")

@login_required
def copiar_receitas_fixas(request):
    try:
        mes_atual = int(request.GET.get('mes', date.today().month))
        ano_atual = int(request.GET.get('ano', date.today().year))
    except:
        mes_atual = date.today().month
        ano_atual = date.today().year

    data_atual = date(ano_atual, mes_atual, 1)
    data_anterior = data_atual - relativedelta(months=1)
    
    # Busca RECEITAS ('R') que são FIXAS ('F') do mês anterior
    receitas_fixas_anterior = Transacao.objects.filter(
        usuario=request.user,
        categoria__tipo='R',  # <--- Filtra Receita
        tipo_custo='F',       # <--- Filtra Fixa
        data__month=data_anterior.month,
        data__year=data_anterior.year
    )
    
    if not receitas_fixas_anterior.exists():
        messages.warning(request, "Nenhuma receita fixa encontrada no mês passado.")
        return redirect(f"/?mes={mes_atual}&ano={ano_atual}")

    contador = 0
    for receita in receitas_fixas_anterior:
        # Verifica duplicidade
        ja_existe = Transacao.objects.filter(
            usuario=request.user,
            descricao=receita.descricao,
            valor=receita.valor,
            data__month=mes_atual,
            data__year=ano_atual,
            categoria__tipo='R'
        ).exists()
        
        if not ja_existe:
            Transacao.objects.create(
                usuario=request.user,
                categoria=receita.categoria,
                descricao=receita.descricao,
                valor=receita.valor,
                tipo_custo='F',
                observacao=f"Copiado de {data_anterior.strftime('%m/%Y')}",
                data=date(ano_atual, mes_atual, receita.data.day) 
            )
            contador += 1

    if contador > 0:
        messages.success(request, f"{contador} receitas copiadas com sucesso!")
    else:
        messages.info(request, "Receitas já foram copiadas.")

    return redirect(f"/?mes={mes_atual}&ano={ano_atual}")

@login_required
def importar_fatura(request):
    if request.method == 'POST':
        form = ImportarFaturaForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            arquivo = request.FILES['arquivo']
            cartao = form.cleaned_data['cartao']
            mes_ref = form.cleaned_data['mes_referencia']
            ano_ref = form.cleaned_data['ano_referencia']
            
            # Data base para forçar o lançamento (Dia 1 do mês selecionado)
            # Dica: Se quiser lançar no dia do fechamento, teria que ter esse dado no cartão
            # Por enquanto, vamos lançar tudo no dia 1 ou manter o dia original mas mudar o mês.
            # Lógica Escolhida: Manter o DIA original, mas forçar MÊS/ANO escolhidos.
            
            novos_lancamentos = 0
            
            try:
                # --- LÓGICA PARA CSV ---
                if arquivo.name.endswith('.csv'):
                    # Tenta ler CSV (padrão Nubank é separador virgula)
                    df = pd.read_csv(arquivo)
                    
                    # Normaliza colunas (para minúsculo) para facilitar
                    df.columns = df.columns.str.lower()
                    
                    # Verifica se tem as colunas essenciais
                    # Nubank: date, title, amount
                    # Inter: Data, Descrição, Valor
                    
                    for index, row in df.iterrows():
                        # Tenta encontrar a data
                        data_str = row.get('date') or row.get('data')
                        descricao = row.get('title') or row.get('descrição') or row.get('historico')
                        valor = row.get('amount') or row.get('valor')
                        
                        if data_str and descricao and valor:
                            # Converte valor (alguns bancos usam virgula decimal)
                            if isinstance(valor, str):
                                valor = float(valor.replace('.', '').replace(',', '.'))
                            
                            # Pega apenas o DIA da data original (ex: 2025-12-25 -> dia 25)
                            try:
                                # Tenta formatos comuns
                                dia_original = pd.to_datetime(data_str).day
                            except:
                                dia_original = 1 # Fallback
                            
                            # Cria a data forçada no mês selecionado
                            try:
                                nova_data = date(ano_ref, mes_ref, dia_original)
                            except ValueError:
                                # Caso o dia seja 31 e o mês novo só tenha 30
                                nova_data = date(ano_ref, mes_ref, 28)

                            # Cria no banco
                            CompraCartao.objects.create(
                                cartao=cartao,
                                descricao=str(descricao)[:100],
                                valor=abs(float(valor)), # Garante positivo (alguns csv vêm negativo)
                                data_compra=nova_data,
                                is_parcelado=False,
                                is_terceiro=False
                            )
                            novos_lancamentos += 1

                # --- LÓGICA PARA OFX (Mais padronizado) ---
                elif arquivo.name.endswith('.ofx') or arquivo.name.endswith('.OFX'):
                    ofx = OfxParser.parse(arquivo)
                    for transacao in ofx.account.statement.transactions:
                        # OFX já traz data objeto python
                        dia_original = transacao.date.day
                        
                        try:
                            nova_data = date(ano_ref, mes_ref, dia_original)
                        except:
                            nova_data = date(ano_ref, mes_ref, 28)
                        
                        CompraCartao.objects.create(
                            cartao=cartao,
                            descricao=transacao.memo[:100],
                            valor=abs(float(transacao.amount)),
                            data_compra=nova_data
                        )
                        novos_lancamentos += 1
                
                messages.success(request, f"{novos_lancamentos} compras importadas para {mes_ref}/{ano_ref}!")
                return redirect(f"/?mes={mes_ref}&ano={ano_ref}")
                
            except Exception as e:
                messages.error(request, f"Erro ao processar arquivo: {str(e)}")
                
    else:
        form = ImportarFaturaForm(user=request.user)

    return render(request, 'core/form_generico.html', {
        'form': form,
        'titulo': 'Importar Fatura (OFX/CSV)'
    })

@login_required
def editar_item(request, tipo, id):
    # Dicionário para mapear a string da URL para o Modelo e Formulário corretos
    config = {
        'categoria': {
            'model': Categoria,
            'form': CategoriaForm,
            'titulo': 'Editar Categoria'
        },
        'cartao': {
            'model': CartaoCredito,
            'form': CartaoCreditoForm,
            'titulo': 'Editar Cartão'
        },
        'terceiro': {
            'model': Terceiro,
            'form': TerceiroForm,
            'titulo': 'Editar Terceiro'
        }
    }

    # Verifica se o tipo existe no dicionário
    if tipo not in config:
        messages.error(request, "Tipo de edição inválido.")
        return redirect('gerenciar_cadastros')

    dados = config[tipo]
    model_class = dados['model']
    form_class = dados['form']

    # Busca o objeto garantindo que pertence ao usuário logado (SEGURANÇA)
    objeto = get_object_or_404(model_class, id=id, usuario=request.user)

    if request.method == 'POST':
        # Instancia o form com os dados novos (POST) e a instância antiga (instance)
        form = form_class(request.POST, instance=objeto)
        if form.is_valid():
            form.save()
            messages.success(request, f"{dados['titulo']} realizado com sucesso!")
            return redirect('gerenciar_cadastros')
    else:
        # GET: Carrega o form preenchido com os dados atuais
        form = form_class(instance=objeto)

    return render(request, 'core/form_generico.html', {
        'form': form,
        'titulo': dados['titulo']
    })

@login_required
def alternar_pagamento(request, tipo, id_item):
    from datetime import date # Garante o import
    
    # Define qual model usar
    if tipo == 'transacao':
        Modelo = Transacao
    elif tipo == 'compra':
        Modelo = CompraCartao
    else:
        return redirect('home')

    # Busca o item com segurança
    item = get_object_or_404(Modelo, id=id_item, usuario=request.user if tipo == 'transacao' else None)
    
    # Se for compra de cartão, precisamos validar o usuário através da relação do cartão
    if tipo == 'compra' and item.cartao.usuario != request.user:
        return redirect('home')

    # Inverte o status (Se tava True vira False, e vice-versa)
    item.pago = not item.pago
    
    # Se virou "Pago", salva a data de hoje. Se "Não pago", limpa a data.
    if tipo == 'transacao':
        item.data_pagamento = date.today() if item.pago else None
    
    item.save()

    # Redireciona de volta para a mesma página que o usuário estava (usando o HTTP_REFERER)
    return redirect(request.META.get('HTTP_REFERER', '/'))

#METAS
@login_required
def definir_metas(request):
    # 1. Processa Formulário (POST)
    if request.method == 'POST':
        form = MetaMensalForm(request.user, request.POST)
        if form.is_valid():
            try:
                meta = form.save(commit=False)
                meta.usuario = request.user
                
                # Limpezas de campos dependendo do tipo
                if meta.tipo != 'C': meta.categoria = None
                if meta.periodo != 'P': 
                    meta.data_inicio = None
                    meta.data_fim = None
                
                meta.save()
                messages.success(request, "Meta salva com sucesso!")
                return redirect('definir_metas')
            except Exception as e:
                messages.error(request, f"Erro ao salvar: {e}")
        else:
            messages.error(request, "Verifique os erros no formulário.")
    else:
        form = MetaMensalForm(request.user)

    # 2. Prepara os dados para exibição
    metas_banco = MetaMensal.objects.filter(usuario=request.user).order_by('periodo', 'categoria__nome')
    
    # Estruturas para o Dashboard
    poupanca_display = []
    gastos_display = []
    
    # Agrupamento temporário
    temp_agrupamento = {
        'poupanca': {'M': [], 'T': [], 'S': [], 'A': [], 'P': []},
        'gastos':   {'M': [], 'T': [], 'S': [], 'A': [], 'P': []}
    }
    
    # Lista plana processada para a tabela do rodapé
    todas_metas_processadas = []

    for meta in metas_banco:
        d_inicio, d_fim = calcular_intervalo_meta(meta)
        gasto_atual = 0
        is_savings = False
        
        # --- Lógica de Cálculo ---
        if meta.tipo == 'C' and meta.categoria:
            gasto_atual = Transacao.objects.filter(usuario=request.user, categoria=meta.categoria, data__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            label = meta.categoria.nome
        elif meta.tipo == 'K':
            gasto_atual = CompraCartao.objects.filter(cartao__usuario=request.user, data_compra__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            label = "Total Cartões"
        elif meta.tipo == 'E':
            rec = Transacao.objects.filter(usuario=request.user, categoria__tipo='R', data__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            desp = Transacao.objects.filter(usuario=request.user, categoria__tipo='D', data__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            cart = CompraCartao.objects.filter(cartao__usuario=request.user, data_compra__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            gasto_atual = rec - (desp + cart)
            label = "Economia / Guardar"
            is_savings = True
        elif meta.tipo == 'G':
            d_conta = Transacao.objects.filter(usuario=request.user, categoria__tipo='D', data__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            c_val = CompraCartao.objects.filter(cartao__usuario=request.user, data_compra__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            gasto_atual = d_conta + c_val
            label = "Orçamento Global"

        if meta.descricao: label = meta.descricao

        # Porcentagem e Cores
        porcentagem = (gasto_atual / meta.valor_limite * 100) if meta.valor_limite > 0 else 0
        msg = ""
        cor_classe = "bg-success"
        
        if is_savings:
            if porcentagem >= 100: 
                cor_classe = "bg-success"
                msg = "Atingida! 🏆"
            elif porcentagem < 50: cor_classe = "bg-danger"
            else: cor_classe = "bg-warning"
        else:
            if porcentagem > 100: 
                cor_classe = "bg-danger"
                msg = "Excedeu!"
            elif porcentagem >= 80: cor_classe = "bg-warning"

        # Preenche objeto meta temporário
        meta.temp_label = label
        meta.temp_gasto = gasto_atual
        meta.temp_perc_real = porcentagem
        meta.temp_perc_visual = min(porcentagem, 100)
        meta.temp_cor = cor_classe
        meta.temp_msg = msg
        meta.temp_is_savings = is_savings
        
        if meta.periodo == 'P' and meta.data_inicio:
            meta.temp_datas = f"{meta.data_inicio.strftime('%d/%m')} a {meta.data_fim.strftime('%d/%m')}"
        else:
            meta.temp_datas = meta.get_periodo_display()

        # Adiciona aos grupos
        chave = 'poupanca' if is_savings else 'gastos'
        temp_agrupamento[chave][meta.periodo].append(meta)
        todas_metas_processadas.append(meta)

    # 3. Transforma dicionário em listas ordenadas para o Template
    titulos = {'M': 'Mensais', 'T': 'Trimestrais', 'S': 'Semestrais', 'A': 'Anuais', 'P': 'Personalizadas'}
    
    # Cores dos Títulos (Bootstrap Classes)
    cores_titulos = {
        'M': 'text-primary',   # Azul
        'T': 'text-warning',   # Amarelo/Laranja
        'S': 'text-info',      # Ciano
        'A': 'text-success',   # Verde
        'P': 'text-dark'       # Preto
    }
    
    ordem = ['M', 'T', 'S', 'A', 'P']

    for sigla in ordem:
        if temp_agrupamento['poupanca'][sigla]:
            poupanca_display.append({
                'titulo': titulos[sigla], 
                'lista': temp_agrupamento['poupanca'][sigla],
                'cor_titulo': cores_titulos[sigla]
            })
        if temp_agrupamento['gastos'][sigla]:
            gastos_display.append({
                'titulo': titulos[sigla], 
                'lista': temp_agrupamento['gastos'][sigla],
                'cor_titulo': cores_titulos[sigla]
            })

    return render(request, 'core/definir_metas.html', {
        'form': form,
        'poupanca_display': poupanca_display,
        'gastos_display': gastos_display,
        'metas': todas_metas_processadas # Lista completa para o rodapé
    })

@login_required
def editar_meta(request, id_meta):
    # Busca a meta ou retorna erro 404, garantindo que pertence ao usuário
    meta = get_object_or_404(MetaMensal, id=id_meta, usuario=request.user)
    
    if request.method == 'POST':
        form = MetaMensalForm(request.user, request.POST, instance=meta)
        if form.is_valid():
            try:
                m = form.save(commit=False)
                
                # Regra de negócio: Se mudou para algo que não é Categoria, limpa o campo
                if m.tipo != 'C':
                    m.categoria = None
                    
                m.save()
                messages.success(request, "Meta atualizada com sucesso!")
                return redirect('definir_metas')
            except Exception as e:
                messages.error(request, "Erro ao atualizar meta.")
    else:
        # Carrega o formulário com os dados existentes
        form = MetaMensalForm(request.user, instance=meta)
    
    # Renderiza o template específico de edição que você criou
    return render(request, 'core/editar_meta.html', { # Atenção ao nome do arquivo
        'form': form,
        'meta': meta # Passar o objeto meta pode ser útil para exibir o título
    })

def excluir_meta(request, id_meta):
    meta = get_object_or_404(MetaMensal, id=id_meta, usuario=request.user)
    meta.delete()
    messages.success(request, "Meta removida.")
    return redirect('definir_metas')

@login_required
def pagar_categoria_inteira(request, categoria_id, mes, ano):
    """
    Marca TODAS as transações de uma categoria específica no mês/ano como PAGAS.
    Se todas já estiverem pagas, marca como NÃO PAGAS (toggle).
    """
    from datetime import date # Garantir import
    
    # Busca as transações dessa categoria, usuário e data
    transacoes = Transacao.objects.filter(
        usuario=request.user,
        categoria_id=categoria_id,
        data__month=mes,
        data__year=ano
    )
    
    if not transacoes.exists():
        return redirect(f'/?mes={mes}&ano={ano}')

    # Verifica se existe ALGUMA pendente (pago=False)
    tem_pendencia = transacoes.filter(pago=False).exists()
    
    # Se tem pendência, vamos marcar TUDO como pago.
    # Se não tem pendência (tudo verde), vamos marcar tudo como NÃO pago.
    novo_status = tem_pendencia 
    nova_data = date.today() if novo_status else None
    
    # Atualização em massa (Bulk Update)
    transacoes.update(pago=novo_status, data_pagamento=nova_data)
    
    # Retorna para a home no mesmo mês
    return redirect(f'/?mes={mes}&ano={ano}')

def calcular_intervalo_meta(meta):
    """Define data de início e fim baseada no tipo de período."""
    hoje = date.today()
    ano = hoje.year
    mes = hoje.month

    # Personalizado: Usa o que o usuário escolheu
    if meta.periodo == 'P':
        inicio = meta.data_inicio or date(ano, mes, 1)
        fim = meta.data_fim or date(ano, mes, calendar.monthrange(ano, mes)[1])
        return inicio, fim

    # Mensal: Mês Atual
    elif meta.periodo == 'M':
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        return date(ano, mes, 1), date(ano, mes, ultimo_dia)

    # Trimestral: Trimestre Atual
    elif meta.periodo == 'T':
        trimestre = (mes - 1) // 3 + 1
        mes_inicio = (trimestre - 1) * 3 + 1
        mes_fim = mes_inicio + 2
        ultimo_dia = calendar.monthrange(ano, mes_fim)[1]
        return date(ano, mes_inicio, 1), date(ano, mes_fim, ultimo_dia)

    # Semestral: Semestre Atual
    elif meta.periodo == 'S':
        if mes <= 6:
            return date(ano, 1, 1), date(ano, 6, 30)
        else:
            return date(ano, 7, 1), date(ano, 12, 31)

    # Anual: Ano Atual
    elif meta.periodo == 'A':
        return date(ano, 1, 1), date(ano, 12, 31)

    return hoje, hoje

@login_required
def acompanhar_metas(request):
    metas_banco = MetaMensal.objects.filter(usuario=request.user)
    relatorio_metas = []

    for meta in metas_banco:
        # USA A FUNÇÃO AUXILIAR PARA PEGAR AS DATAS CERTAS
        d_inicio, d_fim = calcular_intervalo_meta(meta)
        
        gasto_atual = 0
        is_savings = False

        # --- QUERYSETS FILTRANDO PELO INTERVALO (d_inicio, d_fim) ---
        if meta.tipo == 'C' and meta.categoria:
            gasto_atual = Transacao.objects.filter(
                usuario=request.user, 
                categoria=meta.categoria, 
                data__range=[d_inicio, d_fim]
            ).aggregate(Sum('valor'))['valor__sum'] or 0
            
            # Label usa a descrição se existir, senão o nome da categoria
            nome_display = meta.descricao if meta.descricao else meta.categoria.nome

        elif meta.tipo == 'K':
            gasto_atual = CompraCartao.objects.filter(
                cartao__usuario=request.user, 
                data_compra__range=[d_inicio, d_fim]
            ).aggregate(Sum('valor'))['valor__sum'] or 0
            nome_display = meta.descricao if meta.descricao else "Total Cartões"

        elif meta.tipo == 'E':
            # Economia = Receitas - (Despesas + Cartão) no período
            rec = Transacao.objects.filter(usuario=request.user, categoria__tipo='R', data__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            desp = Transacao.objects.filter(usuario=request.user, categoria__tipo='D', data__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            cart = CompraCartao.objects.filter(cartao__usuario=request.user, data_compra__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            
            gasto_atual = rec - (desp + cart)
            nome_display = meta.descricao if meta.descricao else "Economia / Guardar"
            is_savings = True

        elif meta.tipo == 'G':
            # Global = Despesas + Cartão
            d_conta = Transacao.objects.filter(usuario=request.user, categoria__tipo='D', data__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            c_val = CompraCartao.objects.filter(cartao__usuario=request.user, data_compra__range=[d_inicio, d_fim]).aggregate(Sum('valor'))['valor__sum'] or 0
            gasto_atual = d_conta + c_val
            nome_display = meta.descricao if meta.descricao else "Orçamento Global"

        # Cálculos Finais
        porcentagem = (gasto_atual / meta.valor_limite * 100) if meta.valor_limite > 0 else 0
        
        # Cores (Lógica simplificada)
        cor_classe = "bg-success"
        if not is_savings:
            if porcentagem >= 100: cor_classe = "bg-danger"
            elif porcentagem >= 75: cor_classe = "bg-warning"

        # String legível do período
        if meta.periodo == 'P' and meta.data_inicio:
            texto_periodo = f"{meta.data_inicio.strftime('%d/%m')} a {meta.data_fim.strftime('%d/%m')}"
        else:
            texto_periodo = meta.get_periodo_display()

        relatorio_metas.append({
            'label': nome_display,
            'texto_periodo': texto_periodo,
            'limite': meta.valor_limite,
            'gasto': gasto_atual,
            'porcentagem_visual': min(porcentagem, 100),
            'porcentagem_real': porcentagem,
            'cor_classe': cor_classe,
            'is_savings': is_savings
        })

    return render(request, 'core/acompanhar_metas.html', {'metas': relatorio_metas})