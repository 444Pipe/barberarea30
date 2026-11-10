from django.urls import path
from . import views, views_loyalty

urlpatterns = [
    path('clients/', views.clients_list_view, name='admin_clients_api'),
    path('clients/<str:phone>/history/', views.client_history_view, name='admin_client_history'),

    # Tarjeta de sellos (prueba, solo panel). 'settings/' y 'redemptions/' van
    # antes de '<phone>/' para que no se lean como un celular.
    path('loyalty/', views_loyalty.loyalty_cards_view, name='admin_loyalty_cards'),
    path('loyalty/settings/', views_loyalty.loyalty_settings_view, name='admin_loyalty_settings'),
    path('loyalty/redemptions/<int:pk>/', views_loyalty.loyalty_redemption_delete_view,
         name='admin_loyalty_redemption'),
    path('loyalty/<str:phone>/', views_loyalty.loyalty_card_view, name='admin_loyalty_card'),
    path('loyalty/<str:phone>/redeem/', views_loyalty.loyalty_redeem_view, name='admin_loyalty_redeem'),
]
