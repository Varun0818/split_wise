from decimal import Decimal
from .models import Split, Debt

def handle_equal_split(expense, participants):
    """Handle equal splitting of an expense among participants."""
    total_participants = len(participants)
    amount_per_person = expense.amount / Decimal(total_participants)
    
    # Create splits and update debts
    for participant in participants:
        # If this participant paid, they don't owe anything
        if participant == expense.paid_by:
            # Create a split record with 0 amount owed
            Split.objects.create(
                expense=expense,
                user=participant,
                amount_owed=Decimal('0.00')
            )
        else:
            # Create a split record
            Split.objects.create(
                expense=expense,
                user=participant,
                amount_owed=amount_per_person
            )
            
            # Update debt records
            update_debt(expense.paid_by, participant, amount_per_person, expense.group)

def handle_percentage_split(expense, participants, percentages):
    """Handle percentage-based splitting of an expense."""
    for participant in participants:
        percentage = percentages.get(participant.id, Decimal('0'))
        amount_owed = (percentage / Decimal('100')) * expense.amount
        
        # If this participant paid, they don't owe anything
        if participant == expense.paid_by:
            # Create a split record with 0 amount owed
            Split.objects.create(
                expense=expense,
                user=participant,
                amount_owed=Decimal('0.00'),
                percentage=percentage
            )
        else:
            # Create a split record
            Split.objects.create(
                expense=expense,
                user=participant,
                amount_owed=amount_owed,
                percentage=percentage
            )
            
            # Update debt records
            update_debt(expense.paid_by, participant, amount_owed, expense.group)

def handle_direct_split(expense, participants, direct_amounts):
    """Handle direct amount splitting of an expense."""
    for participant in participants:
        amount_owed = direct_amounts.get(participant.id, Decimal('0'))
        
        # If this participant paid, they don't owe anything
        if participant == expense.paid_by:
            # Create a split record with 0 amount owed
            Split.objects.create(
                expense=expense,
                user=participant,
                amount_owed=Decimal('0.00')
            )
        else:
            # Create a split record
            Split.objects.create(
                expense=expense,
                user=participant,
                amount_owed=amount_owed
            )
            
            # Update debt records
            update_debt(expense.paid_by, participant, amount_owed, expense.group)

def update_debt(creditor, debtor, amount, group):
    """Update or create a debt record between two users."""
    # Check if there's an existing debt in the opposite direction
    try:
        reverse_debt = Debt.objects.get(creditor=debtor, debtor=creditor, group=group)
        
        # If the reverse debt is greater, reduce it
        if reverse_debt.amount > amount:
            reverse_debt.amount -= amount
            reverse_debt.save()
            return
        # If the reverse debt is equal, delete it
        elif reverse_debt.amount == amount:
            reverse_debt.delete()
            return
        # If the reverse debt is less, delete it and create a new debt in the opposite direction
        else:
            new_amount = amount - reverse_debt.amount
            reverse_debt.delete()
            
            debt, created = Debt.objects.get_or_create(
                creditor=creditor,
                debtor=debtor,
                group=group,
                defaults={'amount': new_amount}
            )
            
            if not created:
                debt.amount += new_amount
                debt.save()
            
            return
    
    except Debt.DoesNotExist:
        # No reverse debt exists, so create or update a direct debt
        debt, created = Debt.objects.get_or_create(
            creditor=creditor,
            debtor=debtor,
            group=group,
            defaults={'amount': amount}
        )
        
        if not created:
            debt.amount += amount
            debt.save()