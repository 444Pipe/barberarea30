from django.core.management.base import BaseCommand
from apps.roi.models import MonthlyROISnapshot, PartnerMonthlyShare
from apps.cashflow.models import Expense

class Command(BaseCommand):
    help = 'Elimina todos los historiales de snapshots de ROI y opcionalmente los egresos para dejar el tablero en ceros'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear-expenses',
            action='store_true',
            help='También elimina todos los egresos (gastos) registrados',
        )

    def handle(self, *args, **options):
        # 1. Eliminar los Snapshots de ROI
        snapshots = MonthlyROISnapshot.objects.all()
        count = snapshots.count()
        snapshots.delete()
        
        self.stdout.write(self.style.SUCCESS(f'✅ Se han eliminado {count} snapshots de ROI correctamente.'))
        
        # 2. Opcional: Eliminar Egresos
        if options['clear_expenses']:
            expenses = Expense.objects.all()
            exp_count = expenses.count()
            expenses.delete()
            self.stdout.write(self.style.SUCCESS(f'✅ Se han eliminado {exp_count} egresos (gastos) correctamente.'))
            
        self.stdout.write(self.style.SUCCESS('El historial está en ceros.'))
