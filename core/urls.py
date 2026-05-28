from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('', views.organograma_list, name='organograma_list'),
    path('organograma/novo/', views.organograma_create, name='organograma_create'),
    path('organograma/<int:pk>/editar/', views.organograma_edit, name='organograma_edit'),
    path('organograma/<int:pk>/', views.organograma_detail, name='organograma_detail'),
    path('organograma/<int:pk>/construir/', views.organograma_build, name='organograma_build'),
    path('organograma/<int:pk>/publicar/', views.organograma_publish, name='organograma_publish'),
    path('organograma/<int:pk>/deletar/', views.organograma_delete, name='organograma_delete'),
    path('organograma/<int:pk>/unidade/<int:unit_id>/deletar/', views.organograma_unit_delete, name='organograma_unit_delete'),
    path('organograma/<int:pk>/unidade/<int:unit_id>/subir/', views.organograma_unit_up, name='organograma_unit_up'),
    path('organograma/<int:pk>/unidade/<int:unit_id>/descer/', views.organograma_unit_down, name='organograma_unit_down'),
    path('organograma/<int:pk>/agrupar/', views.organograma_agrupar_unidades, name='organograma_agrupar_unidades'),
    path('organograma/<int:pk>/unidade/<int:unit_id>/desagrupar/', views.organograma_desagrupar_unidade, name='organograma_desagrupar_unidade'),
    path('organograma/<int:pk>/validar/', views.organograma_validate_ajax, name='organograma_validate_ajax'),
    path('organograma/<int:pk>/unidade/<int:unit_id>/competencias/', views.unidade_competencias, name='unidade_competencias'),
    path('organograma/<int:pk>/unidade/<int:unit_id>/competencias/importar/', views.unidade_competencias_importar, name='unidade_competencias_importar'),
    path('organograma/<int:pk>/unidade/<int:unit_id>/competencias/reordenar/', views.unidade_competencias_reordenar, name='unidade_competencias_reordenar'),
    path('organograma/<int:pk>/unidade/<int:unit_id>/competencia/<int:competencia_id>/', views.unidade_competencia_update, name='unidade_competencia_update'),
    
    # Fluxo de Alterações
    path('solicitacoes/', views.solicitacao_list, name='solicitacao_list'),
    path('solicitacoes/nova/', views.solicitacao_create_select, name='solicitacao_create_select'),
    path('organograma/<int:pk>/alterar/', views.solicitacao_create, name='solicitacao_create'),
    path('solicitacao/<int:pk>/', views.solicitacao_detail, name='solicitacao_detail'),
    path('solicitacao/<int:pk>/aprovar/', views.solicitacao_approve, name='solicitacao_approve'),
    path('solicitacao/<int:pk>/rejeitar/', views.solicitacao_reject, name='solicitacao_reject'),
    path('solicitacao/<int:pk>/reenviar/', views.solicitacao_resubmit, name='solicitacao_resubmit'),
    path('solicitacao/<int:pk>/excluir/', views.solicitacao_delete, name='solicitacao_delete'),


    # Painel de Configurações Administrativas
    path('configuracoes/cargos/', views.cargo_list, name='cargo_list'),
    path('configuracoes/tipos/', views.tipo_unidade_list, name='tipo_unidade_list'),
    path('configuracoes/resolucoes-estrutura/', views.resolucao_estrutura_list, name='resolucao_estrutura_list'),
    path('configuracoes/resolucao-estrutura/<int:pk>/editar/', views.resolucao_estrutura_editar, name='resolucao_estrutura_editar'),
    path('configuracoes/regimentos/', views.regimento_campus_list, name='regimento_campus_list'),
    path('configuracoes/regimento/<int:pk>/editar/', views.regimento_campus_editar, name='regimento_campus_editar'),
    path('configuracoes/cargo/<int:pk>/editar/', views.cargo_editar, name='cargo_editar'),
    path('configuracoes/tipo-unidade/<int:pk>/editar/', views.tipo_unidade_editar, name='tipo_unidade_editar'),
    path('historico/', views.historico_list, name='historico_list'),

    # Gestão de Usuários
    path('configuracoes/usuarios/', views.usuario_list, name='usuario_list'),
    path('configuracoes/usuario/novo/', views.usuario_editar, name='usuario_criar'),
    path('configuracoes/usuario/<int:pk>/editar/', views.usuario_editar, name='usuario_editar'),
    path('configuracoes/usuario/<int:pk>/excluir/', views.usuario_excluir, name='usuario_excluir'),

    # Gestão de Modelos Referenciais
    path('configuracoes/modelos/', views.modelo_referencial_list, name='modelo_referencial_list'),
    path('configuracoes/modelo/novo/', views.modelo_referencial_form, name='modelo_referencial_criar'),
    path('configuracoes/modelo/<int:pk>/editar/', views.modelo_referencial_form, name='modelo_referencial_editar'),
    path('configuracoes/modelo/<int:pk>/construir/', views.modelo_referencial_build, name='modelo_referencial_build'),
    path('configuracoes/modelo/<int:pk>/regras/', views.modelo_regras_form, name='modelo_regras_editar'),
    path('configuracoes/modelo/<int:pk>/unidade/<int:unit_id>/deletar/', views.modelo_referencial_unit_delete, name='modelo_referencial_unit_delete'),
    path('configuracoes/modelo/<int:pk>/unidade/<int:unit_id>/subir/', views.modelo_referencial_unit_up, name='modelo_referencial_unit_up'),
    path('configuracoes/modelo/<int:pk>/unidade/<int:unit_id>/descer/', views.modelo_referencial_unit_down, name='modelo_referencial_unit_down'),
    path('configuracoes/modelo/<int:pk>/agrupar/', views.modelo_referencial_agrupar, name='modelo_referencial_agrupar'),
    path('configuracoes/modelo/<int:pk>/unidade/<int:unit_id>/desagrupar/', views.modelo_referencial_desagrupar, name='modelo_referencial_desagrupar'),

    path('logout/', views.custom_logout, name='logout'),
]
