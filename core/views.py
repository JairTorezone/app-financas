from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db.models import Sum
from datetime import date
import json
import calendar

from .models import CompraCartao, Transacao, Categoria, CartaoCredito, Terceiro
from .forms import (
    CompraCartaoForm, TransacaoForm, CartaoCreditoForm, CadastroForm, 
    RelatorioFiltroForm, CategoriaForm, TerceiroForm, ImportarFaturaForm)

from django.contrib.auth import login

from django.db.models import ProtectedError
from django.contrib import messages

from django.shortcuts import get_object_or_404
from dateutil.relativedelta import relativedelta

import pandas as pd
from ofxparse import OfxParser

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