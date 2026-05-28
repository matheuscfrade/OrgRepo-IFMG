from django.conf import settings


def environment_info(request):
    """Injeta informações do ambiente em todos os templates."""
    return {
        'IS_MANUAL_TEST': getattr(settings, 'IS_MANUAL_TEST', False),
    }
