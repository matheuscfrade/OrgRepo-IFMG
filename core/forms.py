import re
import unicodedata

from django import forms
from django.db import models
from django.contrib.auth.models import User
from django.forms import inlineformset_factory
from django.forms.models import BaseInlineFormSet
from django.forms.forms import NON_FIELD_ERRORS
from .models import (
    Organograma,
    Unit,
    CargoFuncao,
    TipoUnidade,
    Profile,
    Campus,
    CampusCotaCargo,
    ModeloReferencial,
    ModeloReferencialCotaCargo,
    UnitModelo,
    RegrasAlteracaoModelo,
    ExcecaoRegraAlteracaoCampus,
    RegimentoCampus,
    ResolucaoEstruturaOrganizacional,
    CompetenciaUnidade,
)


def _normalize_cadastro_key(value):
    value = unicodedata.normalize('NFKD', value or '')
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return re.sub(r'\s+', ' ', value).strip().casefold()


REGRAS_MODELO_HELP_TEXTS = {
    'limite_total_alteracoes': "Campo legado mantido apenas para compatibilidade. A valida&ccedil;&atilde;o ativa segue exclusivamente a Resolu&ccedil;&atilde;o CONSUP n&ordm; 44/2025.",
    'exige_vinculo_com_modelo': "Campo legado mantido apenas para compatibilidade. Caixas fora do modelo aparecem no relat&oacute;rio, mas n&atilde;o substituem as regras expressas da Resolu&ccedil;&atilde;o CONSUP n&ordm; 44/2025.",
    'exigir_adequacao_quando_modelo_mudar': "Quando ativo, um organograma passa a ficar pendente de adequa&ccedil;&atilde;o sempre que este modelo referencial for atualizado. Isso obriga a revis&atilde;o da estrutura antes de seguir usando a vers&atilde;o anterior.",
    'permite_renomeacao': "Define se o nome de uma unidade herdada do modelo pode ser alterado no organograma do campus.",
    'limite_renomeacao': "Quantidade m&aacute;xima de unidades do modelo que podem ter o nome alterado. Cada renomea&ccedil;&atilde;o contabiliza neste limite e tamb&eacute;m no limite total.",
    'permite_mudanca_vinculo': "Define se uma unidade pode mudar de subordina&ccedil;&atilde;o em rela&ccedil;&atilde;o ao modelo, ou seja, trocar de unidade-m&atilde;e.",
    'limite_mudanca_vinculo': "Quantidade m&aacute;xima de mudan&ccedil;as de subordina&ccedil;&atilde;o permitidas. Cada mudan&ccedil;a de v&iacute;nculo tamb&eacute;m entra na contagem total de altera&ccedil;&otilde;es.",
    'permite_alteracao_cargo': "Define se o cargo/fun&ccedil;&atilde;o previsto no modelo pode ser substitu&iacute;do por outro no organograma do campus.",
    'limite_alteracao_cargo': "Quantidade m&aacute;xima de unidades cujo cargo/fun&ccedil;&atilde;o pode ser alterado em rela&ccedil;&atilde;o ao modelo.",
    'permite_alteracao_tipo_unidade': "Define se a classifica&ccedil;&atilde;o da unidade pode mudar, como trocar um setor por uma se&ccedil;&atilde;o, quando a regra de resolu&ccedil;&atilde;o permitir.",
    'limite_alteracao_tipo_unidade': "Quantidade m&aacute;xima de unidades que podem ter o tipo alterado em rela&ccedil;&atilde;o ao modelo.",
    'permite_alteracao_sigla': "Define se a sigla da unidade ou do cargo pode divergir da sigla prevista no modelo referencial.",
    'limite_alteracao_sigla': "Quantidade m&aacute;xima de altera&ccedil;&otilde;es de sigla permitidas em rela&ccedil;&atilde;o ao modelo.",
    'permite_exclusao_unidade_modelo': "Define se uma unidade existente no modelo pode deixar de existir no organograma do campus.",
    'limite_exclusao_unidade_modelo': "Quantidade m&aacute;xima de unidades do modelo que podem ser removidas da estrutura do campus.",
    'permite_inclusao_unidade_nova': "Define se o campus pode criar unidades que n&atilde;o existem no modelo referencial.",
    'limite_inclusao_unidade_nova': "Quantidade m&aacute;xima de unidades novas que podem ser criadas fora do modelo.",
    'limite_flexibilizacao_fg': "Limite inteiro da cota de 25% prevista no Art. 3&ordm; da Resolu&ccedil;&atilde;o CONSUP n&ordm; 44/2025 para altera&ccedil;&otilde;es de nomenclatura e/ou vincula&ccedil;&atilde;o de unidades com FG. Valores normativos: Polo=1, 40/26=3, 70/45=3, 90/70 Agr&iacute;cola=3, 150=6 e 150 Agr&iacute;cola=6.",
    'permite_regra_transicao': "Aplica somente ao dimensionamento 40/26. Quando marcado, usa a regra de transi&ccedil;&atilde;o do Art. 3&ordm;, &sect;4&ordm;, elevando temporariamente a cota para at&eacute; 5 altera&ccedil;&otilde;es de nomenclatura e/ou vincula&ccedil;&atilde;o.",
    'prefixos_cargos_bloqueados': "Prefixos de cargos de dire&ccedil;&atilde;o sem flexibiliza&ccedil;&atilde;o, conforme Art. 3&ordm;, &sect;2&ordm;. Use <code>CD</code>.",
    'prefixos_cargos_flexibilizaveis': "Prefixos de fun&ccedil;&otilde;es gratificadas que entram na cota de 25%, conforme Art. 3&ordm;. Use <code>FG</code> para abranger FG-01, FG-02 e FG-03.",
    'departamentos_intocaveis': "Unidades previstas no Art. 3&ordm;, &sect;3&ordm;, flex&iacute;veis apenas quanto &agrave; vincula&ccedil;&atilde;o: Gest&atilde;o de Pessoas, Tecnologia da Informa&ccedil;&atilde;o e Assuntos Institucionais.",
    'verificar_sufixo_anexo': "Exige a preserva&ccedil;&atilde;o dos prefixos de nomenclatura do Anexo VII da Resolu&ccedil;&atilde;o CONSUP n&ordm; 44/2025, como Diretoria, Coordenadoria, Departamento, Setor, Se&ccedil;&atilde;o e N&uacute;cleo.",
}


