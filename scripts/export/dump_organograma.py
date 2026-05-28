import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Organograma

try:
    org = Organograma.objects.get(id=39)
    
    units = []
    for u in org.unidades.all():
        units.append({
            'id': str(u.id),
            'parentId': str(u.unidade_pai.id) if u.unidade_pai else '',
            'name': u.nome_unidade,
            'sigla': u.sigla_unidade or '',
            'is_agrupamento': u.is_agrupamento,
            'layout_filhos': u.layout_filhos
        })
        
    with open('org_debug_39.json', 'w', encoding='utf-8') as f:
        json.dump(units, f, ensure_ascii=False, indent=2)
        
    print("Exportação concluída: org_debug_39.json")
    
except Exception as e:
    print(f"Erro: {e}")
