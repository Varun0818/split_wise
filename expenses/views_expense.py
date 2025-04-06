from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q  # Add this import for Q objects
from django.core.paginator import Paginator
from datetime import datetime
import csv
from django.http import HttpResponse
from decimal import Decimal
from .models import Expense, Split, Debt, Group
from .forms import ExpenseForm

@login_required
def add_expense(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST, user=request.user)
        
        if form.is_valid():
            # Get form data
            title = form.cleaned_data['title']
            amount = form.cleaned_data['amount']
            paid_by = form.cleaned_data['paid_by']
            group = form.cleaned_data['group']
            split_type = form.cleaned_data['split_type']
            participants = form.cleaned_data['participants']
            
            # Validate participants
            if not participants:
                messages.error(request, "You must select at least one participant.")
                return render(request, 'expenses/add_expense.html', {'form': form})
            
            # Ensure payer is in participants
            if paid_by not in participants:
                participants = list(participants)
                participants.append(paid_by)
            
            # Process different split types
            try:
                with transaction.atomic():
                    # Create the expense
                    expense = Expense.objects.create(
                        title=title,
                        amount=amount,
                        paid_by=paid_by,
                        group=group,
                        split_type=split_type
                    )
                    
                    # Handle different split types
                    if split_type == 'EQUAL':
                        handle_equal_split(expense, participants)
                    elif split_type == 'PERCENTAGE':
                        percentages = {}
                        for participant in participants:
                            percentage_key = f'percentage_{participant.id}'
                            if percentage_key in request.POST:
                                percentages[participant.id] = Decimal(request.POST[percentage_key])
                        
                        # Validate percentages
                        if sum(percentages.values()) != Decimal('100'):
                            raise ValueError("Percentages must sum to 100%")
                        
                        handle_percentage_split(expense, participants, percentages)
                    elif split_type == 'DIRECT':
                        direct_amounts = {}
                        for participant in participants:
                            amount_key = f'amount_{participant.id}'
                            if amount_key in request.POST:
                                direct_amounts[participant.id] = Decimal(request.POST[amount_key])
                        
                        # Validate direct amounts
                        if sum(direct_amounts.values()) != amount:
                            raise ValueError("Direct amounts must sum to the total expense amount")
                        
                        handle_direct_split(expense, participants, direct_amounts)
                    
                    messages.success(request, f"Expense '{title}' was added successfully!")
                    return redirect('dashboard')
            
            except ValueError as e:
                messages.error(request, str(e))
                return render(request, 'expenses/add_expense.html', {'form': form})
        
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = ExpenseForm(user=request.user)
    
    return render(request, 'expenses/add_expense.html', {'form': form})

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

@login_required
def expense_list(request):
    """View for listing all expenses"""
    user = request.user
    expenses = Expense.objects.filter(
        Q(paid_by=user) | Q(splits__user=user)
    ).distinct().order_by('-created_at')
    
    return render(request, 'expenses/expense_list.html', {
        'expenses': expenses
    })

@login_required
def expense_detail(request, expense_id):
    """View for showing expense details"""
    expense = get_object_or_404(Expense, id=expense_id)
    
    # Check if user is authorized to view this expense
    if request.user != expense.paid_by and not expense.splits.filter(user=request.user).exists():
        messages.error(request, "You don't have permission to view this expense.")
        return redirect('dashboard')
    
    return render(request, 'expenses/expense_detail.html', {
        'expense': expense
    })

@login_required
def user_expense_history(request):
    # Get expenses where the user is either the payer or a participant
    expenses = Expense.objects.filter(
        Q(splits__user=request.user) | Q(paid_by=request.user)
    ).distinct().order_by('-created_at')
    
    return render(request, 'expenses/user_expense_history.html', {'expenses': expenses})

@login_required
def export_user_expenses(request):
    """Export all user expenses as CSV"""
    user = request.user
    
    # Get all expenses where the user is a participant
    expenses = Expense.objects.filter(
        Q(expenseparticipant__user=user) | Q(paid_by=user)
    ).distinct().order_by('-created_at')
    
    # Create the HttpResponse with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="my_expenses_{datetime.now().strftime("%Y%m%d")}.csv"'
    
    # Create CSV writer
    writer = csv.writer(response)
    
    # Write header row
    writer.writerow([
        'Group', 'Title', 'Amount', 'Paid By', 'Date', 'Split Type', 
        'Your Share', 'Your Payment', 'Net'
    ])
    
    # Write expense data
    for expense in expenses:
        # Calculate user's share
        try:
            user_split = Split.objects.get(expense=expense, user=user)
            user_share = user_split.amount_owed
        except Split.DoesNotExist:
            user_share = 0
        
        # Calculate user's payment
        user_payment = expense.amount if expense.paid_by == user else 0
        
        # Calculate net
        net = user_payment - user_share
        
        writer.writerow([
            expense.group.name,
            expense.title,
            expense.amount,
            expense.paid_by.username,
            expense.created_at.strftime('%Y-%m-%d'),
            expense.get_split_type_display(),
            user_share,
            user_payment,
            net
        ])
    
    return response