def _apply_regras_help_texts(form, *, is_exception=False):
    for field_name, help_text in REGRAS_MODELO_HELP_TEXTS.items():
        if field_name in form.fields:
            if is_exception:
                form.fields[field_name].help_text = f"{help_text} Deixe em branco para herdar a regra base do modelo."
            else:
                form.fields[field_name].help_text = help_text

    if is_exception and 'campus' in form.fields:
        form.fields['campus'].help_text = (
            "Selecione o campus que receber&aacute; uma exce&ccedil;&atilde;o. Apenas os campos preenchidos abaixo sobrescrevem a regra base; os demais continuam herdando a configura&ccedil;&atilde;o do modelo."
        )

class CampusSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value and value != '':
            try:
                # Se for um valor simples (string/int) ou um objeto com .value
                pk_val = value.value if hasattr(value, 'value') else value
                if pk_val:
                    campus = Campus.objects.get(pk=pk_val)
                    option['attrs']['data-dimensionamento'] = campus.dimensionamento or ""
            except (Campus.DoesNotExist, TypeError, ValueError):
                pass
        return option

class ModeloReferencialSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value and value != '':
            try:
                pk_val = value.value if hasattr(value, 'value') else value
                if pk_val:
                    modelo = ModeloReferencial.objects.get(pk=pk_val)
                    option['attrs']['data-dimensionamento'] = modelo.dimensionamento or ""
            except (ModeloReferencial.DoesNotExist, TypeError, ValueError):
                pass
        return option

