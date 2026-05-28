import csv
from django.http import HttpResponse
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Campus, CampusCotaCargo, Organograma, Unit, CargoFuncao, TipoUnidade, Profile, ModeloReferencial, ModeloReferencialCotaCargo, UnitModelo, Dimensionamento, RegrasAlteracaoModelo, ExcecaoRegraAlteracaoCampus, RegimentoCampus, ResolucaoEstruturaOrganizacional, CompetenciaUnidade

@admin.action(description='Exportar para formato LucidChart (CSV)')
def export_lucidchart_csv(modeladmin, request, queryset):
    if queryset.count() != 1:
        modeladmin.message_user(request, "Por favor, selecione apenas UM organograma para exportar.", level=messages.ERROR)
        return

    organograma = queryset.first()
    unidades = organograma.unidades.all()

    response = HttpResponse(
        content_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="organograma_{organograma.campus.sigla}_{organograma.id}.csv"'},
    )
    # Adiciona o BOM para o Excel abrir o UTF-8 corretamente, útil para usuários que testam no Excel local
    response.write(u'\ufeff'.encode('utf8'))

    writer = csv.writer(response, delimiter=',')
    # Header compatível com org chart padrão (LucidChart)
    writer.writerow(['Employee ID', 'Name', 'Title', 'Role', 'Supervisor ID'])

    for unit in unidades:
        nome_completo = f"{unit.sigla_unidade} - {unit.nome_unidade}" if unit.sigla_unidade else unit.nome_unidade
        cargo_completo = f"{unit.sigla_cargo} - {unit.cargo_funcao}" if unit.sigla_cargo else (unit.cargo_funcao or "")
        parent_id = unit.unidade_pai.id if unit.unidade_pai else ""
        
        writer.writerow([
            unit.id,
            nome_completo,
            cargo_completo,
            unit.sigla_cargo or "",
            parent_id
        ])

    return response

class CampusCotaCargoInline(admin.TabularInline):
    model = CampusCotaCargo
    extra = 1
    fields = ('cargo_funcao', 'quantidade')


@admin.register(Campus)
class CampusAdmin(admin.ModelAdmin):
    list_display = ('nome', 'sigla', 'dimensionamento_fk', 'modelo_referencial_padrao')
    search_fields = ('nome', 'sigla')
    list_filter = ('dimensionamento_fk',)
    inlines = [CampusCotaCargoInline]

@admin.register(Organograma)
class OrganogramaAdmin(admin.ModelAdmin):
    list_display = ('campus', 'data_vigencia', 'status', 'resolucao_estrutura', 'regimento_referencia', 'regimento_geral_referencia')
    list_filter = ('status', 'campus')
    search_fields = ('campus__nome',)
    actions = [export_lucidchart_csv]


@admin.register(RegimentoCampus)
class RegimentoCampusAdmin(admin.ModelAdmin):
    list_display = ('nome', 'numero', 'campus', 'tipo', 'data_publicacao', 'vigente')
    list_filter = ('campus', 'tipo', 'vigente')
    search_fields = ('nome', 'numero', 'campus__nome', 'campus__sigla')


@admin.register(ResolucaoEstruturaOrganizacional)
class ResolucaoEstruturaOrganizacionalAdmin(admin.ModelAdmin):
    list_display = ('nome', 'numero', 'campus', 'data_publicacao')
    list_filter = ('campus',)
    search_fields = ('nome', 'numero', 'campus__nome', 'campus__sigla')


@admin.register(CompetenciaUnidade)
class CompetenciaUnidadeAdmin(admin.ModelAdmin):
    list_display = ('unidade', 'regimento', 'referencia_formatada', 'ordem', 'revisada_em')
    list_filter = ('regimento__campus', 'regimento')
    search_fields = ('unidade__nome_unidade', 'unidade__sigla_unidade', 'texto', 'artigo', 'inciso')

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('nome_unidade', 'sigla_unidade', 'organograma', 'cargo_funcao_ref')
    list_filter = ('organograma__campus', 'organograma')
    search_fields = ('nome_unidade', 'sigla_unidade', 'cargo_funcao_ref__nome')

@admin.register(CargoFuncao)
class CargoFuncaoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'sigla')
    search_fields = ('nome', 'sigla')
    filter_horizontal = ('dimensionamentos_permitidos',)

@admin.register(TipoUnidade)
class TipoUnidadeAdmin(admin.ModelAdmin):
    list_display = ('nome', 'cargo_padrao')
    search_fields = ('nome',)
    filter_horizontal = ('dimensionamentos_permitidos',)

@admin.register(Dimensionamento)
class DimensionamentoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'chave')
    search_fields = ('nome', 'chave')

class UnitModeloInline(admin.TabularInline):
    model = UnitModelo
    extra = 2
    fk_name = 'modelo'
    fields = ('nome_unidade', 'sigla_unidade', 'tipo_unidade', 'cargo_funcao_ref', 'permite_resolucao_flexivel', 'is_agrupamento', 'ordem')


class ModeloReferencialCotaCargoInline(admin.TabularInline):
    model = ModeloReferencialCotaCargo
    extra = 1
    fields = ('cargo_funcao', 'quantidade')

@admin.register(ModeloReferencial)
class ModeloReferencialAdmin(admin.ModelAdmin):
    list_display = ('nome', 'dimensionamento', 'resolucao_referencia', 'ativo')
    list_filter = ('dimensionamento', 'ativo')
    search_fields = ('nome', 'resolucao_referencia')
    inlines = [ModeloReferencialCotaCargoInline, UnitModeloInline]

@admin.register(RegrasAlteracaoModelo)
class RegrasAlteracaoModeloAdmin(admin.ModelAdmin):
    list_display = ('modelo_referencial', 'limite_total_alteracoes', 'exigir_adequacao_quando_modelo_mudar')

@admin.register(ExcecaoRegraAlteracaoCampus)
class ExcecaoRegraAlteracaoCampusAdmin(admin.ModelAdmin):
    list_display = ('campus', 'modelo_referencial', 'limite_total_alteracoes')
    list_filter = ('modelo_referencial',)

@admin.register(UnitModelo)
class UnitModeloAdmin(admin.ModelAdmin):
    list_display = ('nome_unidade', 'modelo', 'unidade_pai', 'tipo_unidade', 'permite_resolucao_flexivel')
    list_filter = ('modelo', 'tipo_unidade')
    search_fields = ('nome_unidade', 'modelo__nome')
    filter_horizontal = ('tipos_resolucao_permitidos', 'cargos_resolucao_permitidos')
    ordering = ('modelo', 'ordem')

# Integração do Profile na tela do Usuário
class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Perfil de Acesso'

class CustomUserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)

admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
