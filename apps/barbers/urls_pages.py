from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'barbers_pages'

urlpatterns = [
    path('dashboard/', views.dashboard_barbero, name='dashboard_barbero'),
    path('finalizar-cita/', views.finalizar_cita, name='finalizar_cita'),
    # Botón para cerrar sesión. next_page redirige al login administrativo o principal.
    path('salir/', auth_views.LogoutView.as_view(next_page='/admin-panel/login/'), name='barbero_logout'),
]