class OrganogramaForm(forms.ModelForm):
    utilizar_modelo = forms.BooleanField(
        initial=True,
        required=False,
        label="Utilizar estrutura do Modelo Referencial da Resolução",
        help_text="Se marcado, o sistema criará automaticamente as unidades e cargos padrão para este campus.",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_utilizar_modelo'})
    )

    modelo_referencial = forms.ModelChoiceField(
        queryset=ModeloReferencial.objects.filter(ativo=True),
        required=False,
        label="Modelo Referencial Identificado",
        widget=ModeloReferencialSelect(attrs={'class': 'form-control', 'id': 'id_modelo_referencial'}),
        help_text="Este modelo foi identificado com base no dimensionamento do campus selecionado."
    )

    class Meta:
        model = Organograma
        fields = [
            'campus', 
            'utilizar_modelo',
            'modelo_referencial',
            'resolucao_estrutura',
            'regimento_referencia',
            'regimento_geral_referencia',
            'status', 'organogramas_vinculados'
        ]
        labels = {
            'resolucao_estrutura': 'Resolução da Estrutura Organizacional',
            'regimento_referencia': 'Regimento de Referência',
            'regimento_geral_referencia': 'Regimento Geral de Referência',
        }
        widgets = {
            'campus': CampusSelect(attrs={'class': 'form-control', 'id': 'id_campus'}),
            'resolucao_estrutura': forms.Select(attrs={'class': 'form-control', 'id': 'id_resolucao_estrutura'}),
            'regimento_referencia': forms.Select(attrs={'class': 'form-control', 'id': 'id_regimento_referencia'}),
            'regimento_geral_referencia': forms.Select(attrs={'class': 'form-control', 'id': 'id_regimento_geral_referencia'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'organogramas_vinculados': forms.CheckboxSelectMultiple()
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['resolucao_estrutura'].queryset = ResolucaoEstruturaOrganizacional.objects.select_related('campus').order_by('campus__nome', '-data_publicacao', '-id')
        self.fields['resolucao_estrutura'].empty_label = "Selecione a resolução que aprovou esta versão da estrutura..."
        self.fields['regimento_referencia'].queryset = RegimentoCampus.objects.select_related('campus').filter(tipo='INTERNO').order_by('campus__nome', '-vigente', '-data_publicacao', '-id')
        self.fields['regimento_referencia'].empty_label = "Selecione o regimento cadastrado para este organograma..."
        self.fields['regimento_geral_referencia'].queryset = RegimentoCampus.objects.select_related('campus').filter(tipo='GERAL').order_by('campus__nome', '-vigente', '-data_publicacao', '-id')
        self.fields['regimento_geral_referencia'].empty_label = "Selecione o Regimento Geral usado pelas competências da Reitoria..."
        if 'organogramas_vinculados' in self.fields:
            self.fields['organogramas_vinculados'].queryset = Organograma.objects.filter(status='OFICIAL')
        if self.instance and self.instance.pk:
            self.fields['utilizar_modelo'].required = False
            self.fields['utilizar_modelo'].initial = False
            self.fields['modelo_referencial'].initial = self.instance.modelo_referencial_efetivo
            if self.instance.unidades.exists():
                self.fields['campus'].disabled = True
                self.fields['modelo_referencial'].disabled = True
                self.fields['modelo_referencial'].help_text = "O modelo de referência está travado porque o organograma já possui estrutura construída."
            if self.instance.status == 'PROPOSTA':
                self.fields['status'].disabled = True
                self.fields['status'].help_text = "O status da proposta é controlado pelo fluxo de solicitação."

    def clean(self):
        cleaned_data = super().clean()
        campus = cleaned_data.get('campus')
        modelo = cleaned_data.get('modelo_referencial')
        resolucao = cleaned_data.get('resolucao_estrutura')
        regimento = cleaned_data.get('regimento_referencia')
        regimento_geral = cleaned_data.get('regimento_geral_referencia')
        if not campus:
            return cleaned_data

        if campus.dispensa_modelo_referencial:
            cleaned_data['modelo_referencial'] = None
            modelo = None
        else:
            if not modelo:
                modelo = campus.modelo_referencial_padrao or ModeloReferencial.objects.filter(
                    dimensionamento__chave=campus.dimensionamento_chave,
                    ativo=True,
                ).order_by('id').first()
                cleaned_data['modelo_referencial'] = modelo

            if not modelo:
                self.add_error('modelo_referencial', "Selecione um Modelo Referencial compatível com o campus.")
                return cleaned_data

        if modelo and campus.dimensionamento_chave and modelo.dimensionamento.chave != campus.dimensionamento_chave:
            self.add_error('modelo_referencial', "O Modelo Referencial selecionado não é compatível com o dimensionamento do campus.")

        if modelo and campus.modelo_referencial_padrao and modelo != campus.modelo_referencial_padrao:
            self.add_error('modelo_referencial', f"O campus já possui o modelo referencial padrão '{campus.modelo_referencial_padrao.nome}'.")

        if not resolucao and cleaned_data.get('status') != 'PROPOSTA':
            self.add_error('resolucao_estrutura', "Cadastre e selecione a resolução da estrutura organizacional para esta versão do organograma.")
        elif resolucao and resolucao.campus_id != campus.id:
            self.add_error('resolucao_estrutura', "A resolução selecionada pertence a outro campus.")

        if not regimento:
            regimento = campus.regimentos.filter(tipo='INTERNO', vigente=True).order_by('-data_publicacao', '-id').first()
            if regimento:
                cleaned_data['regimento_referencia'] = regimento
            else:
                self.add_error('regimento_referencia', "Cadastre e selecione um regimento de referência para este campus.")
        elif regimento.campus_id != campus.id:
            self.add_error('regimento_referencia', "O regimento selecionado pertence a outro campus.")
        elif regimento.tipo != 'INTERNO':
            self.add_error('regimento_referencia', "Selecione um Regimento Interno para este campo.")

        if campus.sigla == 'IFMG':
            if not regimento_geral:
                regimento_geral = campus.regimentos.filter(tipo='GERAL', vigente=True).order_by('-data_publicacao', '-id').first()
                if regimento_geral:
                    cleaned_data['regimento_geral_referencia'] = regimento_geral
                else:
                    self.add_error('regimento_geral_referencia', "Cadastre e selecione o Regimento Geral de referência para a Reitoria.")
            elif regimento_geral.campus_id != campus.id:
                self.add_error('regimento_geral_referencia', "O Regimento Geral selecionado pertence a outro campus.")
            elif regimento_geral.tipo != 'GERAL':
                self.add_error('regimento_geral_referencia', "Selecione um Regimento Geral para este campo.")
        elif regimento_geral:
            self.add_error('regimento_geral_referencia', "Regimento Geral de referência é usado apenas para a Reitoria.")

        return cleaned_data


class RegimentoCampusForm(forms.ModelForm):
    def is_valid(self):
        is_valid = super().is_valid()
        if is_valid or not self.cleaned_data.get('vigente'):
            return is_valid

        non_field_errors = self.errors.as_data().get(NON_FIELD_ERRORS, [])
        remaining_errors = []
        for error in non_field_errors:
            if 'unique_regimento_vigente_por_campus_tipo' not in str(error.message):
                remaining_errors.append(error)
        if len(remaining_errors) == len(non_field_errors):
            return False

        if remaining_errors:
            self._errors[NON_FIELD_ERRORS] = self.error_class(remaining_errors)
        else:
            self._errors.pop(NON_FIELD_ERRORS, None)
        return not self.errors

    class Meta:
        model = RegimentoCampus
        fields = ['campus', 'tipo', 'nome', 'numero', 'data_publicacao', 'arquivo', 'link', 'vigente', 'observacoes']
        widgets = {
            'campus': forms.Select(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-control'}),
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Regimento Interno do Campus Arcos'}),
            'numero': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Resolução nº 12/2026'}),
            'data_publicacao': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'arquivo': forms.ClearableFileInput(attrs={'class': 'form-control-file'}),
            'link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'vigente': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'observacoes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class ResolucaoEstruturaOrganizacionalForm(forms.ModelForm):
    class Meta:
        model = ResolucaoEstruturaOrganizacional
        fields = ['campus', 'nome', 'numero', 'data_publicacao', 'arquivo', 'link', 'observacoes']
        widgets = {
            'campus': forms.Select(attrs={'class': 'form-control'}),
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Resolução nº 65/2025'}),
            'numero': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Resolução nº 65/2025'}),
            'data_publicacao': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'arquivo': forms.ClearableFileInput(attrs={'class': 'form-control-file'}),
            'link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'observacoes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class CompetenciaUnidadeForm(forms.ModelForm):
    class Meta:
        model = CompetenciaUnidade
        fields = ['artigo', 'inciso', 'alinea', 'paragrafo', 'texto']
        widgets = {
            'artigo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 12'}),
            'paragrafo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 1º'}),
            'inciso': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: II'}),
            'alinea': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: a'}),
            'texto': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Descreva a competência da unidade...'}),
        }

class CampusForm(forms.ModelForm):
    class Meta:
        model = Campus
        fields = ['nome', 'sigla', 'dimensionamento', 'modelo_referencial_padrao']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome do Campus'}),
            'sigla': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: RE, ARC, BAM'}),
            'dimensionamento': forms.Select(attrs={'class': 'form-control'}),
            'modelo_referencial_padrao': forms.Select(attrs={'class': 'form-control'}),
        }

class TipoUnidadeSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            from .models import TipoUnidade
            try:
                pk_val = value.value if hasattr(value, 'value') else value
                tipo = TipoUnidade.objects.get(pk=pk_val)
                if tipo.cargo_padrao:
                    option['attrs']['data-cargo'] = tipo.cargo_padrao.nome
                    option['attrs']['data-sigla'] = tipo.cargo_padrao.sigla
                    option['attrs']['data-cargo-id'] = tipo.cargo_padrao.id
                if tipo.selecao_cargo_livre or tipo.is_generico_pendente:
                    option['attrs']['data-cargo-livre'] = 'true'
                    from .models import CargoFuncao
                    fg_ids = list(
                        CargoFuncao.objects.filter(sigla__in=['FG-01', 'FG-02'])
                        .values_list('id', flat=True)
                    )
                    option['attrs']['data-cargo-ids'] = ','.join(str(i) for i in fg_ids)
            except (TipoUnidade.DoesNotExist, TypeError, ValueError):
                pass
        return option


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ['unidade_pai', 'tipo_unidade', 'cargo_funcao_ref', 'cargo_funcao', 'sigla_cargo', 'nome_unidade', 'sigla_unidade', 'ligacao_indireta', 'layout_filhos']
        widgets = {
            'unidade_pai': forms.Select(attrs={'class': 'form-control'}),
            'tipo_unidade': TipoUnidadeSelect(attrs={'class': 'form-control'}),
            'cargo_funcao_ref': forms.Select(attrs={'class': 'form-control'}),
            'cargo_funcao': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Auditor(a) Interno'}),
            'sigla_cargo': forms.Select(attrs={'class': 'form-control'}),
            'nome_unidade': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Pró-Reitoria de Ensino'}),
            'sigla_unidade': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: DE'}),
            'ligacao_indireta': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'layout_filhos': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        organograma_id = kwargs.pop('organograma_id', None)
        super(UnitForm, self).__init__(*args, **kwargs)
        
        # Ajusta Querysets e labels vazias
        if self.fields.get('tipo_unidade'):
             self.fields['tipo_unidade'].empty_label = "Selecione o Tipo de Departamento..."
        if self.fields.get('cargo_funcao_ref'):
             self.fields['cargo_funcao_ref'].empty_label = "(Selecionar tipo de departamento)"
             
        # Transformar sigla_cargo em Dropdown dinÃ¢mico
        opcoes_sigla = CargoFuncao.objects.values_list('sigla', 'sigla').distinct().order_by('sigla')
        self.fields['sigla_cargo'] = forms.ChoiceField(
            choices=[("", "Selecione...")] + list(opcoes_sigla),
            required=False,
            widget=forms.Select(attrs={'class': 'form-control'})
        )

        if self.fields.get('organograma_vinculado'):
            self.fields['organograma_vinculado'].queryset = Organograma.objects.filter(status='OFICIAL')
            self.fields['organograma_vinculado'].empty_label = "Nenhum (Organograma Isolado)"

        if organograma_id:
            org = Organograma.objects.get(pk=organograma_id)
            self.sigla_prefix = org.campus.get_sigla_prefix
            self.fields['unidade_pai'].queryset = Unit.objects.filter(organograma_id=organograma_id)
            self.fields['unidade_pai'].empty_label = "Nenhuma (Topo da Hierarquia / Raiz)"
            
            # Filtro de Tipos de Unidade e Cargos baseado no dimensionamento
            dim = org.campus.dimensionamento_fk
            if dim:
                tipo_queryset = TipoUnidade.objects.filter(
                    dimensionamentos_permitidos=dim,
                    apenas_modelo_referencial=False
                )
                self.fields['cargo_funcao_ref'].queryset = CargoFuncao.objects.filter(dimensionamentos_permitidos=dim)
            elif org.campus.dimensionamento != 'REITORIA':
                tipo_queryset = TipoUnidade.objects.filter(
                    apenas_modelo_referencial=False
                ).exclude(nome__icontains='Pró-Reitoria').exclude(nome__iexact='Reitoria')
                self.fields['cargo_funcao_ref'].queryset = CargoFuncao.objects.exclude(nome__icontains='Reitor').exclude(nome__icontains='Pró-Reitor')
            else:
                tipo_queryset = TipoUnidade.objects.all()

            if self.instance and self.instance.pk and self.instance.tipo_unidade_id:
                tipo_queryset = tipo_queryset | TipoUnidade.objects.filter(pk=self.instance.tipo_unidade_id)
            self.fields['tipo_unidade'].queryset = tipo_queryset.distinct().order_by('nome')

            origem_modelo = self.instance.origem_modelo if self.instance and self.instance.pk else None
            if origem_modelo and origem_modelo.has_flexible_resolution:
                self.fields['cargo_funcao_ref'].widget.attrs['data-model-flex'] = 'true'
                self.fields['cargo_funcao_ref'].widget.attrs['data-allowed-cargo-ids'] = ','.join(
                    str(i) for i in origem_modelo.allowed_cargo_ids
                )
        else:
            self.sigla_prefix = ""

    def clean_sigla_unidade(self):
        sigla = self.cleaned_data.get('sigla_unidade')
        if not sigla:
            return sigla
            
        if hasattr(self, 'sigla_prefix') and self.sigla_prefix:
            prefix = self.sigla_prefix
            if not sigla.startswith(f"{prefix}-"):
                # Se o usuário digitou apenas o sufixo, adiciona o prefixo
                # Se digitou algo totalmente diferente, força o prefixo
                if '-' in sigla and sigla.split('-')[0] != prefix:
                    # Caso tenha digitado outro prefixo por engano
                    sufixo = sigla.split('-', 1)[1]
                    sigla = f"{prefix}-{sufixo}"
                else:
                    sigla = f"{prefix}-{sigla}"
        return sigla.upper()

    def clean(self):
        cleaned_data = super().clean()
        nome = cleaned_data.get('nome_unidade')
        tipo = cleaned_data.get('tipo_unidade')
        
        if not nome or not tipo:
            return cleaned_data

        nome_upper = nome.upper()
        
        # 1. Bloqueio de "Setor ou Seção" no nome (case-insensitive)
        if "SETOR OU SEÇÃO" in nome_upper or "SETOR OU SECAO" in nome_upper:
            self.add_error('nome_unidade', "O nome da unidade não pode conter 'Setor ou Seção'. Defina se a unidade é um Setor ou uma Seção.")
            
        # 2. Bloqueio de tipos marcados como apenas para modelo referencial
        if tipo.apenas_modelo_referencial:
            self.add_error('tipo_unidade', f"O tipo '{tipo.nome}' é permitido apenas em Modelos Referenciais. Altere para um tipo concreto (Setor ou Seção).")

        origem_modelo = self.instance.origem_modelo if self.instance and self.instance.pk else None
        cargo_ref = cleaned_data.get('cargo_funcao_ref')
        if origem_modelo and origem_modelo.has_flexible_resolution:
            tipo_ids = set(origem_modelo.allowed_tipo_ids)
            cargo_ids = set(origem_modelo.allowed_cargo_ids)
            if tipo and tipo_ids and tipo.id not in tipo_ids:
                self.add_error('tipo_unidade', "Selecione um tipo permitido pela regra de resolução desta unidade do modelo.")
            if cargo_ref and cargo_ids and cargo_ref.id not in cargo_ids:
                self.add_error('cargo_funcao_ref', "Selecione um cargo permitido pela regra de resolução desta unidade do modelo.")
            if tipo and cargo_ref and tipo.cargo_padrao_id and not tipo.selecao_cargo_livre and cargo_ref.id != tipo.cargo_padrao_id:
                self.add_error('cargo_funcao_ref', f"Para o tipo '{tipo.nome}', o cargo deve ser '{tipo.cargo_padrao.sigla}'.")
            
        # 3. Validação Cruzada: Nome vs Tipo (Evitar selecionar Setor e escrever Seção)
        tipo_nome = tipo.nome.upper()
        if "SETOR" in tipo_nome and "SEÇÃO" in nome_upper:
            self.add_error('nome_unidade', f"Inconsistência: O tipo é '{tipo.nome}', mas o nome contém 'Seção'.")
        
        if "SEÇÃO" in tipo_nome and "SETOR" in nome_upper and "SETORIAL" not in nome_upper:
            self.add_error('nome_unidade', f"Inconsistência: O tipo é '{tipo.nome}', mas o nome contém 'Setor'.")

        return cleaned_data


class ModeloReferencialForm(forms.ModelForm):
    class Meta:
        model = ModeloReferencial
        fields = ['nome', 'dimensionamento', 'descricao', 'resolucao_referencia', 'ativo']
        widgets = {
            'descricao': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Descreva o propósito deste modelo...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        self.fields['ativo'].widget.attrs.update({'class': 'form-check-input'})

class UnitModeloForm(forms.ModelForm):
    tipos_resolucao_permitidos = forms.ModelMultipleChoiceField(
        queryset=TipoUnidade.objects.none(),
        required=False,
        label="Tipos de Resolução no Campus",
        widget=forms.SelectMultiple(attrs={'class': 'form-control', 'size': 4})
    )
    cargos_resolucao_permitidos = forms.ModelMultipleChoiceField(
        queryset=CargoFuncao.objects.none(),
        required=False,
        label="Cargos Derivados da Resolução",
        widget=forms.SelectMultiple(attrs={'class': 'form-control', 'size': 4})
    )

    class Meta:
        model = UnitModelo
        fields = [
            'unidade_pai', 'tipo_unidade', 'cargo_funcao_ref', 'cargo_funcao', 'sigla_cargo',
            'nome_unidade', 'sigla_unidade', 'atribuicoes', 'is_agrupamento', 'layout_filhos',
            'permite_resolucao_flexivel', 'tipos_resolucao_permitidos', 'cargos_resolucao_permitidos'
        ]
        widgets = {
            'tipo_unidade': TipoUnidadeSelect(attrs={'class': 'form-control'}),
            'nome_unidade': forms.TextInput(attrs={'placeholder': 'Ex: Diretoria de Ensino'}),
            'sigla_unidade': forms.TextInput(attrs={'placeholder': 'Ex: DE'}),
            'atribuicoes': forms.Textarea(attrs={'rows': 3}),
            'cargo_funcao': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Auditor(a) Interno'}),
        }

    def __init__(self, *args, **kwargs):
        modelo = kwargs.pop('modelo', None)
        super().__init__(*args, **kwargs)
        
        # Dropdown de siglas dinÃ¢mico
        opcoes_sigla = CargoFuncao.objects.values_list('sigla', 'sigla').distinct().order_by('sigla')
        self.fields['sigla_cargo'] = forms.ChoiceField(
            choices=[("", "Selecione...")] + list(opcoes_sigla),
            required=False,
            widget=forms.Select(attrs={'class': 'form-control'})
        )

        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-control'})
        
        if modelo:
            self.fields['unidade_pai'].queryset = UnitModelo.objects.filter(modelo=modelo)
            self.fields['unidade_pai'].empty_label = "Nenhuma (Topo da Hierarquia / Raiz)"

            dim = modelo.dimensionamento
            if dim:
                # Inclui tipos exclusivos de modelo referencial (apenas_modelo_referencial=True)
                self.fields['tipo_unidade'].queryset = TipoUnidade.objects.filter(dimensionamentos_permitidos=dim)
                self.fields['cargo_funcao_ref'].queryset = CargoFuncao.objects.filter(dimensionamentos_permitidos=dim)
                self.fields['tipos_resolucao_permitidos'].queryset = TipoUnidade.objects.filter(
                    dimensionamentos_permitidos=dim,
                    apenas_modelo_referencial=False,
                )
                self.fields['cargos_resolucao_permitidos'].queryset = CargoFuncao.objects.filter(
                    dimensionamentos_permitidos=dim
                )

    def clean_sigla_unidade(self):
        sigla = self.cleaned_data.get('sigla_unidade')
        if sigla:
            return sigla.upper()
        return sigla

    def clean(self):
        cleaned_data = super().clean()
        permitir = cleaned_data.get('permite_resolucao_flexivel')
        tipos = cleaned_data.get('tipos_resolucao_permitidos')
        cargos = cleaned_data.get('cargos_resolucao_permitidos')

        if permitir:
            if not tipos:
                self.add_error('tipos_resolucao_permitidos', 'Informe ao menos um tipo permitido para a resolução desta unidade.')
            if tipos:
                required_cargos = []
                missing_defaults = []
                for tipo in tipos:
                    if tipo.cargo_padrao_id:
                        required_cargos.append(tipo.cargo_padrao)
                    elif not tipo.selecao_cargo_livre:
                        missing_defaults.append(tipo.nome)

                if missing_defaults:
                    self.add_error(
                        'tipos_resolucao_permitidos',
                        'Os seguintes tipos precisam ter cargo padrão definido para uso na resolução flexível: ' + ', '.join(missing_defaults) + '.'
                    )

                if required_cargos:
                    cleaned_data['cargos_resolucao_permitidos'] = CargoFuncao.objects.filter(
                        id__in=[cargo.id for cargo in required_cargos]
                    )
                elif not cargos:
                    self.add_error('cargos_resolucao_permitidos', 'Informe ao menos um cargo permitido para a resolução desta unidade.')
            elif not cargos:
                self.add_error('cargos_resolucao_permitidos', 'Informe ao menos um cargo permitido para a resolução desta unidade.')
        return cleaned_data

class CargoFuncaoForm(forms.ModelForm):
    class Meta:
        model = CargoFuncao
        fields = ['nome', 'sigla']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Diretor(a)'}),
            'sigla': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: CD-02'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        nome = (cleaned_data.get('nome') or "").strip()
        sigla = (cleaned_data.get('sigla') or "").strip().upper()
        cleaned_data['nome'] = nome
        cleaned_data['sigla'] = sigla
        nome_upper = nome.upper()
        sigla_upper = sigla.upper()
        if "FG-01 OU FG-02" in nome_upper or "FG-01 OU FG-02" in sigla_upper:
            raise forms.ValidationError(
                "Não cadastre cargos híbridos como 'FG-01 ou FG-02'. Use cargos concretos e configure a resolução flexível diretamente na unidade do Modelo Referencial."
            )
        for cargo in CargoFuncao.objects.exclude(pk=self.instance.pk).only('nome', 'sigla'):
            if (
                _normalize_cadastro_key(cargo.nome) == _normalize_cadastro_key(nome)
                and _normalize_cadastro_key(cargo.sigla) == _normalize_cadastro_key(sigla)
            ):
                raise forms.ValidationError('Já existe um cargo/função cadastrado com este nome e sigla.')
        return cleaned_data


class TipoUnidadeForm(forms.ModelForm):
    class Meta:
        model = TipoUnidade
        fields = ['nome', 'cargo_padrao', 'dimensionamentos_permitidos', 'selecao_cargo_livre', 'apenas_modelo_referencial']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Campus'}),
            'cargo_padrao': forms.Select(attrs={'class': 'form-control'}),
            'dimensionamentos_permitidos': forms.CheckboxSelectMultiple(),
        }

    def clean_nome(self):
        nome = (self.cleaned_data.get('nome') or '').strip()
        nome_upper = (nome or "").upper()
        if "SETOR OU SEÇÃO" in nome_upper or "SETOR OU SECAO" in nome_upper:
            raise forms.ValidationError(
                "Não cadastre tipos híbridos como 'Setor ou Seção'. Use tipos concretos e configure a resolução flexível diretamente na unidade do Modelo Referencial."
            )
        for tipo in TipoUnidade.objects.exclude(pk=self.instance.pk).only('nome'):
            if _normalize_cadastro_key(tipo.nome) == _normalize_cadastro_key(nome):
                raise forms.ValidationError('Já existe um tipo de unidade cadastrado com este nome.')
        return nome


class CustomUserForm(forms.ModelForm):
    campus = forms.ModelChoiceField(queryset=Campus.objects.all(), required=False, label="Campus Responsável", widget=forms.Select(attrs={'class': 'form-control'}))
    is_staff = forms.BooleanField(required=False, label="Admin (Acesso Geral - Gerencia solicitações em análise)")
    is_superuser = forms.BooleanField(required=False, label="Superadmin (Controle Total - Visualiza rascunhos de todos os campi)")
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}), required=False, label="Senha")

    class Meta:
        model = User
        fields = ['username', 'email', 'is_staff', 'is_superuser']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome de Usuário'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email para contato'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['password'].help_text = "Deixe em branco para manter a senha atual."
            self.fields['password'].required = False
            if hasattr(self.instance, 'profile') and self.instance.profile.campus:
                self.fields['campus'].initial = self.instance.profile.campus
        else:
            self.fields['password'].required = True

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if user.is_superuser:
            user.is_staff = True
        if commit:
            user.save()
            profile, _ = Profile.objects.get_or_create(user=user)
            if user.is_staff or user.is_superuser:
                profile.campus = None
            else:
                profile.campus = self.cleaned_data.get('campus')
            profile.save()
        return user


class RegrasAlteracaoModeloForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_regras_help_texts(self)

    class Meta:
        model = RegrasAlteracaoModelo
        fields = [
            'exigir_adequacao_quando_modelo_mudar',
            'limite_flexibilizacao_fg',
            'permite_regra_transicao',
            'prefixos_cargos_bloqueados',
            'prefixos_cargos_flexibilizaveis',
            'departamentos_intocaveis',
            'verificar_sufixo_anexo',
        ]
        widgets = {
            'limite_total_alteracoes': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'exige_vinculo_com_modelo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'exigir_adequacao_quando_modelo_mudar': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'permite_renomeacao': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'limite_renomeacao': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_mudanca_vinculo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'limite_mudanca_vinculo': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_alteracao_cargo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'limite_alteracao_cargo': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_alteracao_tipo_unidade': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'limite_alteracao_tipo_unidade': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_alteracao_sigla': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'limite_alteracao_sigla': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_exclusao_unidade_modelo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'limite_exclusao_unidade_modelo': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_inclusao_unidade_nova': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'limite_inclusao_unidade_nova': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'limite_flexibilizacao_fg': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_regra_transicao': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'prefixos_cargos_bloqueados': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: CD'}),
            'prefixos_cargos_flexibilizaveis': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: FG'}),
            'departamentos_intocaveis': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Gestão de Pessoas, ...'}),
            'verificar_sufixo_anexo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


