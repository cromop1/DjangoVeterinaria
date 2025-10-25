from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # Admin de Django
    path('admin/', admin.site.urls),

    # App principal
    path('', include('Core.urls')),

    # Redirigir la raíz a login si quieres (opcional)
    path('', RedirectView.as_view(pattern_name='login', permanent=False)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / 'static')
