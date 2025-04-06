import logging
import json
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from expenses.models import RecurringExpense
from expenses.views import generate_expense_from_recurring, update_next_due_date

# Set up logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Generate expenses from recurring expenses that are due'
    
    def handle(self, *args, **options):
        today = timezone.now().date()
        
        # Get all recurring expenses that are due
        due_expenses = RecurringExpense.objects.filter(next_due_date__lte=today)
        
        self.stdout.write(f"Found {due_expenses.count()} recurring expenses due for generation")
        logger.info(f"Found {due_expenses.count()} recurring expenses due for generation")
        
        generated_count = 0
        error_count = 0
        
        for recurring_expense in due_expenses:
            try:
                with transaction.atomic():
                    # Generate the expense
                    expense = generate_expense_from_recurring(recurring_expense)
                    
                    # Update next due date
                    update_next_due_date(recurring_expense)
                    
                    generated_count += 1
                    
                    self.stdout.write(self.style.SUCCESS(
                        f"Generated expense '{expense.title}' from recurring expense '{recurring_expense.title}'"
                    ))
                    logger.info(f"Generated expense '{expense.title}' from recurring expense '{recurring_expense.title}'")
            
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(
                    f"Error generating expense from recurring expense '{recurring_expense.title}': {str(e)}"
                ))
                logger.error(f"Error generating expense from recurring expense '{recurring_expense.title}': {str(e)}")
        
        self.stdout.write(self.style.SUCCESS(
            f"Successfully generated {generated_count} expenses. Errors: {error_count}"
        ))
        logger.info(f"Successfully generated {generated_count} expenses. Errors: {error_count}")