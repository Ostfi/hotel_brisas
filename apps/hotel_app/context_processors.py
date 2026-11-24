def hotel_roles(request):
    user = request.user
    if not user.is_authenticated:
        return {
            'hotel_es_personal': False,
            'hotel_es_administrador': False,
        }

    groups = set(user.groups.values_list('name', flat=True))
    es_administrador = user.is_superuser or 'Administradores' in groups
    return {
        'hotel_es_personal': (
            es_administrador
            or user.is_staff
            or 'Recepcionistas' in groups
        ),
        'hotel_es_administrador': es_administrador,
    }
