from django.core.management.base import BaseCommand
from expenses.models import Group, Expense, Split, Debt, ParentExpense, RecurringExpense
from django.db import transaction

class Command(BaseCommand):
    help = 'Reset expense history by deleting all expense-related data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Delete all expense data including groups',
        )
        parser.add_argument(
            '--groups',
            action='store_true',
            help='Delete only groups and related expenses',
        )
        parser.add_argument(
            '--expenses',
            action='store_true',
            help='Delete only expenses but keep groups',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options['all'] or (options['groups'] and options['expenses']):
            # Delete everything
            self.stdout.write('Deleting all expense data...')
            Debt.objects.all().delete()
            Split.objects.all().delete()
            Expense.objects.all().delete()
            RecurringExpense.objects.all().delete()
            ParentExpense.objects.all().delete()
            Group.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Successfully deleted all expense data'))
            
        elif options['groups']:
            # Delete groups and related expenses
            self.stdout.write('Deleting all groups and related expenses...')
            Group.objects.all().delete()  # This will cascade delete related expenses
            self.stdout.write(self.style.SUCCESS('Successfully deleted all groups and related expenses'))
            
        elif options['expenses']:
            # Delete only expenses
            self.stdout.write('Deleting all expenses but keeping groups...')
            Debt.objects.all().delete()
            Split.objects.all().delete()
            Expense.objects.all().delete()
            RecurringExpense.objects.all().delete()
            ParentExpense.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Successfully deleted all expenses'))
            
        else:
            self.stdout.write(self.style.WARNING('No action specified. Use --all, --groups, or --expenses'))