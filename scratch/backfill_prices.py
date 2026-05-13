import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'barberarea30.settings')
django.setup()

from apps.bookings.models import Booking
from apps.cashflow.models import Sale

def backfill_booking_prices():
    sales = Sale.objects.exclude(booking__isnull=True)
    updated = 0
    for sale in sales:
        booking = sale.booking
        if booking.status == 'completed' and booking.price != sale.final_price:
            print(f"Updating booking {booking.id}: {booking.price} -> {sale.final_price}")
            booking.price = sale.final_price
            booking.save(update_fields=['price'])
            updated += 1
            
    print(f"Successfully updated {updated} bookings.")

if __name__ == '__main__':
    backfill_booking_prices()