def _cargo_quota_queryset():
    allowed_siglas = {'CD-1', 'CD-2', 'CD-3', 'CD-4', 'FG-1', 'FG-2', 'FG-3'}
    selected_ids = []
    seen_siglas = set()
    cargos = CargoFuncao.objects.filter(
        models.Q(sigla__istartswith='CD') |
        models.Q(sigla__istartswith='FG')
    ).order_by('sigla', 'nome', 'id')
    for cargo in cargos:
        sigla = (cargo.sigla or '').upper().strip()
        if '-' not in sigla:
            continue
        prefix, number = sigla.split('-', 1)
        if not number.isdigit():
            continue
        canonical_sigla = f"{prefix}-{int(number)}"
        if canonical_sigla not in allowed_siglas or canonical_sigla in seen_siglas:
            continue
        selected_ids.append(cargo.id)
        seen_siglas.add(canonical_sigla)
    return CargoFuncao.objects.filter(id__in=selected_ids).order_by('sigla', 'nome', 'id')


class CargoQuotaInlineFormSet(BaseInlineFormSet):
    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        if 'cargo_funcao' in form.fields:
            queryset = _cargo_quota_queryset()
            instance_cargo_id = getattr(form.instance, 'cargo_funcao_id', None)
            if instance_cargo_id:
                queryset = (queryset | CargoFuncao.objects.filter(pk=instance_cargo_id)).distinct()
            form.fields['cargo_funcao'].queryset = queryset
        return form


