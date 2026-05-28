# Sistema de Configuração e Controle de Alterações do Modelo Referencial

Este plano descreve como implementar uma funcionalidade de configuração para restringir e controlar quais tipos e volumes de alterações podem ser feitos em um Organograma quando derivado de um Modelo Referencial.

## Resumo do Problema
O objetivo é garantir que **todos os organogramas** da instituição sigam o Modelo Referencial estipulado pelo seu tipo de Campus (`Dimensionamento`), permitindo apenas um desvio de padrão ("gordura") configurável. Através de um novo sistema de configuração de regras, determinaremos as tolerâncias de mudança (tipos de alterações e quantidade) ao comparar o organograma atual de um campus com seu respectivo Modelo Referencial. Caso um organograma ultrapasse esses limites (ex: adicionou 6 caixinhas extras quando o limite era 5), o sistema deve identificar a infração e bloqueá-la.

O desafio técnico é realizar este "Diff" (comparação algorítmica) de maneira eficiente e manter as regras devidamente vinculadas aos perfis de campi.

## Proposed Changes

### Modelagem de Dados (`core/models.py`)

1. **Rastreabilidade de Origem:**
   - Adicionar o campo `origem_modelo` (FK para `UnitModelo`) no modelo `Unit`. Como todos os organogramas devem derivar de um padrão, isso permitirá que o sistema saiba exatamente qual caixinha é correspondente a qual no Modelo Referencial, facilitando identificar se ela foi *renomeada*, *movida*, ou se é uma *caixa nova* (`origem_modelo=None`).

2. **Modelo de Regras de Alteração (`RegrasAlteracaoModelo`):**
   - O modelo de configuração possuirá campos atrelados ao normativo institucional (Art. 3º), ditando o limite de flexibilização de FGs por Campus.
   - **Campos Propostos:**
     - `limite_flexibilizacao_inteiro` (int): ex: 1, 3, 5 (transição) ou 6. (Representa as cotas de 25%).
     - `permite_regra_transicao` (bool): Para campi 40/26 ativarem a cota estendida de 5 alterações até atingirem o quadro de servidores exigido.

## Premissas e Decisões de Design (Acordadas)

> [!NOTE]
> As regras abaixo guiarão o desenvolvimento e foram validadas para a execução deste projeto.

1. **Bloqueio Rígido:** A plataforma fará o bloqueio duro (*Hard Block*). Se qualquer limite configurado for ultrapassado, o sistema proíbe a ação (seja proposição, publicação ou edição direta) e mostra uma mensagem clara detalhando o que precisa ser desfeito para se readequar ao limite.
2. **Nascimento Obrigatório Via Modelo:** Organogramas em branco (do zero) não serão permitidos. Todos devem necessariamente nascer de uma cópia de um referencial, validando todo o motor do Diff.
3. **Menu Dedicado de Configuração:** Será criada uma tela/interface dedicada (Menu de Configuração de Regras de Alteração) voltada aos usuários master (Reitoria) para gerenciarem as regras numéricas/atributos, sem necessidade de acessar o /admin puro do Django.
4. **Regras e Normativas de Negócio (Baseadas no Art. 3º e Parágrafos):**
   O motor de validação processará rigidamente as seguintes exigências legais ao realizar o diff do organograma com o `'origem_modelo'`:
   - **Cota de Flexibilidade FGs:** Alterações de *nomenclatura* e/ou *vinculação* de unidades que possuam função gratificada (FG-01 e FG-02) estarão fixadas ao limite quantitativo parametrizado:
      - *Polo de Inovação*: Max 1 unidade.
      - *40/26, 70/45, 90/70 Agrícola*: Max 3 unidades.
      - *150, 150 Agrícola*: Max 6 unidades.
   - **Exigência de Sufixo/Prefixo:** Nomenclaturas alteradas ainda devem verificar e manter o prefixo estipulado pelo Anexo VII.
   - **Bloqueio de Cargos de Direção (CD):** Unidades associadas a sigla CD não possuem flexibilidade alguma. Qualquer tentativa de alteração de nome ou pai retornará bloqueio automático.
   - **Departamentos Intocáveis (Apenas Vinculação):** Caixinhas cujos nomes do referencial sejam "Gestão de Pessoas", "Tecnologia da Informação" e "Assuntos Institucionais" não terão seu nome alterado. A alteração nestes só é permitida na *vinculação* (mudança de pai).
   - **Transição Excepcional (40/26):** Se o campus habilitar a "Regra de Transição" na configuração, terá o teto ampliado para 5 alterações em vez de 3, sujeito ao atingimento da fração de pessoal 25/18.
