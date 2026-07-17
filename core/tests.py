from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import (
    CargoFuncaoForm,
    ModeloReferencialCotaCargoFormSet,
    OrganogramaForm,
    RegimentoCampusForm,
    TipoUnidadeForm,
    UnitForm,
    UnitModeloForm,
)
from .models import (
    Campus,
    CampusCotaCargo,
    CargoFuncao,
    CompetenciaUnidade,
    Dimensionamento,
    ExcecaoRegraAlteracaoCampus,
    ModeloReferencial,
    ModeloReferencialCotaCargo,
    Organograma,
    RegrasAlteracaoModelo,
    RegimentoCampus,
    ResolucaoEstruturaOrganizacional,
    SolicitacaoAlteracao,
    TipoUnidade,
    Unit,
    UnitModelo,
)
from .services.governance import validate_organograma_governance
from .views import _get_unidades_json_data


class DiretoriaMultiCargoTests(TestCase):
    """Diretoria may use CD-03 or CD-04 as Diretor(a) (small-campus CONSUP 44 models)."""

    def setUp(self):
        self.dim, _ = Dimensionamento.objects.get_or_create(
            chave='40_26', defaults={'nome': 'Modelo 40/26'}
        )
        # May already exist after migration 0054 / load_consup44
        self.cd03, _ = CargoFuncao.objects.get_or_create(nome='Diretor(a)', sigla='CD-03')
        self.cd04_dir, _ = CargoFuncao.objects.get_or_create(nome='Diretor(a)', sigla='CD-04')
        self.cd04_coord, _ = CargoFuncao.objects.get_or_create(nome='Coordenador(a)', sigla='CD-04')
        for c in (self.cd03, self.cd04_dir, self.cd04_coord):
            c.dimensionamentos_permitidos.add(self.dim)
        self.tipo, _ = TipoUnidade.objects.get_or_create(
            nome='Diretoria', defaults={'cargo_padrao': self.cd03}
        )
        if self.tipo.cargo_padrao_id != self.cd03.id:
            self.tipo.cargo_padrao = self.cd03
            self.tipo.save(update_fields=['cargo_padrao'])
        self.tipo.dimensionamentos_permitidos.add(self.dim)
        self.tipo.cargos_ocupantes_permitidos.set([self.cd03, self.cd04_dir])
        self.campus, _ = Campus.objects.get_or_create(
            sigla='CTT-IFMG',
            defaults={
                'nome': 'Campus Teste',
                'dimensionamento': '40_26',
                'dimensionamento_fk': self.dim,
            },
        )
        self.org = Organograma.objects.create(campus=self.campus, status='RASCUNHO')

    def test_tipo_allows_cd03_and_cd04_diretor(self):
        ids = self.tipo.get_allowed_cargo_ids()
        self.assertEqual(set(ids), {self.cd03.id, self.cd04_dir.id})
        self.assertNotIn(self.cd04_coord.id, ids)
        self.assertTrue(self.tipo.permite_escolha_entre_cargos)

    def test_unit_form_accepts_diretoria_with_cd04_as_diretor(self):
        form = UnitForm(
            data={
                'unidade_pai': '',
                'tipo_unidade': self.tipo.id,
                'cargo_funcao_ref': self.cd04_dir.id,
                'cargo_funcao': '',
                'sigla_cargo': 'CD-04',
                'nome_unidade': 'Diretoria de Ensino',
                'sigla_unidade': 'CTT-DE',
                'ligacao_indireta': False,
                'layout_filhos': 'V',
            },
            organograma_id=self.org.id,
        )
        self.assertTrue(form.is_valid(), form.errors)
        unit = form.save(commit=False)
        unit.organograma = self.org
        unit.save()
        unit.refresh_from_db()
        self.assertEqual(unit.cargo_funcao_ref_id, self.cd04_dir.id)
        self.assertEqual(unit.cargo_funcao_ref.nome, 'Diretor(a)')
        self.assertEqual(unit.cargo_funcao_ref.sigla, 'CD-04')
        self.assertEqual(unit.tipo_unidade_id, self.tipo.id)

    def test_unit_form_rejects_coordenador_cd04_on_diretoria(self):
        form = UnitForm(
            data={
                'unidade_pai': '',
                'tipo_unidade': self.tipo.id,
                'cargo_funcao_ref': self.cd04_coord.id,
                'cargo_funcao': '',
                'sigla_cargo': 'CD-04',
                'nome_unidade': 'Diretoria de Ensino',
                'sigla_unidade': 'CTT-DE',
                'ligacao_indireta': False,
                'layout_filhos': 'V',
            },
            organograma_id=self.org.id,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('cargo_funcao_ref', form.errors)

    def test_unit_form_rejects_cargo_outside_allowed_list(self):
        fg = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        fg.dimensionamentos_permitidos.add(self.dim)
        form = UnitForm(
            data={
                'unidade_pai': '',
                'tipo_unidade': self.tipo.id,
                'cargo_funcao_ref': fg.id,
                'cargo_funcao': '',
                'sigla_cargo': 'FG-01',
                'nome_unidade': 'Diretoria de Ensino',
                'sigla_unidade': 'CTT-DE',
                'ligacao_indireta': False,
                'layout_filhos': 'V',
            },
            organograma_id=self.org.id,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('cargo_funcao_ref', form.errors)

    def test_load_consup44_builds_4026_diretoria_as_diretor_cd04(self):
        from django.core.management import call_command

        call_command('load_consup44_modelos')
        dim = Dimensionamento.objects.get(chave='40_26')
        modelo = ModeloReferencial.objects.filter(dimensionamento=dim).order_by('id').first()
        self.assertIsNotNone(modelo)
        diretorias = UnitModelo.objects.filter(
            modelo=modelo,
            tipo_unidade__nome='Diretoria',
        ).select_related('cargo_funcao_ref')
        self.assertTrue(diretorias.exists())
        for um in diretorias:
            self.assertEqual(um.cargo_funcao_ref.sigla, 'CD-04')
            self.assertEqual(um.cargo_funcao_ref.nome, 'Diretor(a)')


class ConfiguracaoCadastroTests(TestCase):
    def test_cargo_form_rejects_existing_nome_sigla_pair(self):
        CargoFuncao.objects.create(nome='Coordenador(a)', sigla='CD-04')

        form = CargoFuncaoForm(data={'nome': ' Coordenador(a) ', 'sigla': ' cd-04 '})

        self.assertFalse(form.is_valid())
        self.assertIn('Já existe um cargo/função cadastrado com este nome e sigla.', form.errors['__all__'])

    def test_tipo_unidade_form_rejects_existing_normalized_name(self):
        TipoUnidade.objects.create(nome='Seção')

        form = TipoUnidadeForm(data={'nome': 'Secao'})

        self.assertFalse(form.is_valid())
        self.assertIn('Já existe um tipo de unidade cadastrado com este nome.', form.errors['nome'])


class UsuarioAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username='admin-users', password='senha', is_staff=True)
        self.client = Client()
        self.client.force_login(self.admin)

    def test_staff_user_can_delete_another_user_from_user_management(self):
        User = get_user_model()
        target = User.objects.create_user(username='remove-me', password='senha')

        response = self.client.post(reverse('usuario_excluir', args=[target.pk]))

        self.assertRedirects(response, reverse('usuario_list'))
        self.assertFalse(User.objects.filter(pk=target.pk).exists())

    def test_staff_user_cannot_delete_own_account_from_user_management(self):
        response = self.client.post(reverse('usuario_excluir', args=[self.admin.pk]))

        self.assertRedirects(response, reverse('usuario_list'))
        self.assertTrue(get_user_model().objects.filter(pk=self.admin.pk).exists())

    def test_user_management_list_shows_delete_action_only_for_other_users(self):
        User = get_user_model()
        target = User.objects.create_user(username='listed-user', password='senha')

        response = self.client.get(reverse('usuario_list'))

        self.assertContains(response, reverse('usuario_excluir', args=[target.pk]))
        self.assertNotContains(response, reverse('usuario_excluir', args=[self.admin.pk]))


class GovernancaModeloReferencialTests(TestCase):
    def setUp(self):
        self.dimensionamento = Dimensionamento.objects.create(nome='Campus 40/26', chave='40_26')
        self.modelo = ModeloReferencial.objects.create(
            nome='Modelo Campus 40/26',
            dimensionamento=self.dimensionamento,
            ativo=True,
        )
        self.campus = Campus.objects.create(
            nome='Campus Teste',
            sigla='CTS-IFMG',
            dimensionamento_fk=self.dimensionamento,
            modelo_referencial_padrao=self.modelo,
        )
        self.raiz_modelo = UnitModelo.objects.create(
            modelo=self.modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS',
            ordem=1,
        )
        self.regras = RegrasAlteracaoModelo.objects.create(
            modelo_referencial=self.modelo,
            limite_total_alteracoes=4,
            exige_vinculo_com_modelo=False,
            permite_inclusao_unidade_nova=False,
            limite_inclusao_unidade_nova=0,
            permite_renomeacao=True,
            limite_renomeacao=2,
            permite_mudanca_vinculo=True,
            limite_mudanca_vinculo=2,
            permite_alteracao_cargo=True,
            limite_alteracao_cargo=2,
            permite_alteracao_tipo_unidade=True,
            limite_alteracao_tipo_unidade=2,
            permite_alteracao_sigla=True,
            limite_alteracao_sigla=2,
            permite_exclusao_unidade_modelo=True,
            limite_exclusao_unidade_modelo=2,
        )

    def test_manual_organograma_uses_campus_default_model(self):
        organograma = Organograma.objects.create(campus=self.campus, status='RASCUNHO')
        unit = Unit.objects.create(
            organograma=organograma,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)
        unit.refresh_from_db()

        self.assertEqual(validacao['errors'], [])
        self.assertEqual(organograma.modelo_referencial_efetivo, self.modelo)
        self.assertEqual(unit.origem_modelo_id, self.raiz_modelo.id)

    def test_reitoria_is_allowed_without_modelo_referencial(self):
        dimensionamento = Dimensionamento.objects.create(nome='Reitoria', chave='REITORIA')
        reitoria = Campus.objects.create(nome='Reitoria', sigla='IFMG', dimensionamento_fk=dimensionamento)
        organograma = Organograma.objects.create(campus=reitoria, status='RASCUNHO')
        Unit.objects.create(
            organograma=organograma,
            nome_unidade='Reitoria',
            sigla_unidade='RE',
            ordem=1,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertEqual(validacao['errors'], [])
        self.assertIsNone(organograma.modelo_referencial_efetivo)
        self.assertEqual(validacao['modelo'], None)

    def test_cargo_quota_blocks_when_model_limit_is_exceeded(self):
        cd2 = CargoFuncao.objects.create(nome='Diretor', sigla='CD-02')
        ModeloReferencialCotaCargo.objects.create(
            modelo_referencial=self.modelo,
            cargo_funcao=cd2,
            quantidade=1,
        )
        organograma = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            status='RASCUNHO',
        )
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )
        for index in range(2):
            Unit.objects.create(
                organograma=organograma,
                nome_unidade=f'Diretoria Extra {index}',
                sigla_unidade=f'CTS-DE{index}',
                cargo_funcao_ref=cd2,
                ordem=index + 2,
            )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertTrue(validacao['cargo_quota_exceeded'])
        self.assertTrue(any('CD-02' in error and '2/1' in error for error in validacao['cargo_quota_errors']))
        self.assertTrue(any('CD-02' in error and '2/1' in error for error in validacao['errors']))
        self.assertIn('Cota de cargos/funcoes do Modelo Referencial excedida.', validacao['html'])
        self.assertIn('Limite de cargo/funcao excedido para CD-02: 2/1.', validacao['html'])
        self.assertEqual(validacao['cargo_quotas']['items'][0]['status'], 'exceeded')

    def test_cargo_quota_reports_unallocated_balance_without_blocking(self):
        fg1 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        ModeloReferencialCotaCargo.objects.create(
            modelo_referencial=self.modelo,
            cargo_funcao=fg1,
            quantidade=2,
        )
        organograma = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            status='RASCUNHO',
        )
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )
        Unit.objects.create(
            organograma=organograma,
            nome_unidade='Setor de Apoio',
            sigla_unidade='CTS-SA',
            cargo_funcao_ref=fg1,
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertFalse(validacao['cargo_quota_exceeded'])
        self.assertTrue(validacao['cargo_quota_unallocated'])
        self.assertEqual(validacao['cargo_quota_errors'], [])
        self.assertEqual(validacao['cargo_quotas']['items'][0]['used'], 1)
        self.assertEqual(validacao['cargo_quotas']['items'][0]['limit'], 2)
        self.assertEqual(validacao['cargo_quotas']['items'][0]['status'], 'unallocated')

    def test_cd_fg_without_registered_quota_is_blocked_as_zero_limit(self):
        fg2 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-02')
        organograma = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            status='RASCUNHO',
        )
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )
        Unit.objects.create(
            organograma=organograma,
            nome_unidade='Setor Sem Cota',
            sigla_unidade='CTS-SC',
            cargo_funcao_ref=fg2,
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertTrue(validacao['cargo_quota_exceeded'])
        self.assertTrue(any('FG-02' in error and 'nao possui cota cadastrada' in error for error in validacao['cargo_quota_errors']))

    def test_reitoria_uses_campus_cargo_quotas_without_modelo_referencial(self):
        dimensionamento = Dimensionamento.objects.create(nome='Reitoria', chave='REITORIA')
        reitoria = Campus.objects.create(nome='Reitoria', sigla='IFMG', dimensionamento_fk=dimensionamento)
        cd1 = CargoFuncao.objects.create(nome='Reitor', sigla='CD-01')
        CampusCotaCargo.objects.create(campus=reitoria, cargo_funcao=cd1, quantidade=1)
        organograma = Organograma.objects.create(campus=reitoria, status='RASCUNHO')
        Unit.objects.create(
            organograma=organograma,
            nome_unidade='Reitoria',
            sigla_unidade='RE',
            cargo_funcao_ref=cd1,
            ordem=1,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertEqual(validacao['errors'], [])
        self.assertIsNone(validacao['modelo'])
        self.assertEqual(validacao['cargo_quotas']['items'][0]['sigla'], 'CD-01')
        self.assertEqual(validacao['cargo_quotas']['items'][0]['used'], 1)
        self.assertEqual(validacao['cargo_quotas']['items'][0]['limit'], 1)

    def test_modelo_regras_cota_formset_renders_multiple_cd_fg_rows(self):
        cd1 = CargoFuncao.objects.create(nome='Reitor', sigla='CD-01')
        CargoFuncao.objects.create(nome='Coordenador', sigla='CD-04')
        CargoFuncao.objects.create(nome='Coordenador duplicado', sigla='CD-04')
        fg1 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        CargoFuncao.objects.create(nome='Supervisor', sigla='FG-03')
        CargoFuncao.objects.create(nome='Outro', sigla='OUT')

        formset = ModeloReferencialCotaCargoFormSet(instance=self.modelo, prefix='cotas')

        self.assertEqual(formset.total_form_count(), 6)
        first_form = formset.forms[0]
        cargo_queryset = first_form.fields['cargo_funcao'].queryset
        cargo_ids = set(cargo_queryset.values_list('id', flat=True))
        cargo_siglas = list(cargo_queryset.values_list('sigla', flat=True))
        self.assertIn(cd1.id, cargo_ids)
        self.assertIn(fg1.id, cargo_ids)
        self.assertEqual(set(cargo_siglas), {'CD-01', 'CD-04', 'FG-01', 'FG-03'})
        self.assertEqual(len(cargo_siglas), len(set(cargo_siglas)))

    def test_organograma_form_allows_reitoria_without_modelo_referencial(self):
        dimensionamento = Dimensionamento.objects.create(nome='Reitoria', chave='REITORIA')
        reitoria = Campus.objects.create(nome='Reitoria', sigla='IFMG', dimensionamento_fk=dimensionamento)
        resolucao = ResolucaoEstruturaOrganizacional.objects.create(
            campus=reitoria,
            nome='Resolucao da Reitoria',
            numero='1/2026',
            data_publicacao=date(2026, 1, 1),
        )
        regimento_interno = RegimentoCampus.objects.create(
            campus=reitoria,
            tipo='INTERNO',
            nome='Regimento Interno da Reitoria',
            numero='RI 1/2026',
            vigente=True,
        )
        regimento_geral = RegimentoCampus.objects.create(
            campus=reitoria,
            tipo='GERAL',
            nome='Regimento Geral',
            numero='RG 1/2026',
            vigente=True,
        )

        form = OrganogramaForm(data={
            'campus': reitoria.id,
            'utilizar_modelo': '',
            'modelo_referencial': '',
            'resolucao_estrutura': resolucao.id,
            'regimento_referencia': regimento_interno.id,
            'regimento_geral_referencia': regimento_geral.id,
            'status': 'RASCUNHO',
            'organogramas_vinculados': [],
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data['modelo_referencial'])

    def test_additional_unit_is_blocked_because_proposal_must_keep_model_units(self):
        organograma = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            status='RASCUNHO',
        )
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )
        Unit.objects.create(
            organograma=organograma,
            nome_unidade='Nova Assessoria',
            sigla_unidade='CTS-NA',
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertTrue(any('unidade adicional não prevista no modelo referencial' in error for error in validacao['errors']))
        self.assertEqual(validacao['counts']['inclusao_unidade_nova'], 1)

    def test_campus_override_no_longer_allows_inclusion(self):
        ExcecaoRegraAlteracaoCampus.objects.create(
            modelo_referencial=self.modelo,
            campus=self.campus,
            exige_vinculo_com_modelo=False,
            permite_inclusao_unidade_nova=True,
            limite_inclusao_unidade_nova=1,
        )
        organograma = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            status='RASCUNHO',
        )
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )
        Unit.objects.create(
            organograma=organograma,
            nome_unidade='Nova Assessoria',
            sigla_unidade='CTS-NA',
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertTrue(any('unidade adicional não prevista no modelo referencial' in error for error in validacao['errors']))
        self.assertEqual(validacao['counts']['inclusao_unidade_nova'], 1)

    def test_legacy_total_limit_no_longer_blocks_when_not_in_resolution(self):
        child_model = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            nome_unidade='Diretoria de Ensino',
            sigla_unidade='DE',
            ordem=2,
        )
        organograma = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            status='RASCUNHO',
        )
        root = Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-NOVO',
            ordem=1,
        )
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=child_model,
            unidade_pai=root,
            nome_unidade='Diretoria de Ensino e Extensão',
            sigla_unidade='DEE',
            ordem=2,
        )
        self.regras.limite_total_alteracoes = 1
        self.regras.save(update_fields=['limite_total_alteracoes'])

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertEqual(validacao['errors'], [])
        self.assertEqual(validacao['counts']['alteracao_sigla'], 0)

    def test_fg_flexibility_limits_follow_resolution_by_dimensionamento(self):
        scenarios = [
            ('POLO', 1, 2),
            ('40_26', 3, 4),
            ('150', 6, 7),
        ]
        fg = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        for chave, limite, changes in scenarios:
            dim, _ = Dimensionamento.objects.get_or_create(chave=chave, defaults={'nome': f'Modelo {chave}'})
            modelo = ModeloReferencial.objects.create(nome=f'Modelo {chave}', dimensionamento=dim, ativo=True)
            campus = Campus.objects.create(nome=f'Campus {chave}', sigla=f'{chave}-IFMG', dimensionamento_fk=dim, modelo_referencial_padrao=modelo)
            raiz_modelo = UnitModelo.objects.create(modelo=modelo, nome_unidade='IFMG Campus Teste', ordem=1)
            regras = RegrasAlteracaoModelo.objects.create(modelo_referencial=modelo, limite_flexibilizacao_fg=limite)
            organograma = Organograma.objects.create(campus=campus, modelo_base=modelo, status='RASCUNHO')
            raiz = Unit.objects.create(organograma=organograma, origem_modelo=raiz_modelo, nome_unidade='IFMG Campus Teste', ordem=1)
            for index in range(changes):
                origem = UnitModelo.objects.create(
                    modelo=modelo,
                    unidade_pai=raiz_modelo,
                    cargo_funcao_ref=fg,
                    nome_unidade=f'Setor de Area {index}',
                    ordem=index + 2,
                )
                Unit.objects.create(
                    organograma=organograma,
                    origem_modelo=origem,
                    unidade_pai=raiz,
                    cargo_funcao_ref=fg,
                    nome_unidade=f'Setor de Area Alterada {index}',
                    ordem=index + 2,
                )

            validacao = validate_organograma_governance(organograma, persist_links=True)

            self.assertEqual(validacao['counts']['flexibilizacao_fg'], changes)
            self.assertTrue(any('Limite de flexibilização excedido' in error for error in validacao['errors']))
            self.assertTrue(validacao['quota_exceeded'])
            self.assertEqual(validacao['blocking_entries'], [])
            self.assertIn('Cota de flexibiliza', validacao['html'])
            self.assertIn('Compoe o somatorio excedido', validacao['html'])
            self.assertNotIn('Impeditivo', validacao['html'])

    def test_transition_rule_allows_five_changes_for_40_26(self):
        fg = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        ModeloReferencialCotaCargo.objects.create(modelo_referencial=self.modelo, cargo_funcao=fg, quantidade=5)
        self.regras.limite_flexibilizacao_fg = 3
        self.regras.permite_regra_transicao = True
        self.regras.save(update_fields=['limite_flexibilizacao_fg', 'permite_regra_transicao'])
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(organograma=organograma, origem_modelo=self.raiz_modelo, nome_unidade='IFMG Campus Teste', ordem=1)
        for index in range(5):
            origem = UnitModelo.objects.create(
                modelo=self.modelo,
                unidade_pai=self.raiz_modelo,
                cargo_funcao_ref=fg,
                nome_unidade=f'Setor de Transicao {index}',
                ordem=index + 2,
            )
            Unit.objects.create(
                organograma=organograma,
                origem_modelo=origem,
                unidade_pai=raiz,
                cargo_funcao_ref=fg,
                nome_unidade=f'Setor de Transicao Ajustado {index}',
                ordem=index + 2,
            )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertEqual(validacao['counts']['flexibilizacao_fg'], 5)
        self.assertEqual(validacao['errors'], [])

    def test_report_marks_permitted_fg_difference_as_counted(self):
        fg = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        ModeloReferencialCotaCargo.objects.create(modelo_referencial=self.modelo, cargo_funcao=fg, quantidade=1)
        origem = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Apoio',
            ordem=2,
        )
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(organograma=organograma, origem_modelo=self.raiz_modelo, nome_unidade='IFMG Campus Teste', ordem=1)
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem,
            unidade_pai=raiz,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Apoio Administrativo',
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertEqual(validacao['errors'], [])
        self.assertEqual(validacao['counts']['flexibilizacao_fg'], 1)
        self.assertIn('Conta na cota?', validacao['html'])
        self.assertIn('>Sim</span>', validacao['html'])
        self.assertIn('Base legal:', validacao['html'])
        self.assertIn('Art. 3º, caput', validacao['html'])
        self.assertIn('Flexibilização utilizada: <b>1</b> de <b>3</b>. Saldo: <b>2</b>.', validacao['html'])

    def test_report_lists_only_pending_rows(self):
        fg = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        ModeloReferencialCotaCargo.objects.create(modelo_referencial=self.modelo, cargo_funcao=fg, quantidade=1)
        origem = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Apoio',
            ordem=2,
        )
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(organograma=organograma, origem_modelo=self.raiz_modelo, nome_unidade='IFMG Campus Teste', ordem=1)
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem,
            unidade_pai=raiz,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Apoio Administrativo',
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertIn('Setor de Apoio Administrativo', validacao['html'])
        self.assertNotIn('IFMG Campus Teste</td>', validacao['html'])
        self.assertNotIn('Sem diferen', validacao['html'])

    def test_model_rule_flexible_prefixes_drive_quota_counting(self):
        fx = CargoFuncao.objects.create(nome='Chefe Especial', sigla='FX-01')
        self.regras.prefixos_cargos_flexibilizaveis = 'FX'
        self.regras.save(update_fields=['prefixos_cargos_flexibilizaveis'])
        origem = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            cargo_funcao_ref=fx,
            nome_unidade='Setor de Apoio',
            ordem=2,
        )
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(organograma=organograma, origem_modelo=self.raiz_modelo, nome_unidade='IFMG Campus Teste', ordem=1)
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem,
            unidade_pai=raiz,
            cargo_funcao_ref=fx,
            nome_unidade='Setor de Apoio Administrativo',
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertEqual(validacao['counts']['flexibilizacao_fg'], 1)

    def test_additional_and_missing_units_are_not_counted_in_quota(self):
        fg = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            cargo_funcao_ref=fg,
            nome_unidade='Setor Previsto',
            ordem=2,
        )
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(organograma=organograma, origem_modelo=self.raiz_modelo, nome_unidade='IFMG Campus Teste', ordem=1)
        Unit.objects.create(
            organograma=organograma,
            unidade_pai=raiz,
            cargo_funcao_ref=fg,
            nome_unidade='Setor Adicional',
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertEqual(validacao['counts']['inclusao_unidade_nova'], 1)
        self.assertEqual(validacao['counts']['exclusao_unidade_modelo'], 1)
        self.assertEqual(validacao['counts']['flexibilizacao_fg'], 0)
        self.assertTrue(any('unidade adicional não prevista no modelo referencial' in error for error in validacao['errors']))
        self.assertTrue(any('unidade prevista no modelo referencial ausente na proposta' in error for error in validacao['errors']))
        self.assertIn('Conta na cota?', validacao['html'])
        self.assertIn('>Não</span>', validacao['html'])

    def test_proposal_builder_blocks_new_units(self):
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='PROPOSTA')
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            ordem=1,
        )
        User = get_user_model()
        user = User.objects.create_user(username='staff-create-block', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)

        response = client.post(
            reverse('organograma_build', args=[organograma.id]),
            {
                'unidade_pai': '',
                'tipo_unidade': '',
                'cargo_funcao_ref': '',
                'cargo_funcao': '',
                'sigla_cargo': '',
                'nome_unidade': 'Setor Adicional',
                'sigla_unidade': 'SAD',
                'atribuicoes': '',
                'layout_filhos': 'V',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(organograma.unidades.count(), 1)
        self.assertIn('não permitem incluir', response.json()['html'])

    def test_proposal_builder_renders_restricted_structure_mode(self):
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='PROPOSTA')
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            ordem=1,
        )
        User = get_user_model()
        user = User.objects.create_user(username='staff-render-restricted', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)

        response = client.get(reverse('organograma_build', args=[organograma.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Solicitação de alteração')
        self.assertContains(response, 'Selecione uma Caixinha')
        self.assertContains(response, 'const allowStructureChanges = false;')
        self.assertContains(response, 'window.checkPendingNavigation')
        self.assertContains(response, reverse('organograma_validate_ajax', args=[organograma.id]))
        self.assertContains(response, 'allowedTipoIds')
        self.assertContains(response, 'allowedCargoIds')
        self.assertContains(response, 'window.moveNode')
        self.assertContains(response, 'function stripSiglaPrefix')
        self.assertContains(response, "setFieldValue('id_sigla_unidade', stripSiglaPrefix(node.sigla))")
        self.assertContains(response, 'function showValidationPopup')
        self.assertContains(response, 'padding: 8px 142px 8px 44px;')
        self.assertContains(response, 'function applyMixedChildLayout')
        self.assertContains(response, "node.data.layout_filhos === 'V'")
        self.assertContains(response, 'function linkPathForMixedLayout')
        self.assertContains(response, "link.source.data.layout_filhos === 'V'")
        self.assertContains(response, 'const sourceLeft = sx - boxWidth / 2;')
        self.assertContains(response, 'const spineX = sourceLeft;')
        self.assertContains(response, 'const targetSideY = link.target.y;')
        self.assertContains(response, 'V${targetSideY} H${targetLeft}')
        self.assertContains(response, 'competencias-empty-warning')
        self.assertContains(response, '.warning-banner')
        self.assertContains(response, 'function setCargoRefLocked')
        self.assertContains(response, 'cargo-ref-locked')
        self.assertContains(response, 'dataset.lockedByTipo')
        self.assertContains(response, 'setCargoRefLocked(cargoRef, !allowsCargoChoice || allowedCargoIds.length <= 1)')
        self.assertContains(response, 'preserveCargo')
        self.assertContains(response, 'builder-form-compact')
        self.assertContains(response, '.pending-badge')
        self.assertContains(response, '.node-box:hover .node-box-actions')
        self.assertContains(response, 'width: 45px !important;')
        self.assertContains(response, 'window.toggleExpand')
        self.assertContains(response, 'window.centerOnNode')

    def test_proposal_builder_blocks_unit_deletion(self):
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='PROPOSTA')
        unidade = Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            ordem=1,
        )
        User = get_user_model()
        user = User.objects.create_user(username='staff-delete-block', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)

        response = client.post(
            reverse('organograma_unit_delete', args=[organograma.id, unidade.id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Unit.objects.filter(pk=unidade.pk).exists())
        self.assertIn('não permitem incluir', response.json()['html'])

    def test_cd_units_are_not_flexible(self):
        cd = CargoFuncao.objects.create(nome='Diretor', sigla='CD-04')
        origem = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            cargo_funcao_ref=cd,
            nome_unidade='Diretoria de Ensino',
            ordem=2,
        )
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(organograma=organograma, origem_modelo=self.raiz_modelo, nome_unidade='IFMG Campus Teste', ordem=1)
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem,
            unidade_pai=raiz,
            cargo_funcao_ref=cd,
            nome_unidade='Diretoria Academica',
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertTrue(any('cargo de direção (CD)' in error for error in validacao['errors']))

    def test_link_only_departments_accept_only_parent_change(self):
        fg = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        ModeloReferencialCotaCargo.objects.create(modelo_referencial=self.modelo, cargo_funcao=fg, quantidade=1)
        origem_pai = UnitModelo.objects.create(modelo=self.modelo, unidade_pai=self.raiz_modelo, nome_unidade='Diretoria A', ordem=2)
        novo_pai = UnitModelo.objects.create(modelo=self.modelo, unidade_pai=self.raiz_modelo, nome_unidade='Diretoria B', ordem=3)
        origem = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=origem_pai,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Gestao de Pessoas',
            ordem=4,
        )
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(organograma=organograma, origem_modelo=self.raiz_modelo, nome_unidade='IFMG Campus Teste', ordem=1)
        pai_a = Unit.objects.create(organograma=organograma, origem_modelo=origem_pai, unidade_pai=raiz, nome_unidade='Diretoria A', ordem=2)
        pai_b = Unit.objects.create(organograma=organograma, origem_modelo=novo_pai, unidade_pai=raiz, nome_unidade='Diretoria B', ordem=3)
        unidade = Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem,
            unidade_pai=pai_b,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Gestao de Pessoas',
            ordem=4,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)
        self.assertEqual(validacao['errors'], [])

        unidade.nome_unidade = 'Setor de Desenvolvimento de Pessoas'
        unidade.unidade_pai = pai_a
        unidade.save(update_fields=['nome_unidade', 'unidade_pai'])
        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertTrue(any('flexível apenas quanto à vinculação' in error for error in validacao['errors']))
        self.assertIn('Impeditivo', validacao['html'])
        self.assertIn('background:#fff5f5', validacao['html'])
        self.assertIn('Art. 3º, §3º', validacao['html'])

    def test_annex_vii_prefix_is_preserved(self):
        fg = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        origem = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Biblioteca',
            ordem=2,
        )
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(organograma=organograma, origem_modelo=self.raiz_modelo, nome_unidade='IFMG Campus Teste', ordem=1)
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem,
            unidade_pai=raiz,
            cargo_funcao_ref=fg,
            nome_unidade='Nucleo de Biblioteca',
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertTrue(any('Anexo VII' in error for error in validacao['errors']))

    def test_setor_and_secao_prefixes_are_interchangeable_within_fg_quota(self):
        fg1 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        fg2 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-02')
        ModeloReferencialCotaCargo.objects.create(modelo_referencial=self.modelo, cargo_funcao=fg1, quantidade=1)
        origem = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            cargo_funcao_ref=fg2,
            nome_unidade='Seção de Planejamento e Controle Acadêmico',
            ordem=2,
        )
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            ordem=1,
        )
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem,
            unidade_pai=raiz,
            cargo_funcao_ref=fg1,
            nome_unidade='Setor de Planejamento e Controle Acadêmico',
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertEqual(validacao['errors'], [])
        self.assertEqual(validacao['counts']['flexibilizacao_fg'], 1)
        self.assertIn('>Sim</span>', validacao['html'])

    def test_consup44_loader_is_idempotent_and_creates_six_models(self):
        call_command('load_consup44_modelos', verbosity=0)
        first_count = UnitModelo.objects.count()
        call_command('load_consup44_modelos', verbosity=0)
        second_count = UnitModelo.objects.count()

        self.assertEqual(
            ModeloReferencial.objects.filter(resolucao_referencia='Resolução CONSUP 44/2025').count(),
            6,
        )
        self.assertEqual(first_count, second_count)
        self.assertTrue(UnitModelo.objects.filter(nome_unidade='Coordenadoria de Prospecção e Gestão de Projetos de PD&I').exists())

    def test_model_update_can_require_adequacao(self):
        organograma = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            modelo_referencia_atualizado_em=timezone.now() - timedelta(days=2),
            status='OFICIAL',
        )
        self.regras.exigir_adequacao_quando_modelo_mudar = True
        self.regras.save(update_fields=['exigir_adequacao_quando_modelo_mudar'])
        ModeloReferencial.objects.filter(pk=self.modelo.pk).update(data_atualizacao=timezone.now())
        self.modelo.refresh_from_db()
        organograma.refresh_from_db()

        self.assertTrue(organograma.precisa_adequacao_modelo)

    def test_generic_model_unit_is_marked_as_pending_after_clone(self):
        cargo_generico = CargoFuncao.objects.create(nome='Chefe', sigla='FG')
        tipo_setor = TipoUnidade.objects.create(nome='Setor')
        tipo_secao = TipoUnidade.objects.create(nome='Seção')
        fg1 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        fg2 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-02')
        tipo_setor.dimensionamentos_permitidos.add(self.dimensionamento)
        tipo_secao.dimensionamentos_permitidos.add(self.dimensionamento)
        cargo_generico.dimensionamentos_permitidos.add(self.dimensionamento)
        fg1.dimensionamentos_permitidos.add(self.dimensionamento)
        fg2.dimensionamentos_permitidos.add(self.dimensionamento)

        pendente_modelo = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            cargo_funcao=cargo_generico.nome,
            nome_unidade='Setor ou Seção de Biblioteca',
            sigla_unidade='SBI',
            ordem=2,
            permite_resolucao_flexivel=True,
        )
        pendente_modelo.tipos_resolucao_permitidos.set([tipo_setor, tipo_secao])
        pendente_modelo.cargos_resolucao_permitidos.set([fg1, fg2])
        organograma = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            status='RASCUNHO',
        )
        raiz = Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )
        unidade = Unit.objects.create(
            organograma=organograma,
            origem_modelo=pendente_modelo,
            unidade_pai=raiz,
            cargo_funcao=cargo_generico.nome,
            nome_unidade='Setor ou Seção de Biblioteca',
            sigla_unidade='CTS-SBI',
            ordem=2,
        )

        self.assertTrue(unidade.has_pending_definition)
        self.assertTrue(organograma.has_pending_units)

    def test_edit_form_keeps_generic_type_available_for_transition(self):
        cargo_generico = CargoFuncao.objects.create(nome='Chefe', sigla='FG')
        tipo_setor = TipoUnidade.objects.create(nome='Setor')
        tipo_secao = TipoUnidade.objects.create(nome='Seção')
        fg1 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        fg2 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-02')
        for obj in (tipo_setor, tipo_secao):
            obj.dimensionamentos_permitidos.add(self.dimensionamento)
        for cargo in (cargo_generico, fg1, fg2):
            cargo.dimensionamentos_permitidos.add(self.dimensionamento)

        origem_modelo = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            cargo_funcao='Chefe',
            nome_unidade='Setor ou Seção de Biblioteca',
            sigla_unidade='SBI',
            ordem=2,
            permite_resolucao_flexivel=True,
        )
        origem_modelo.tipos_resolucao_permitidos.set([tipo_setor, tipo_secao])
        origem_modelo.cargos_resolucao_permitidos.set([fg1, fg2])

        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        unidade = Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem_modelo,
            cargo_funcao='Chefe',
            nome_unidade='Setor ou Seção de Biblioteca',
            sigla_unidade='CTS-SBI',
            ordem=1,
        )

        form = UnitForm(instance=unidade, organograma_id=organograma.id)

        tipo_ids = list(form.fields['tipo_unidade'].queryset.values_list('id', flat=True))
        self.assertIn(tipo_setor.id, tipo_ids)
        self.assertIn(tipo_secao.id, tipo_ids)

    def test_flexible_model_unit_exposes_allowed_resolution_options(self):
        tipo_setor = TipoUnidade.objects.create(nome='Setor')
        tipo_secao = TipoUnidade.objects.create(nome='Seção')
        fg1 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        fg2 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-02')
        for obj in (tipo_setor, tipo_secao):
            obj.dimensionamentos_permitidos.add(self.dimensionamento)
        for cargo in (fg1, fg2):
            cargo.dimensionamentos_permitidos.add(self.dimensionamento)

        origem_modelo = UnitModelo.objects.create(
            modelo=self.modelo,
            nome_unidade='Setor ou Seção de Biblioteca',
            sigla_unidade='SBI',
            cargo_funcao='Chefe',
            ordem=2,
            permite_resolucao_flexivel=True,
        )
        origem_modelo.tipos_resolucao_permitidos.set([tipo_setor, tipo_secao])
        origem_modelo.cargos_resolucao_permitidos.set([fg1, fg2])

        self.assertTrue(origem_modelo.has_flexible_resolution)
        self.assertEqual(set(origem_modelo.allowed_tipo_ids), {tipo_setor.id, tipo_secao.id})
        self.assertEqual(set(origem_modelo.allowed_cargo_ids), {fg1.id, fg2.id})

    def test_flexible_resolution_does_not_count_as_governance_change(self):
        tipo_setor = TipoUnidade.objects.create(nome='Setor')
        tipo_secao = TipoUnidade.objects.create(nome='Seção')
        fg1 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        fg2 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-02')
        for obj in (tipo_setor, tipo_secao):
            obj.dimensionamentos_permitidos.add(self.dimensionamento)
        for cargo in (fg1, fg2):
            cargo.dimensionamentos_permitidos.add(self.dimensionamento)

        origem_modelo = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            nome_unidade='Setor ou Seção de Biblioteca',
            sigla_unidade='SBI',
            cargo_funcao='Chefe',
            ordem=2,
            permite_resolucao_flexivel=True,
        )
        origem_modelo.tipos_resolucao_permitidos.set([tipo_setor, tipo_secao])
        origem_modelo.cargos_resolucao_permitidos.set([fg1, fg2])

        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem_modelo,
            unidade_pai=raiz,
            tipo_unidade=tipo_setor,
            cargo_funcao_ref=fg1,
            nome_unidade='Setor de Biblioteca',
            sigla_unidade='CTS-SBI',
            ordem=2,
        )
        ModeloReferencialCotaCargo.objects.create(modelo_referencial=self.modelo, cargo_funcao=fg1, quantidade=1)

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertEqual(validacao['errors'], [])
        self.assertEqual(validacao['counts']['alteracao_tipo_unidade'], 0)
        self.assertEqual(validacao['counts']['alteracao_cargo'], 0)

    def test_prefixed_sigla_from_campus_is_not_counted_as_sigla_change(self):
        child_model = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            nome_unidade='Diretoria de Ensino',
            sigla_unidade='DE',
            ordem=2,
        )
        organograma = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            status='RASCUNHO',
        )
        raiz = Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=child_model,
            unidade_pai=raiz,
            nome_unidade='Diretoria de Ensino',
            sigla_unidade='CTS-DE',
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)

        self.assertEqual(validacao['counts']['alteracao_sigla'], 0)
        self.assertEqual(validacao['errors'], [])

    def test_recreated_unit_under_same_parent_is_blocked_and_does_not_count_cota(self):
        tipo_setor = TipoUnidade.objects.create(nome='Setor')
        fg = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        tipo_setor.dimensionamentos_permitidos.add(self.dimensionamento)
        fg.dimensionamentos_permitidos.add(self.dimensionamento)
        origem = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            tipo_unidade=tipo_setor,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Biblioteca',
            ordem=2,
        )
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )
        unidade_recriada = Unit.objects.create(
            organograma=organograma,
            unidade_pai=raiz,
            tipo_unidade=tipo_setor,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Biblioteca e Arquivo',
            sigla_unidade='CTS-SBA',
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)
        unidade_recriada.refresh_from_db()

        self.assertIsNone(unidade_recriada.origem_modelo_id)
        self.assertEqual(validacao['counts']['renomeacao'], 0)
        self.assertEqual(validacao['counts']['inclusao_unidade_nova'], 1)
        self.assertEqual(validacao['counts']['exclusao_unidade_modelo'], 1)
        self.assertEqual(validacao['counts']['flexibilizacao_fg'], 0)
        self.assertTrue(any('unidade adicional não prevista no modelo referencial' in error for error in validacao['errors']))
        self.assertTrue(any('unidade prevista no modelo referencial ausente na proposta' in error for error in validacao['errors']))

    def test_recreated_fg_unit_with_new_parent_is_blocked_and_does_not_count_cota(self):
        tipo_setor = TipoUnidade.objects.create(nome='Setor')
        fg = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        tipo_setor.dimensionamentos_permitidos.add(self.dimensionamento)
        fg.dimensionamentos_permitidos.add(self.dimensionamento)
        diretoria_modelo = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            nome_unidade='Diretoria Administrativa',
            ordem=2,
        )
        origem = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=diretoria_modelo,
            tipo_unidade=tipo_setor,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Almoxarifado e Patrimônio',
            ordem=3,
        )
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )
        Unit.objects.create(
            organograma=organograma,
            origem_modelo=diretoria_modelo,
            unidade_pai=raiz,
            nome_unidade='Diretoria Administrativa',
            ordem=2,
        )
        unidade_recriada = Unit.objects.create(
            organograma=organograma,
            unidade_pai=raiz,
            tipo_unidade=tipo_setor,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Comunicação',
            sigla_unidade='CTS-SCOM',
            ordem=3,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)
        unidade_recriada.refresh_from_db()

        self.assertIsNone(unidade_recriada.origem_modelo_id)
        self.assertEqual(validacao['counts']['renomeacao'], 0)
        self.assertEqual(validacao['counts']['mudanca_vinculo'], 0)
        self.assertEqual(validacao['counts']['inclusao_unidade_nova'], 1)
        self.assertEqual(validacao['counts']['exclusao_unidade_modelo'], 1)
        self.assertEqual(validacao['counts']['flexibilizacao_fg'], 0)
        self.assertTrue(any('unidade adicional não prevista no modelo referencial' in error for error in validacao['errors']))
        self.assertTrue(any('unidade prevista no modelo referencial ausente na proposta' in error for error in validacao['errors']))

    def test_inferred_link_from_previous_source_is_cleared_when_source_does_not_match_model(self):
        tipo_setor = TipoUnidade.objects.create(nome='Setor')
        fg = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        tipo_setor.dimensionamentos_permitidos.add(self.dimensionamento)
        fg.dimensionamentos_permitidos.add(self.dimensionamento)
        origem = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            tipo_unidade=tipo_setor,
            cargo_funcao_ref=fg,
            nome_unidade='Setor de Almoxarifado e Patrimônio',
            ordem=2,
        )
        organograma_original = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='OFICIAL')
        unidade_original = Unit.objects.create(
            organograma=organograma_original,
            nome_unidade='Setor de Comunicação',
            tipo_unidade=tipo_setor,
            cargo_funcao_ref=fg,
            ordem=1,
        )
        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='PROPOSTA')
        raiz = Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            ordem=1,
        )
        unidade_proposta = Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem,
            source_unit=unidade_original,
            unidade_pai=raiz,
            nome_unidade='Setor de Comunicação',
            tipo_unidade=tipo_setor,
            cargo_funcao_ref=fg,
            ordem=2,
        )

        validacao = validate_organograma_governance(organograma, persist_links=True)
        unidade_proposta.refresh_from_db()

        self.assertIsNone(unidade_proposta.origem_modelo_id)
        self.assertEqual(validacao['counts']['inclusao_unidade_nova'], 1)
        self.assertEqual(validacao['counts']['exclusao_unidade_modelo'], 1)

    def test_builder_json_keeps_pending_definition_metadata(self):
        cargo_generico = CargoFuncao.objects.create(nome='Chefe', sigla='FG')
        tipo_setor = TipoUnidade.objects.create(nome='Setor')
        tipo_secao = TipoUnidade.objects.create(nome='Seção')
        fg1 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        fg2 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-02')
        for obj in (tipo_setor, tipo_secao):
            obj.dimensionamentos_permitidos.add(self.dimensionamento)
        for cargo in (cargo_generico, fg1, fg2):
            cargo.dimensionamentos_permitidos.add(self.dimensionamento)

        origem_modelo = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            cargo_funcao='Chefe',
            nome_unidade='Setor ou Seção de Biblioteca',
            sigla_unidade='SBI',
            ordem=2,
            permite_resolucao_flexivel=True,
        )
        origem_modelo.tipos_resolucao_permitidos.set([tipo_setor, tipo_secao])
        origem_modelo.cargos_resolucao_permitidos.set([fg1, fg2])

        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        unidade = Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem_modelo,
            cargo_funcao='Chefe',
            nome_unidade='Setor ou Seção de Biblioteca',
            sigla_unidade='CTS-SBI',
            ordem=1,
        )

        payload = _get_unidades_json_data([unidade])[0]

        self.assertTrue(payload['isPendingDefinition'])
        self.assertTrue(payload['isFlexibleSource'])
        self.assertEqual(set(payload['allowedTipoIds']), {tipo_setor.id, tipo_secao.id})
        self.assertEqual(set(payload['allowedCargoIds']), {fg1.id, fg2.id})

    def test_builder_forces_default_cargo_for_flexible_resolution_when_type_is_concrete(self):
        tipo_setor = TipoUnidade.objects.create(nome='Setor')
        tipo_secao = TipoUnidade.objects.create(nome='Seção')
        fg1 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        fg2 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-02')
        tipo_setor.cargo_padrao = fg1
        tipo_setor.save(update_fields=['cargo_padrao'])
        tipo_secao.cargo_padrao = fg2
        tipo_secao.save(update_fields=['cargo_padrao'])
        for obj in (tipo_setor, tipo_secao):
            obj.dimensionamentos_permitidos.add(self.dimensionamento)
        for cargo in (fg1, fg2):
            cargo.dimensionamentos_permitidos.add(self.dimensionamento)

        origem_modelo = UnitModelo.objects.create(
            modelo=self.modelo,
            unidade_pai=self.raiz_modelo,
            nome_unidade='Setor ou Seção de Biblioteca',
            sigla_unidade='SBI',
            cargo_funcao='Chefe',
            ordem=2,
            permite_resolucao_flexivel=True,
        )
        origem_modelo.tipos_resolucao_permitidos.set([tipo_setor, tipo_secao])
        origem_modelo.cargos_resolucao_permitidos.set([fg1, fg2])

        organograma = Organograma.objects.create(campus=self.campus, modelo_base=self.modelo, status='RASCUNHO')
        raiz = Unit.objects.create(
            organograma=organograma,
            origem_modelo=self.raiz_modelo,
            nome_unidade='IFMG Campus Teste',
            sigla_unidade='CTS-CTS',
            ordem=1,
        )
        unidade = Unit.objects.create(
            organograma=organograma,
            origem_modelo=origem_modelo,
            unidade_pai=raiz,
            nome_unidade='Setor ou Seção de Biblioteca',
            sigla_unidade='CTS-SBI',
            cargo_funcao='Chefe',
            ordem=2,
        )

        User = get_user_model()
        user = User.objects.create_user(username='staff', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)

        response = client.post(
            reverse('organograma_build', args=[organograma.id]) + f'?edit={unidade.id}',
            {
                'unidade_pai': raiz.id,
                'tipo_unidade': tipo_setor.id,
                'cargo_funcao_ref': fg2.id,
                'cargo_funcao': '',
                'sigla_cargo': '',
                'nome_unidade': 'Setor de Biblioteca',
                'sigla_unidade': 'SBI',
                'atribuicoes': '',
                'layout_filhos': 'V',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 400)
        unidade.refresh_from_db()
        self.assertIsNone(unidade.tipo_unidade_id)
        self.assertIsNone(unidade.cargo_funcao_ref_id)

    def test_model_form_derives_allowed_cargos_from_selected_types(self):
        tipo_setor = TipoUnidade.objects.create(nome='Setor')
        tipo_secao = TipoUnidade.objects.create(nome='Seção')
        fg1 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        fg2 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-02')
        tipo_setor.cargo_padrao = fg1
        tipo_setor.save(update_fields=['cargo_padrao'])
        tipo_secao.cargo_padrao = fg2
        tipo_secao.save(update_fields=['cargo_padrao'])
        for obj in (tipo_setor, tipo_secao):
            obj.dimensionamentos_permitidos.add(self.dimensionamento)
        for cargo in (fg1, fg2):
            cargo.dimensionamentos_permitidos.add(self.dimensionamento)

        form = UnitModeloForm(
            data={
                'nome_unidade': 'Setor ou Seção de Biblioteca',
                'sigla_unidade': 'SBI',
                'layout_filhos': 'V',
                'permite_resolucao_flexivel': 'on',
                'tipos_resolucao_permitidos': [tipo_setor.id, tipo_secao.id],
                'cargos_resolucao_permitidos': [],
            },
            modelo=self.modelo,
        )

        self.assertTrue(form.is_valid(), form.errors)
        cargos_ids = set(form.cleaned_data['cargos_resolucao_permitidos'].values_list('id', flat=True))
        self.assertEqual(cargos_ids, {fg1.id, fg2.id})


class CompetenciasUnidadeTests(TestCase):
    def setUp(self):
        self.dimensionamento = Dimensionamento.objects.create(nome='Campus 40/26', chave='40_26')
        self.modelo = ModeloReferencial.objects.create(nome='Modelo Campus', dimensionamento=self.dimensionamento, ativo=True)
        self.campus = Campus.objects.create(
            nome='Campus Competencias',
            sigla='CPT-IFMG',
            dimensionamento_fk=self.dimensionamento,
            modelo_referencial_padrao=self.modelo,
        )
        self.regimento_antigo = RegimentoCampus.objects.create(
            campus=self.campus,
            nome='Regimento Antigo',
            numero='Resolução 1/2024',
            vigente=False,
        )
        self.regimento_vigente = RegimentoCampus.objects.create(
            campus=self.campus,
            nome='Regimento Vigente',
            numero='Resolução 2/2026',
            vigente=True,
        )
        self.organograma = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='RASCUNHO',
        )
        self.unidade = Unit.objects.create(
            organograma=self.organograma,
            nome_unidade='Diretoria de Ensino',
            sigla_unidade='CPT-DE',
            ordem=1,
        )

    def test_campus_keeps_only_one_current_regimento(self):
        novo = RegimentoCampus.objects.create(
            campus=self.campus,
            nome='Regimento Mais Novo',
            numero='Resolução 3/2026',
            vigente=True,
        )
        self.regimento_vigente.refresh_from_db()

        self.assertTrue(novo.vigente)
        self.assertFalse(self.regimento_vigente.vigente)
        self.assertEqual(self.campus.regimentos.filter(vigente=True).count(), 1)

    def test_regimento_form_allows_replacing_current_regimento(self):
        form = RegimentoCampusForm(
            data={
                'campus': self.campus.id,
                'tipo': 'INTERNO',
                'nome': 'Regimento Mais Novo',
                'numero': 'Resolução 3/2026',
                'data_publicacao': '2026-05-06',
                'link': '',
                'vigente': 'on',
                'observacoes': '',
            },
            files={},
        )

        self.assertTrue(form.is_valid(), form.errors)
        novo = form.save()
        self.regimento_vigente.refresh_from_db()

        self.assertTrue(novo.vigente)
        self.assertFalse(self.regimento_vigente.vigente)
        self.assertEqual(self.campus.regimentos.filter(tipo='INTERNO', vigente=True).count(), 1)

    def test_new_current_regimento_versions_official_organograma(self):
        self.organograma.status = 'OFICIAL'
        self.organograma.save()
        CompetenciaUnidade.objects.create(
            unidade=self.unidade,
            regimento=self.regimento_vigente,
            artigo='8',
            texto='Executar as competências regimentais.',
        )

        novo = RegimentoCampus.objects.create(
            campus=self.campus,
            nome='Regimento Mais Novo',
            numero='Resolução 3/2026',
            vigente=True,
        )

        self.organograma.refresh_from_db()
        novo_oficial = Organograma.objects.get(campus=self.campus, status='OFICIAL')
        unidade_nova = novo_oficial.unidades.get(nome_unidade='Diretoria de Ensino')

        self.assertEqual(self.organograma.status, 'HISTORICO')
        self.assertEqual(self.organograma.regimento_referencia, self.regimento_vigente)
        self.assertEqual(novo_oficial.regimento_referencia, novo)
        self.assertEqual(unidade_nova.competencias.count(), 1)
        self.assertEqual(unidade_nova.competencias_status, 'desatualizada')

    def test_unit_competencia_status_and_organograma_summary(self):
        self.assertEqual(self.unidade.competencias_status, 'sem_competencias')
        self.assertEqual(self.organograma.competencias_resumo['sem_competencias'], 1)

        CompetenciaUnidade.objects.create(
            unidade=self.unidade,
            regimento=self.regimento_antigo,
            artigo='10',
            inciso='II',
            texto='Planejar as ações de ensino.',
        )

        self.assertEqual(self.unidade.competencias_status, 'desatualizada')
        resumo = self.organograma.competencias_resumo
        self.assertEqual(resumo['desatualizadas'], 1)
        self.assertTrue(resumo['tem_alertas'])

        self.unidade.competencias.all().update(regimento=self.regimento_vigente)
        self.assertEqual(self.unidade.competencias_status, 'revisada')
        resumo = self.organograma.competencias_resumo
        self.assertEqual(resumo['revisadas'], 1)
        self.assertFalse(resumo['tem_alertas'])

    def test_competencia_reference_orders_art_inciso_alinea_paragrafo(self):
        competencia = CompetenciaUnidade.objects.create(
            unidade=self.unidade,
            regimento=self.regimento_vigente,
            artigo='12',
            inciso='II',
            alinea='a',
            paragrafo='1',
            texto='Coordenar processos academicos.',
        )

        self.assertEqual(competencia.referencia_formatada, 'Art. 12, inciso II, alínea a, § 1')

    def test_builder_json_uses_structured_competencias_not_legacy_text(self):
        self.unidade.atribuicoes = 'Texto legado que não deve virar competência.'
        self.unidade.save(update_fields=['atribuicoes'])
        CompetenciaUnidade.objects.create(
            unidade=self.unidade,
            regimento=self.regimento_vigente,
            artigo='12',
            texto='Coordenar processos acadêmicos.',
        )

        payload = _get_unidades_json_data([self.unidade])[0]

        self.assertNotIn('atribuicoes', payload)
        self.assertEqual(payload['competenciasCount'], 1)
        self.assertEqual(payload['competencias'][0]['texto'], 'Coordenar processos acadêmicos.')
        self.assertEqual(payload['competenciasStatus'], 'revisada')
        self.assertIn('regimentoUrl', payload['competencias'][0])

    def test_detail_exposes_competencias_modal_state_for_public_and_logged_views(self):
        self.organograma.status = 'OFICIAL'
        self.organograma.save(update_fields=['status'])
        CompetenciaUnidade.objects.create(
            unidade=self.unidade,
            regimento=self.regimento_vigente,
            artigo='12',
            texto='Coordenar processos academicos.',
        )

        client = Client()
        response = client.get(reverse('organograma_detail', args=[self.organograma.id]))

        self.assertContains(response, 'Coordenar processos academicos.')
        self.assertContains(response, 'window.showCompetenciasPendencias = showCompetenciasPendencias;')
        self.assertContains(response, 'window.showCompetenciasPendencias && !c.atualizada')
        self.assertContains(response, 'const grupos = competencias.reduce')
        self.assertContains(response, 'grupo.competencias.map')
        self.assertContains(response, 'const modalHost = document.fullscreenElement || document.body;')
        self.assertContains(response, "modalHost.insertAdjacentHTML('beforeend', modalHtml);")
        self.assertContains(response, 'Abrir regimento')
        self.assertContains(response, 'const showCompetenciasPendencias = false')

        user = get_user_model().objects.create_user(username='viewer', password='senha', is_staff=True)
        client.force_login(user)
        response = client.get(reverse('organograma_detail', args=[self.organograma.id]))

        self.assertContains(response, 'Coordenar processos academicos.')
        self.assertContains(response, 'const showCompetenciasPendencias = true')

    def test_competencias_are_copied_when_creating_proposal(self):
        CompetenciaUnidade.objects.create(
            unidade=self.unidade,
            regimento=self.regimento_vigente,
            artigo='8',
            texto='Executar as competências regimentais.',
        )
        user = get_user_model().objects.create_user(username='campus-staff', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)
        self.organograma.status = 'OFICIAL'
        self.organograma.save(update_fields=['status'])

        response = client.post(
            reverse('solicitacao_create', args=[self.organograma.id]),
            {'justificativa': 'Atualização estrutural.'},
        )

        self.assertEqual(response.status_code, 302)
        proposta = Organograma.objects.get(status='PROPOSTA')
        unidade_proposta = proposta.unidades.get(nome_unidade=self.unidade.nome_unidade)
        competencia = unidade_proposta.competencias.get()
        self.assertEqual(proposta.regimento_referencia, self.regimento_vigente)
        self.assertEqual(competencia.regimento, self.regimento_vigente)
        self.assertEqual(competencia.texto, 'Executar as competências regimentais.')
    def test_solicitacao_list_shows_new_request_button(self):
        user = get_user_model().objects.create_user(username='campus-lista', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)

        response = client.get(reverse('solicitacao_list'))

        self.assertContains(response, reverse('solicitacao_create_select'))
        self.assertContains(response, 'Nova Solicita')

    def test_select_campus_redirects_to_create_request_for_official_organograma(self):
        self.organograma.status = 'OFICIAL'
        self.organograma.save(update_fields=['status'])
        user = get_user_model().objects.create_user(username='campus-selecao', password='senha')
        user.profile.campus = self.campus
        user.profile.save()
        client = Client()
        client.force_login(user)

        response = client.post(reverse('solicitacao_create_select'), {'campus': self.campus.id})

        self.assertRedirects(response, reverse('solicitacao_create', args=[self.organograma.id]), fetch_redirect_response=False)

    def test_created_request_stays_draft_until_requester_submits_for_analysis(self):
        self.organograma.status = 'OFICIAL'
        origem = UnitModelo.objects.create(
            modelo=self.modelo,
            nome_unidade='Diretoria de Ensino',
            ordem=1,
        )
        self.unidade.origem_modelo = origem
        self.unidade.save(update_fields=['origem_modelo'])
        self.organograma.save(update_fields=['status'])
        user = get_user_model().objects.create_user(username='campus-rascunho', password='senha')
        user.profile.campus = self.campus
        user.profile.save()
        client = Client()
        client.force_login(user)

        response = client.post(
            reverse('solicitacao_create', args=[self.organograma.id]),
            {'justificativa': 'Atualizacao estrutural em preparacao.'},
        )

        self.assertEqual(response.status_code, 302)
        solicitacao = SolicitacaoAlteracao.objects.get()
        self.assertEqual(solicitacao.status, 'RASCUNHO')

        response = client.post(reverse('solicitacao_resubmit', args=[solicitacao.id]))

        self.assertEqual(response.status_code, 302)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, 'EM_ANALISE')

    def test_request_with_governance_pending_cannot_be_submitted_for_analysis(self):
        self.organograma.status = 'OFICIAL'
        self.organograma.save(update_fields=['status'])
        user = get_user_model().objects.create_user(username='campus-pendencia', password='senha')
        user.profile.campus = self.campus
        user.profile.save()
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        Unit.objects.create(
            organograma=proposta,
            nome_unidade='Unidade fora do modelo',
            sigla_unidade='CPT-UFM',
            ordem=1,
        )
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=user,
            justificativa='Ajuste com pendencia.',
            status='RASCUNHO',
        )
        client = Client()
        client.force_login(user)

        response = client.post(reverse('solicitacao_resubmit', args=[solicitacao.id]))

        self.assertEqual(response.status_code, 302)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, 'RASCUNHO')

    def test_requester_can_edit_draft_proposal_unit_before_submission(self):
        self.organograma.status = 'OFICIAL'
        self.organograma.save(update_fields=['status'])
        user = get_user_model().objects.create_user(username='campus-edita-rascunho', password='senha')
        user.profile.campus = self.campus
        user.profile.save()
        client = Client()
        client.force_login(user)
        client.post(
            reverse('solicitacao_create', args=[self.organograma.id]),
            {'justificativa': 'Ajuste inicial.'},
        )
        solicitacao = SolicitacaoAlteracao.objects.get()
        unidade_proposta = solicitacao.organograma_proposto.unidades.get(source_unit=self.unidade)

        response = client.post(
            reverse('organograma_build', args=[solicitacao.organograma_proposto.id]) + f'?edit={unidade_proposta.id}',
            {
                'nome_unidade': 'Diretoria de Ensino Atualizada',
                'sigla_unidade': 'CPT-DEA',
                'unidade_pai': '',
                'tipo_unidade': '',
                'cargo_funcao_ref': '',
                'cargo_funcao': '',
                'sigla_cargo': '',
                'layout_filhos': 'V',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        unidade_proposta.refresh_from_db()
        self.assertEqual(unidade_proposta.nome_unidade, 'Diretoria de Ensino Atualizada')

    def test_import_competencias_from_csv_creates_multiple_rows(self):
        user = get_user_model().objects.create_user(username='competencias-import-csv', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)
        upload = SimpleUploadedFile(
            'competencias.csv',
            (
                'artigo,inciso,alinea,paragrafo,texto\n'
                '12,II,a,1,Coordenar os processos academicos.\n'
                '13,,,,Planejar as acoes de ensino.\n'
            ).encode('utf-8'),
            content_type='text/csv',
        )

        response = client.post(
            reverse('unidade_competencias_importar', args=[self.organograma.id, self.unidade.id]),
            {'arquivo': upload, 'regimento_id': self.regimento_vigente.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['importedCount'], 2)
        competencias = list(self.unidade.competencias.order_by('ordem'))
        self.assertEqual([c.texto for c in competencias], [
            'Coordenar os processos academicos.',
            'Planejar as acoes de ensino.',
        ])
        self.assertEqual(competencias[0].artigo, '12')
        self.assertEqual(competencias[0].inciso, 'II')
        self.assertEqual(competencias[0].alinea, 'a')
        self.assertEqual(competencias[0].paragrafo, '1')
        self.assertEqual(competencias[1].artigo, '13')
        self.assertTrue(all(c.regimento == self.regimento_vigente for c in competencias))

    def test_import_competencias_from_txt_uses_one_nonblank_line_per_row(self):
        user = get_user_model().objects.create_user(username='competencias-import-txt', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)
        upload = SimpleUploadedFile(
            'competencias.txt',
            'Coordenar processos.\n\nPlanejar acoes.\n'.encode('utf-8'),
            content_type='text/plain',
        )

        response = client.post(
            reverse('unidade_competencias_importar', args=[self.organograma.id, self.unidade.id]),
            {'arquivo': upload, 'regimento_id': self.regimento_vigente.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['importedCount'], 2)
        self.assertEqual(
            list(self.unidade.competencias.order_by('ordem').values_list('texto', flat=True)),
            ['Coordenar processos.', 'Planejar acoes.'],
        )

    def test_import_competencias_rejects_csv_without_text_column(self):
        user = get_user_model().objects.create_user(username='competencias-import-invalid', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)
        upload = SimpleUploadedFile(
            'competencias.csv',
            'artigo,descricao\n12,Sem coluna texto\n'.encode('utf-8'),
            content_type='text/csv',
        )

        response = client.post(
            reverse('unidade_competencias_importar', args=[self.organograma.id, self.unidade.id]),
            {'arquivo': upload, 'regimento_id': self.regimento_vigente.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.unidade.competencias.count(), 0)
        self.assertIn('texto', response.json()['errors']['arquivo'][0])

    def test_builder_shows_competencias_import_controls(self):
        user = get_user_model().objects.create_user(username='competencias-import-ui', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)

        response = client.get(reverse('organograma_build', args=[self.organograma.id]))

        self.assertContains(response, 'id="competenciasImportFile"', html=False)
        self.assertContains(response, 'id="competenciaFormWrap"', html=False)
        self.assertContains(response, 'window.saveCompetencia')
        self.assertContains(response, 'window.startCompetenciaCreate')
        self.assertContains(response, 'window.importCompetencias')
        self.assertContains(response, reverse('unidade_competencias_importar', args=[self.organograma.id, 999999]))
        self.assertContains(response, reverse('unidade_competencias', args=[self.organograma.id, 999999]))

    def test_proposal_starts_without_new_approval_resolution(self):
        resolucao = ResolucaoEstruturaOrganizacional.objects.create(
            campus=self.campus,
            nome='Resolucao da Estrutura',
            numero='1/2026',
            data_publicacao=date(2026, 5, 6),
        )
        self.organograma.status = 'OFICIAL'
        self.organograma.resolucao_estrutura = resolucao
        self.organograma.data_vigencia = date(2026, 5, 6)
        self.organograma.nome_documento_aprovacao = 'Resolucao 1/2026'
        self.organograma.save(update_fields=['status', 'resolucao_estrutura', 'data_vigencia', 'nome_documento_aprovacao'])
        user = get_user_model().objects.create_user(username='campus-proposta', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)

        response = client.post(
            reverse('solicitacao_create', args=[self.organograma.id]),
            {'justificativa': 'Atualizacao com nova versao.'},
        )

        self.assertEqual(response.status_code, 302)
        proposta = Organograma.objects.get(status='PROPOSTA')
        self.assertIsNone(proposta.resolucao_estrutura)
        self.assertEqual(proposta.data_vigencia, date(2026, 5, 6))
        self.assertEqual(proposta.nome_documento_aprovacao, 'Resolucao 1/2026')

    def test_send_to_consup_keeps_current_official_active(self):
        resolucao_original = ResolucaoEstruturaOrganizacional.objects.create(
            campus=self.campus,
            nome='Resolucao Original',
            numero='2/2026',
            data_publicacao=date(2026, 5, 6),
        )
        self.organograma.status = 'OFICIAL'
        self.organograma.resolucao_estrutura = resolucao_original
        self.organograma.data_vigencia = date(2026, 5, 6)
        self.organograma.nome_documento_aprovacao = 'Resolucao 2/2026'
        self.organograma.save(update_fields=['status', 'resolucao_estrutura', 'data_vigencia', 'nome_documento_aprovacao'])
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=get_user_model().objects.create_user(username='solicitante', password='senha'),
            justificativa='Proposta criada antes do ajuste.',
            status='EM_ANALISE',
        )
        admin = get_user_model().objects.create_user(username='admin-proposta', password='senha', is_superuser=True)
        client = Client()
        client.force_login(admin)

        response = client.post(reverse('solicitacao_approve', args=[solicitacao.id]))

        self.assertEqual(response.status_code, 302)
        proposta.refresh_from_db()
        self.organograma.refresh_from_db()
        solicitacao.refresh_from_db()
        self.assertEqual(self.organograma.status, 'OFICIAL')
        self.assertEqual(proposta.status, 'PROPOSTA')
        self.assertEqual(solicitacao.status, 'ENVIADO_CONSUP')
        self.assertIsNone(proposta.data_aprovacao_sistema)

    def test_requester_cannot_edit_proposal_unit_while_request_is_under_analysis(self):
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        unidade_proposta = Unit.objects.create(
            organograma=proposta,
            source_unit=self.unidade,
            nome_unidade='Diretoria de Ensino',
            sigla_unidade='CPT-DE',
            ordem=1,
        )
        solicitante = get_user_model().objects.create_user(username='solicitante-bloqueio', password='senha')
        solicitante.profile.campus = self.campus
        solicitante.profile.save()
        SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=solicitante,
            justificativa='Proposta aguardando avaliacao.',
            status='EM_ANALISE',
        )
        client = Client()
        client.force_login(solicitante)

        response = client.post(
            reverse('organograma_build', args=[proposta.id]) + f'?edit={unidade_proposta.id}',
            {
                'nome_unidade': 'Diretoria Alterada Indevidamente',
                'sigla_unidade': 'CPT-DAI',
                'unidade_pai': '',
                'tipo_unidade': '',
                'cargo_funcao_ref': '',
                'cargo_funcao': '',
                'sigla_cargo': '',
                'layout_filhos': 'V',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 403)
        unidade_proposta.refresh_from_db()
        self.assertEqual(unidade_proposta.nome_unidade, 'Diretoria de Ensino')

    def test_requester_can_edit_proposal_unit_only_after_return_for_correction(self):
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        unidade_proposta = Unit.objects.create(
            organograma=proposta,
            source_unit=self.unidade,
            nome_unidade='Diretoria de Ensino',
            sigla_unidade='CPT-DE',
            ordem=1,
        )
        solicitante = get_user_model().objects.create_user(username='solicitante-libera', password='senha')
        solicitante.profile.campus = self.campus
        solicitante.profile.save()
        SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=solicitante,
            justificativa='Proposta devolvida para ajuste.',
            status='DEVOLVIDO_CORRECAO',
        )
        client = Client()
        client.force_login(solicitante)

        response = client.post(
            reverse('organograma_build', args=[proposta.id]) + f'?edit={unidade_proposta.id}',
            {
                'nome_unidade': 'Diretoria de Ensino Corrigida',
                'sigla_unidade': 'CPT-DEC',
                'unidade_pai': '',
                'tipo_unidade': '',
                'cargo_funcao_ref': '',
                'cargo_funcao': '',
                'sigla_cargo': '',
                'layout_filhos': 'V',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        unidade_proposta.refresh_from_db()
        self.assertEqual(unidade_proposta.nome_unidade, 'Diretoria de Ensino Corrigida')

    def test_requester_cannot_edit_proposal_metadata_while_request_is_under_analysis(self):
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        solicitante = get_user_model().objects.create_user(username='solicitante-meta-bloqueio', password='senha')
        solicitante.profile.campus = self.campus
        solicitante.profile.save()
        SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=solicitante,
            justificativa='Proposta aguardando avaliacao.',
            status='EM_ANALISE',
        )
        client = Client()
        client.force_login(solicitante)

        response = client.get(reverse('organograma_edit', args=[proposta.id]))

        self.assertEqual(response.status_code, 403)

    def test_final_consup_approval_requires_new_resolution_before_promoting_proposal(self):
        resolucao_original = ResolucaoEstruturaOrganizacional.objects.create(
            campus=self.campus,
            nome='Resolucao Original',
            numero='2/2026',
            data_publicacao=date(2026, 5, 6),
        )
        self.organograma.status = 'OFICIAL'
        self.organograma.resolucao_estrutura = resolucao_original
        self.organograma.save(update_fields=['status', 'resolucao_estrutura'])
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=get_user_model().objects.create_user(username='solicitante-consup', password='senha'),
            justificativa='Proposta enviada ao Consup.',
            status='ENVIADO_CONSUP',
        )
        admin = get_user_model().objects.create_user(username='admin-consup', password='senha', is_superuser=True)
        client = Client()
        client.force_login(admin)

        response = client.post(reverse('solicitacao_approve', args=[solicitacao.id]))

        self.assertEqual(response.status_code, 302)
        proposta.refresh_from_db()
        self.organograma.refresh_from_db()
        solicitacao.refresh_from_db()
        self.assertEqual(self.organograma.status, 'OFICIAL')
        self.assertEqual(proposta.status, 'PROPOSTA')
        self.assertEqual(solicitacao.status, 'ENVIADO_CONSUP')

        resolucao_nova = ResolucaoEstruturaOrganizacional.objects.create(
            campus=self.campus,
            nome='Resolucao Nova',
            numero='3/2026',
            data_publicacao=date(2026, 6, 10),
        )
        proposta.resolucao_estrutura = resolucao_nova
        proposta.data_vigencia = date(2026, 6, 10)
        proposta.save(update_fields=['resolucao_estrutura', 'data_vigencia'])

        response = client.post(reverse('solicitacao_approve', args=[solicitacao.id]))

        self.assertEqual(response.status_code, 302)
        proposta.refresh_from_db()
        self.organograma.refresh_from_db()
        solicitacao.refresh_from_db()
        self.assertEqual(self.organograma.status, 'HISTORICO')
        self.assertEqual(proposta.status, 'OFICIAL')
        self.assertEqual(solicitacao.status, 'APROVADO')
        self.assertIsNotNone(proposta.data_aprovacao_sistema)
        self.assertEqual(proposta.resolucao_estrutura, resolucao_nova)

    def test_final_consup_approval_for_competency_only_changes_requires_new_regimento_not_resolution(self):
        resolucao_original = ResolucaoEstruturaOrganizacional.objects.create(
            campus=self.campus,
            nome='Resolucao Original',
            numero='2/2026',
            data_publicacao=date(2026, 5, 6),
        )
        novo_regimento = RegimentoCampus.objects.create(
            campus=self.campus,
            nome='Regimento Novo',
            numero='Portaria 3/2026',
            data_publicacao=date(2026, 6, 10),
            vigente=True,
        )
        self.organograma.status = 'OFICIAL'
        self.organograma.resolucao_estrutura = resolucao_original
        self.organograma.save(update_fields=['status', 'resolucao_estrutura'])
        raiz_modelo = UnitModelo.objects.create(
            modelo=self.modelo,
            nome_unidade=self.unidade.nome_unidade,
            sigla_unidade=self.unidade.sigla_unidade,
            ordem=self.unidade.ordem,
        )
        self.unidade.origem_modelo = raiz_modelo
        self.unidade.save(update_fields=['origem_modelo'])
        CompetenciaUnidade.objects.create(
            unidade=self.unidade,
            regimento=self.regimento_vigente,
            artigo='1º',
            texto='Competencia original.',
            ordem=1,
        )
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            resolucao_estrutura=resolucao_original,
            regimento_referencia=novo_regimento,
            status='PROPOSTA',
        )
        unidade_proposta = Unit.objects.create(
            organograma=proposta,
            source_unit=self.unidade,
            origem_modelo=raiz_modelo,
            nome_unidade=self.unidade.nome_unidade,
            sigla_unidade=self.unidade.sigla_unidade,
            ordem=self.unidade.ordem,
        )
        CompetenciaUnidade.objects.create(
            unidade=unidade_proposta,
            regimento=novo_regimento,
            artigo='1º',
            texto='Competencia atualizada pelo novo regimento.',
            ordem=1,
        )
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=get_user_model().objects.create_user(username='solicitante-regimento', password='senha'),
            justificativa='Atualizacao de competencias por novo regimento.',
            status='ENVIADO_CONSUP',
        )
        admin = get_user_model().objects.create_user(username='admin-regimento', password='senha', is_superuser=True)
        client = Client()
        client.force_login(admin)

        response = client.post(reverse('solicitacao_approve', args=[solicitacao.id]))

        self.assertEqual(response.status_code, 302)
        proposta.refresh_from_db()
        self.organograma.refresh_from_db()
        solicitacao.refresh_from_db()
        self.assertEqual(self.organograma.status, 'HISTORICO')
        self.assertEqual(proposta.status, 'OFICIAL')
        self.assertEqual(solicitacao.status, 'APROVADO')
        self.assertEqual(proposta.resolucao_estrutura, resolucao_original)
        self.assertEqual(proposta.regimento_referencia, novo_regimento)

    def test_reject_requires_evaluator_justification(self):
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=get_user_model().objects.create_user(username='solicitante-rejeicao', password='senha'),
            justificativa='Proposta em analise.',
            status='EM_ANALISE',
        )
        admin = get_user_model().objects.create_user(username='admin-rejeicao', password='senha', is_superuser=True)
        client = Client()
        client.force_login(admin)

        response = client.post(reverse('solicitacao_reject', args=[solicitacao.id]), {'acao_rejeicao': 'rejeitar'})

        self.assertEqual(response.status_code, 302)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, 'EM_ANALISE')
        self.assertEqual(solicitacao.justificativa_avaliador, '')

    def test_reject_definitively_stores_evaluator_justification(self):
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=get_user_model().objects.create_user(username='solicitante-definitivo', password='senha'),
            justificativa='Proposta em analise.',
            status='ENVIADO_CONSUP',
        )
        admin = get_user_model().objects.create_user(username='admin-definitivo', password='senha', is_superuser=True)
        client = Client()
        client.force_login(admin)

        response = client.post(
            reverse('solicitacao_reject', args=[solicitacao.id]),
            {'acao_rejeicao': 'rejeitar', 'justificativa_avaliador': 'Nao atende aos criterios do CONSUP.'},
        )

        self.assertEqual(response.status_code, 302)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, 'REJEITADO')
        self.assertEqual(solicitacao.justificativa_avaliador, 'Nao atende aos criterios do CONSUP.')

    def test_return_for_correction_allows_resubmission(self):
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        solicitante = get_user_model().objects.create_user(username='solicitante-correcao', password='senha', is_staff=True)
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=solicitante,
            justificativa='Proposta em analise.',
            status='EM_ANALISE',
        )
        admin = get_user_model().objects.create_user(username='admin-correcao', password='senha', is_superuser=True)
        client = Client()
        client.force_login(admin)

        response = client.post(
            reverse('solicitacao_reject', args=[solicitacao.id]),
            {'acao_rejeicao': 'devolver_correcao', 'justificativa_avaliador': 'Corrigir a justificativa normativa.'},
        )

        self.assertEqual(response.status_code, 302)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, 'DEVOLVIDO_CORRECAO')
        self.assertEqual(solicitacao.justificativa_avaliador, 'Corrigir a justificativa normativa.')

        client.force_login(solicitante)
        response = client.post(reverse('solicitacao_resubmit', args=[solicitacao.id]))

        self.assertEqual(response.status_code, 302)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, 'EM_ANALISE')

    def test_requester_sees_evaluator_justification_on_detail(self):
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        solicitante = get_user_model().objects.create_user(username='solicitante-visualiza', password='senha', is_staff=True)
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=solicitante,
            justificativa='Solicito ajuste na estrutura.',
            justificativa_avaliador='Corrigir a justificativa normativa antes de reenviar.',
            status='DEVOLVIDO_CORRECAO',
        )
        client = Client()
        client.force_login(solicitante)

        response = client.get(reverse('solicitacao_detail', args=[solicitacao.id]))

        self.assertContains(response, 'Justificativa do Avaliador')
        self.assertContains(response, 'Corrigir a justificativa normativa antes de reenviar.')

    def test_reject_actions_use_popup_instead_of_inline_textarea(self):
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        solicitante = get_user_model().objects.create_user(username='solicitante-popup', password='senha', is_staff=True)
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=solicitante,
            justificativa='Proposta em analise.',
            status='EM_ANALISE',
        )
        admin = get_user_model().objects.create_user(username='admin-popup', password='senha', is_superuser=True)
        client = Client()
        client.force_login(admin)

        list_response = client.get(reverse('solicitacao_list'))
        detail_response = client.get(reverse('solicitacao_detail', args=[solicitacao.id]))

        for response in (list_response, detail_response):
            self.assertNotContains(response, '<textarea name="justificativa_avaliador"', html=False)
            self.assertContains(response, 'data-rejection-form')
            self.assertContains(response, 'data-rejection-action="devolver_correcao"')
            self.assertContains(response, 'data-rejection-action="rejeitar"')
            self.assertContains(response, 'openEvaluatorJustificationPopup')

    def test_definitive_rejection_cannot_be_resubmitted(self):
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        solicitante = get_user_model().objects.create_user(username='solicitante-final', password='senha', is_staff=True)
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=solicitante,
            justificativa='Proposta rejeitada.',
            status='REJEITADO',
        )
        client = Client()
        client.force_login(solicitante)

        response = client.post(reverse('solicitacao_resubmit', args=[solicitacao.id]))

        self.assertEqual(response.status_code, 302)
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, 'REJEITADO')

    def test_deleting_request_queryset_also_deletes_linked_proposal(self):
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='PROPOSTA',
        )
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=get_user_model().objects.create_user(username='solicitante-delete', password='senha'),
            justificativa='Proposta para excluir.',
            status='EM_ANALISE',
        )

        SolicitacaoAlteracao.objects.filter(pk=solicitacao.pk).delete()

        self.assertFalse(SolicitacaoAlteracao.objects.filter(pk=solicitacao.pk).exists())
        self.assertFalse(Organograma.objects.filter(pk=proposta.pk).exists())

    def test_deleting_request_queryset_does_not_delete_approved_official_organogram(self):
        proposta = Organograma.objects.create(
            campus=self.campus,
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
            status='OFICIAL',
        )
        solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.organograma,
            organograma_proposto=proposta,
            usuario=get_user_model().objects.create_user(username='solicitante-approved-delete', password='senha'),
            justificativa='Proposta aprovada.',
            status='APROVADO',
        )

        SolicitacaoAlteracao.objects.filter(pk=solicitacao.pk).delete()

        self.assertFalse(SolicitacaoAlteracao.objects.filter(pk=solicitacao.pk).exists())
        self.assertTrue(Organograma.objects.filter(pk=proposta.pk, status='OFICIAL').exists())

    def test_solicitacao_detail_shows_competencias_added_to_proposal(self):
        user = get_user_model().objects.create_user(username='campus-staff', password='senha', is_staff=True)
        client = Client()
        client.force_login(user)
        self.organograma.status = 'OFICIAL'
        self.organograma.save(update_fields=['status'])

        response = client.post(
            reverse('solicitacao_create', args=[self.organograma.id]),
            {'justificativa': 'Atualizacao de competencias.'},
        )

        self.assertEqual(response.status_code, 302)
        solicitacao = SolicitacaoAlteracao.objects.get()
        unidade_proposta = solicitacao.organograma_proposto.unidades.get(source_unit=self.unidade)
        CompetenciaUnidade.objects.create(
            unidade=unidade_proposta,
            regimento=self.regimento_vigente,
            artigo='12',
            texto='Coordenar as competencias academicas.',
        )

        response = client.get(reverse('solicitacao_detail', args=[solicitacao.id]))

        self.assertContains(response, 'Setores Modificados')
        self.assertContains(response, 'Compet')
        self.assertContains(response, 'Art. 12: Coordenar as competencias academicas.')