ModeloReferencialCotaCargoFormSet = inlineformset_factory(
    ModeloReferencial,
    ModeloReferencialCotaCargo,
    formset=CargoQuotaInlineFormSet,
    fields=['cargo_funcao', 'quantidade'],
    extra=6,
    can_delete=True,
    widgets={
        'cargo_funcao': forms.Select(attrs={'class': 'form-control'}),
        'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
    },
)


CampusCotaCargoFormSet = inlineformset_factory(
    Campus,
    CampusCotaCargo,
    formset=CargoQuotaInlineFormSet,
    fields=['cargo_funcao', 'quantidade'],
    extra=6,
    can_delete=True,
    widgets={
        'cargo_funcao': forms.Select(attrs={'class': 'form-control'}),
        'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
    },
)


class ExcecaoRegraAlteracaoCampusForm(forms.ModelForm):
    class Meta:
        model = ExcecaoRegraAlteracaoCampus
        fields = [
            'campus',
            'limite_total_alteracoes',
            'exige_vinculo_com_modelo',
            'exigir_adequacao_quando_modelo_mudar',
            'permite_renomeacao',
            'limite_renomeacao',
            'permite_mudanca_vinculo',
            'limite_mudanca_vinculo',
            'permite_alteracao_cargo',
            'limite_alteracao_cargo',
            'permite_alteracao_tipo_unidade',
            'limite_alteracao_tipo_unidade',
            'permite_alteracao_sigla',
            'limite_alteracao_sigla',
            'permite_exclusao_unidade_modelo',
            'limite_exclusao_unidade_modelo',
            'permite_inclusao_unidade_nova',
            'limite_inclusao_unidade_nova',
        ]
        widgets = {
            'campus': forms.Select(attrs={'class': 'form-control'}),
            'limite_total_alteracoes': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'exige_vinculo_com_modelo': forms.NullBooleanSelect(attrs={'class': 'form-control'}),
            'exigir_adequacao_quando_modelo_mudar': forms.NullBooleanSelect(attrs={'class': 'form-control'}),
            'permite_renomeacao': forms.NullBooleanSelect(attrs={'class': 'form-control'}),
            'limite_renomeacao': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_mudanca_vinculo': forms.NullBooleanSelect(attrs={'class': 'form-control'}),
            'limite_mudanca_vinculo': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_alteracao_cargo': forms.NullBooleanSelect(attrs={'class': 'form-control'}),
            'limite_alteracao_cargo': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_alteracao_tipo_unidade': forms.NullBooleanSelect(attrs={'class': 'form-control'}),
            'limite_alteracao_tipo_unidade': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_alteracao_sigla': forms.NullBooleanSelect(attrs={'class': 'form-control'}),
            'limite_alteracao_sigla': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_exclusao_unidade_modelo': forms.NullBooleanSelect(attrs={'class': 'form-control'}),
            'limite_exclusao_unidade_modelo': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'permite_inclusao_unidade_nova': forms.NullBooleanSelect(attrs={'class': 'form-control'}),
            'limite_inclusao_unidade_nova': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        modelo = kwargs.pop('modelo', None)
        super().__init__(*args, **kwargs)
        self.modelo = modelo
        _apply_regras_help_texts(self, is_exception=True)
        if modelo:
            self.fields['campus'].queryset = Campus.objects.filter(
                models.Q(modelo_referencial_padrao=modelo) |
                models.Q(dimensionamento_fk=modelo.dimensionamento)
            ).distinct().order_by('nome')

    def clean(self):
        cleaned_data = super().clean()
        campus = cleaned_data.get('campus')
        if self.modelo and campus and campus.modelo_referencial_padrao and campus.modelo_referencial_padrao != self.modelo:
            self.add_error('campus', "O campus selecionado está vinculado a outro Modelo Referencial padrão.")
        return cleaned_data


