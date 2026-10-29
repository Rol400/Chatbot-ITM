from django.contrib.admin import AdminSite
from django.http import HttpResponse


class ProtectedAdminSite(AdminSite):
    def login(self, request, extra_context=None):
        from . import limits
        from .views import LOGIN_FAILS, LOGIN_LOCK_SECONDS, _login_keys
        if request.method != 'POST':
            return super().login(request, extra_context)
        keys = _login_keys(request, request.POST.get('username', '').strip()[:150])
        if any(limits.count(key) >= LOGIN_FAILS for key in keys):
            response = HttpResponse('Demasiados intentos. Espera 15 minutos e inténtalo de nuevo.',
                                    status=429, content_type='text/plain; charset=utf-8')
            response['Cache-Control'] = 'no-store'
            response['Retry-After'] = str(LOGIN_LOCK_SECONDS)
            return response
        response = super().login(request, extra_context)
        if response.status_code == 302 and request.user.is_authenticated and request.user.is_staff:
            limits.clear(keys[1])
        else:
            for key in keys:
                limits.hit(key, LOGIN_LOCK_SECONDS)
        return response