class OrganogramaExportTests(TestCase):
    def setUp(self):
        self.campus = Campus.objects.create(nome='Campus Exportacao', sigla='EXP')
        self.organograma = Organograma.objects.create(campus=self.campus, status='OFICIAL')
        self.unidade = Unit.objects.create(
            organograma=self.organograma,
            nome_unidade='Diretoria de Exportacao',
            sigla_unidade='EXP-DE',
            ordem=1,
        )

    def assert_export_controls(self, response):
        self.assertContains(response, 'data-org-export-format="svg"')
        self.assertContains(response, 'data-org-export-format="png"')
        self.assertContains(response, 'data-org-export-format="pdf"')
        self.assertContains(response, 'window.OrgChartExporter')
        self.assertContains(response, 'html2canvas')
        self.assertContains(response, 'org-chart-export-area')
        self.assertContains(response, 'org-export-competencias-status')
        self.assertContains(response, '.org-export-competencias-status { display: none !important; }')
        self.assertContains(response, 'removeExportOnlyElements')

    def test_detail_renders_complete_export_controls(self):
        response = self.client.get(reverse('organograma_detail', args=[self.organograma.id]))

        self.assertEqual(response.status_code, 200)
        self.assert_export_controls(response)

    def test_builder_renders_complete_export_controls(self):
        user = get_user_model().objects.create_user(username='export-staff', password='senha', is_staff=True)
        self.client.force_login(user)
        self.organograma.status = 'RASCUNHO'
        self.organograma.save(update_fields=['status'])

        response = self.client.get(reverse('organograma_build', args=[self.organograma.id]))

        self.assertEqual(response.status_code, 200)
        self.assert_export_controls(response)
        self.assertContains(response, '.chart-control-group {\n        position: absolute;\n        bottom: 20px;')


class ListFiltersTests(TestCase):
    def setUp(self):
        self.dimensionamento = Dimensionamento.objects.create(nome='Campus 40/26', chave='40_26')
        self.modelo = ModeloReferencial.objects.create(nome='Modelo 40/26', dimensionamento=self.dimensionamento, ativo=True)
        self.campus_a = Campus.objects.create(
            nome='Campus Alfa',
            sigla='ALF',
            dimensionamento_fk=self.dimensionamento,
            modelo_referencial_padrao=self.modelo,
        )
        self.campus_b = Campus.objects.create(nome='Campus Beta', sigla='BET')
        self.resolucao_a = ResolucaoEstruturaOrganizacional.objects.create(
            campus=self.campus_a,
            nome='Resolucao Alfa',
            numero='1/2024',
            data_publicacao=date(2024, 1, 10),
        )
        self.resolucao_b = ResolucaoEstruturaOrganizacional.objects.create(
            campus=self.campus_a,
            nome='Resolucao Alfa Nova',
            numero='2/2025',
            data_publicacao=date(2025, 2, 20),
        )
        self.oficial = Organograma.objects.create(
            campus=self.campus_a,
            modelo_base=self.modelo,
            resolucao_estrutura=self.resolucao_b,
            status='OFICIAL',
        )
        self.rascunho = Organograma.objects.create(campus=self.campus_b, status='RASCUNHO')
        self.historico_v1 = Organograma.objects.create(
            campus=self.campus_a,
            resolucao_estrutura=self.resolucao_a,
            data_aprovacao_sistema=timezone.make_aware(datetime(2024, 1, 10, 9, 0)),
            status='HISTORICO',
        )
        self.historico_v2 = Organograma.objects.create(
            campus=self.campus_a,
            resolucao_estrutura=self.resolucao_b,
            data_aprovacao_sistema=timezone.make_aware(datetime(2025, 2, 20, 9, 0)),
            status='HISTORICO',
        )
        self.user_a = get_user_model().objects.create_user(username='user-a', password='senha')
        self.user_a.profile.campus = self.campus_a
        self.user_a.profile.save()
        self.user_b = get_user_model().objects.create_user(username='user-b', password='senha')

    def test_public_organograma_filters_do_not_expose_drafts(self):
        response = self.client.get(reverse('organograma_list'), {'status': 'rascunho', 'q': 'Beta'})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.rascunho, response.context['organogramas'])
        self.assertNotIn(self.rascunho, response.context['rascunhos'])

    def test_public_organograma_list_defaults_to_campus_order(self):
        beta_oficial = Organograma.objects.create(campus=self.campus_b, status='OFICIAL')

        response = self.client.get(reverse('organograma_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['organogramas']), [self.oficial, beta_oficial])
        self.assertContains(response, '<option value="campus" selected>Campus</option>', html=False)

    def test_logged_organograma_list_defaults_to_campus_order(self):
        beta_oficial = Organograma.objects.create(campus=self.campus_b, status='OFICIAL')
        self.client.force_login(self.user_a)

        response = self.client.get(reverse('organograma_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['organogramas']), [self.oficial, beta_oficial])
        self.assertContains(response, '<option value="campus" selected>Campus</option>', html=False)

    def test_organograma_detail_deduplicates_reciprocal_links(self):
        reitoria = Campus.objects.create(nome='Reitoria', sigla='IFMG')
        reitoria_org = Organograma.objects.create(campus=reitoria, status='OFICIAL')
        self.oficial.organogramas_vinculados.add(reitoria_org)
        reitoria_org.organogramas_vinculados.add(self.oficial)

        response = self.client.get(reverse('organograma_detail', args=[self.oficial.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'/organograma/{reitoria_org.pk}/?next=',
            count=1,
            html=False,
        )

    def test_logged_user_rascunho_scope_respects_profile_campus(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse('organograma_list'), {'status': 'rascunho'})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.rascunho, response.context['rascunhos'])

    def test_solicitacao_filters_preserve_user_isolation(self):
        other_original = Organograma.objects.create(campus=self.campus_b, status='OFICIAL')
        other_proposal = Organograma.objects.create(campus=self.campus_b, status='PROPOSTA')
        own_proposal = Organograma.objects.create(campus=self.campus_a, status='PROPOSTA')
        own = SolicitacaoAlteracao.objects.create(
            organograma_original=self.oficial,
            organograma_proposto=own_proposal,
            usuario=self.user_a,
            justificativa='Minha alteracao',
            status='EM_ANALISE',
        )
        other = SolicitacaoAlteracao.objects.create(
            organograma_original=other_original,
            organograma_proposto=other_proposal,
            usuario=self.user_b,
            justificativa='Outra alteracao',
            status='EM_ANALISE',
        )

        self.client.force_login(self.user_a)
        response = self.client.get(reverse('solicitacao_list'), {'q': 'alteracao'})

        self.assertEqual(response.status_code, 200)
        self.assertIn(own, response.context['solicitacoes'])
        self.assertNotIn(other, response.context['solicitacoes'])

    def test_current_official_card_shows_active_proposal_for_same_campus(self):
        admin = get_user_model().objects.create_user(username='admin', password='senha', is_superuser=True)
        proposta = Organograma.objects.create(campus=self.campus_a, status='PROPOSTA')
        SolicitacaoAlteracao.objects.create(
            organograma_original=self.oficial,
            organograma_proposto=proposta,
            usuario=admin,
            justificativa='Proposta ainda em analise.',
            status='EM_ANALISE',
        )
        novo_oficial = Organograma.objects.create(campus=self.campus_a, status='OFICIAL')
        self.oficial.refresh_from_db()
        self.client.force_login(admin)

        response = self.client.get(reverse('organograma_list'))

        self.assertEqual(self.oficial.status, 'HISTORICO')
        self.assertTrue(novo_oficial.tem_proposta_ativa)
        self.assertContains(response, 'Oficial (Com Proposta de Alteração)')

    def test_logged_official_card_shows_cargo_quota_balance(self):
        fg1 = CargoFuncao.objects.create(nome='Chefe', sigla='FG-01')
        ModeloReferencialCotaCargo.objects.create(
            modelo_referencial=self.modelo,
            cargo_funcao=fg1,
            quantidade=2,
        )
        Unit.objects.create(
            organograma=self.oficial,
            nome_unidade='Setor de Apoio',
            sigla_unidade='ALF-SA',
            cargo_funcao_ref=fg1,
            ordem=1,
        )
        self.client.force_login(self.user_a)

        response = self.client.get(reverse('organograma_list'))

        self.assertContains(response, 'FG-01: 1 / 2')
        self.assertContains(response, 'Cargo não alocado')

    def test_public_official_card_hides_cargo_quota_balance(self):
        cd2 = CargoFuncao.objects.create(nome='Diretor', sigla='CD-02')
        ModeloReferencialCotaCargo.objects.create(
            modelo_referencial=self.modelo,
            cargo_funcao=cd2,
            quantidade=1,
        )
        Unit.objects.create(
            organograma=self.oficial,
            nome_unidade='Diretoria',
            sigla_unidade='ALF-DIR',
            cargo_funcao_ref=cd2,
            ordem=1,
        )

        response = self.client.get(reverse('organograma_list'))

        self.assertNotContains(response, 'CD-02: 1 / 1')
        self.assertNotContains(response, 'Cargo não alocado')

    def test_logged_official_card_marks_cd_fg_without_registered_quota(self):
        cd2 = CargoFuncao.objects.create(nome='Diretor', sigla='CD-02')
        Unit.objects.create(
            organograma=self.oficial,
            nome_unidade='Diretoria sem cota',
            sigla_unidade='ALF-DSC',
            cargo_funcao_ref=cd2,
            ordem=1,
        )
        self.client.force_login(self.user_a)

        response = self.client.get(reverse('organograma_list'))

        self.assertNotContains(response, 'CD-02: 1 / 0')
        self.assertContains(response, 'CD-02: 1 / -')

    def test_historico_filters_version_after_full_campus_versioning(self):
        response = self.client.get(reverse('historico_list'), {'versao': 'v2'})

        self.assertEqual(response.status_code, 200)
        groups = response.context['campus_groups']
        orgs = list(groups[self.campus_a])
        self.assertEqual(orgs, [self.historico_v2])
        self.assertEqual(orgs[0].versao_calculada, 'v2')

    def test_historico_filters_by_system_approval_date(self):
        response = self.client.get(reverse('historico_list'), {'data_inicio': '2025-01-01'})

        self.assertEqual(response.status_code, 200)
        groups = response.context['campus_groups']
        orgs = list(groups[self.campus_a])
        self.assertEqual(orgs, [self.historico_v2])


class DiferenciacaoPerfisTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.campus = Campus.objects.create(nome='Campus de Teste', sigla='TST')
        
        # 1. Superadmin (is_superuser=True)
        self.superadmin = User.objects.create_user(
            username='superadmin-perfis',
            password='senha',
            is_superuser=True,
            is_staff=True
        )
        
        # 2. Admin Limitado (is_staff=True, is_superuser=False)
        self.admin_limitado = User.objects.create_user(
            username='admin-perfis',
            password='senha',
            is_staff=True,
            is_superuser=False
        )
        
        # 3. Usuário de Campus (is_staff=False, profile.campus = campus)
        self.campus_user = User.objects.create_user(
            username='user-perfis',
            password='senha',
            is_staff=False,
            is_superuser=False
        )
        self.campus_user.profile.campus = self.campus
        self.campus_user.profile.save()
        
        # Create an official organogram for base
        self.dimensionamento = Dimensionamento.objects.create(nome='Dimensionamento Teste', chave='40_26')
        self.modelo = ModeloReferencial.objects.create(nome='Modelo Teste', dimensionamento=self.dimensionamento, ativo=True)
        self.regimento_vigente = RegimentoCampus.objects.create(campus=self.campus, nome='Regimento Teste')
        self.oficial = Organograma.objects.create(
            campus=self.campus,
            status='OFICIAL',
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
        )

        # Create proposed organogram
        self.proposta = Organograma.objects.create(
            campus=self.campus,
            status='PROPOSTA',
            modelo_base=self.modelo,
            regimento_referencia=self.regimento_vigente,
        )

        # Create a solicitation in status RASCUNHO for campus_user
        self.solicitacao = SolicitacaoAlteracao.objects.create(
            organograma_original=self.oficial,
            organograma_proposto=self.proposta,
            usuario=self.campus_user,
            justificativa='Rascunho do campus.',
            status='RASCUNHO',
        )

    def test_campus_user_can_access_own_draft(self):
        client = Client()
        client.force_login(self.campus_user)
        
        # Can list
        response = client.get(reverse('solicitacao_list'))
        self.assertContains(response, 'Rascunho do campus.')
        
        # Can view details
        response = client.get(reverse('solicitacao_detail', args=[self.solicitacao.id]))
        self.assertEqual(response.status_code, 200)

    def test_superadmin_can_access_campus_draft(self):
        client = Client()
        client.force_login(self.superadmin)
        
        # Can list
        response = client.get(reverse('solicitacao_list'))
        self.assertContains(response, 'Rascunho do campus.')
        
        # Can view details
        response = client.get(reverse('solicitacao_detail', args=[self.solicitacao.id]))
        self.assertEqual(response.status_code, 200)

    def test_staff_can_open_modelo_referencial_builder(self):
        client = Client()
        client.force_login(self.superadmin)

        response = client.get(reverse('modelo_referencial_build', args=[self.modelo.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('modelo_referencial_list'))
        self.assertContains(response, 'const isModeloBuilder = true;')
        self.assertNotContains(response, 'name="atribuicoes"', html=False)
        self.assertContains(response, 'function layoutForChildren')
        self.assertContains(response, "return isTopLayoutSource ? 'H' : 'V';")

    def test_limited_admin_cannot_access_campus_draft(self):
        client = Client()
        client.force_login(self.admin_limitado)
        
        # Cannot list
        response = client.get(reverse('solicitacao_list'))
        self.assertNotContains(response, 'Rascunho do campus.')
        
        # Cannot view details (PermissionDenied)
        response = client.get(reverse('solicitacao_detail', args=[self.solicitacao.id]))
        self.assertEqual(response.status_code, 403)
        
        # Cannot view organogram proposed details
        response = client.get(reverse('organograma_detail', args=[self.proposta.id]))
        self.assertEqual(response.status_code, 403)
        
        # Cannot edit metadata
        response = client.post(reverse('organograma_edit', args=[self.proposta.id]))
        self.assertEqual(response.status_code, 403)
        
        # Cannot delete
        response = client.post(reverse('organograma_delete', args=[self.proposta.id]))
        self.assertEqual(response.status_code, 403)

        # Cannot build
        response = client.get(reverse('organograma_build', args=[self.proposta.id]))
        self.assertEqual(response.status_code, 403)

    def test_limited_admin_can_access_submitted_solicitation(self):
        # Change status to EM_ANALISE
        self.solicitacao.status = 'EM_ANALISE'
        self.solicitacao.save()
        
        client = Client()
        client.force_login(self.admin_limitado)
        
        # Can list
        response = client.get(reverse('solicitacao_list'))
        self.assertContains(response, 'Rascunho do campus.')
        
        # Can view details
        response = client.get(reverse('solicitacao_detail', args=[self.solicitacao.id]))
        self.assertEqual(response.status_code, 200)
        
        # Can view organogram proposed details
        response = client.get(reverse('organograma_detail', args=[self.proposta.id]))
        self.assertEqual(response.status_code, 200)

    def test_custom_user_form_superuser_auto_staff(self):
        from core.forms import CustomUserForm
        form_data = {
            'username': 'new-superadmin',
            'email': 'super@test.com',
            'is_superuser': True,
            'is_staff': False,  # intentionally set false to test auto-promotion
            'password': 'some-strong-password',
            'campus': '',
        }
        form = CustomUserForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        
        # Reload to bypass Django relation caching
        user = get_user_model().objects.get(pk=user.pk)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertIsNone(user.profile.campus)

    def test_custom_user_form_campus_assignment(self):
        from core.forms import CustomUserForm
        form_data = {
            'username': 'new-campus-user',
            'email': 'campus@test.com',
            'is_superuser': False,
            'is_staff': False,
            'password': 'some-strong-password',
            'campus': self.campus.pk,
        }
        form = CustomUserForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        
        # Reload to bypass Django relation caching
        user = get_user_model().objects.get(pk=user.pk)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertEqual(user.profile.campus, self.campus)

    def test_draft_deletion_by_owner(self):
        client = Client()
        client.force_login(self.campus_user)
        
        # Owner should be able to delete the draft
        response = client.post(reverse('solicitacao_delete', args=[self.solicitacao.id]))
        self.assertEqual(response.status_code, 302)
        
        # Verify both solicitation and proposed organogram are deleted
        self.assertFalse(SolicitacaoAlteracao.objects.filter(pk=self.solicitacao.id).exists())
        self.assertFalse(Organograma.objects.filter(pk=self.proposta.id).exists())

    def test_draft_deletion_by_superadmin(self):
        client = Client()
        client.force_login(self.superadmin)
        
        # Superadmin should be able to delete the draft
        response = client.post(reverse('solicitacao_delete', args=[self.solicitacao.id]))
        self.assertEqual(response.status_code, 302)
        
        # Verify both are deleted
        self.assertFalse(SolicitacaoAlteracao.objects.filter(pk=self.solicitacao.id).exists())
        self.assertFalse(Organograma.objects.filter(pk=self.proposta.id).exists())

    def test_draft_deletion_denied_to_limited_admin(self):
        client = Client()
        client.force_login(self.admin_limitado)
        
        # Limited admin should not be able to delete campus user's draft
        response = client.post(reverse('solicitacao_delete', args=[self.solicitacao.id]))
        self.assertEqual(response.status_code, 403)
        
        # Verify they are still in DB
        self.assertTrue(SolicitacaoAlteracao.objects.filter(pk=self.solicitacao.id).exists())
        self.assertTrue(Organograma.objects.filter(pk=self.proposta.id).exists())

    def test_draft_deletion_denied_for_non_drafts(self):
        # Change status to EM_ANALISE
        self.solicitacao.status = 'EM_ANALISE'
        self.solicitacao.save()
        
        client = Client()
        client.force_login(self.campus_user)
        
        # Owner tries to delete active solicitation
        response = client.post(reverse('solicitacao_delete', args=[self.solicitacao.id]))
        self.assertEqual(response.status_code, 302) # redirects with warning message
        
        # Verify solicitation still exists
        self.assertTrue(SolicitacaoAlteracao.objects.filter(pk=self.solicitacao.id).exists())
