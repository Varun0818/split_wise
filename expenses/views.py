from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.db import transaction
from decimal import Decimal
from .models import Expense, Split, Debt, Group
from .forms import ExpenseForm

def home(request):
    return render(request, 'expenses/home.html')

from django.db.models import Sum, Q, F, Case, When, DecimalField, Value
from django.db.models.functions import Coalesce
from collections import defaultdict

@login_required
def dashboard(request):
    user = request.user
    
    # Calculate total amount owed (where user is debtor)
    total_owed = Debt.objects.filter(
        debtor=user, 
        is_settled=False
    ).aggregate(
        total=Coalesce(Sum('amount'), 0)
    )['total']
    
    # Calculate total amount to receive (where user is creditor)
    total_to_receive = Debt.objects.filter(
        creditor=user, 
        is_settled=False
    ).aggregate(
        total=Coalesce(Sum('amount'), 0)
    )['total']
    
    # Calculate net balance
    net_balance = total_to_receive - total_owed
    
    # Get all groups the user belongs to
    user_groups = Group.objects.filter(members=user)
    
    # Group summary data
    group_summary = []
    for group in user_groups:
        # Amount owed in this group
        group_owed = Debt.objects.filter(
            debtor=user,
            expense__group=group,
            is_settled=False
        ).aggregate(
            total=Coalesce(Sum('amount'), 0)
        )['total']
        
        # Amount to receive in this group
        group_to_receive = Debt.objects.filter(
            creditor=user,
            expense__group=group,
            is_settled=False
        ).aggregate(
            total=Coalesce(Sum('amount'), 0)
        )['total']
        
        # Recent expenses in this group (limit to 5)
        recent_expenses = Expense.objects.filter(
            group=group
        ).order_by('-created_at')[:5]
        
        group_summary.append({
            'group': group,
            'owed': group_owed,
            'to_receive': group_to_receive,
            'net': group_to_receive - group_owed,
            'recent_expenses': recent_expenses
        })
    
    # User breakdown - who owes you and whom you owe
    # People who owe you
    creditor_summary = Debt.objects.filter(
        creditor=user,
        is_settled=False
    ).values('debtor').annotate(
        total_amount=Sum('amount')
    ).order_by('-total_amount')
    
    # People you owe
    debtor_summary = Debt.objects.filter(
        debtor=user,
        is_settled=False
    ).values('creditor').annotate(
        total_amount=Sum('amount')
    ).order_by('-total_amount')
    
    # Enhance the user data with actual user objects
    for summary in creditor_summary:
        summary['user'] = User.objects.get(pk=summary['debtor'])
    
    for summary in debtor_summary:
        summary['user'] = User.objects.get(pk=summary['creditor'])
    
    # Get unsettled debts for the current user (for settle up functionality)
    unsettled_debts = Debt.objects.filter(
        Q(debtor=user) | Q(creditor=user),
        is_settled=False
    ).select_related('debtor', 'creditor', 'expense')
    
    context = {
        'total_owed': total_owed,
        'total_to_receive': total_to_receive,
        'net_balance': net_balance,
        'group_summary': group_summary,
        'creditor_summary': creditor_summary,
        'debtor_summary': debtor_summary,
        'unsettled_debts': unsettled_debts,
    }
    
    return render(request, 'expenses/dashboard.html', context)

def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}! You can now log in.')
            login(request, user)  # Auto-login after registration
            return redirect('dashboard')
    else:
        form = UserCreationForm()
    return render(request, 'expenses/register.html', {'form': form})

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
            debt.save

# Add these to your existing views.py file

# Around line 300-310 (recurring expenses section)
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from .models import RecurringExpense, Expense, Split, Debt
from .forms import RecurringExpenseForm
import json  # Add this import for JSON handling
from django.contrib.auth.models import User  # Add this import for User model

@login_required
def recurring_expenses(request):
    """View to list all recurring expenses for the current user"""
    # Get recurring expenses where the user is either the creator or a participant
    recurring_expenses = RecurringExpense.objects.filter(
        models.Q(paid_by=request.user) | models.Q(participants=request.user)
    ).distinct()
    
    return render(request, 'expenses/recurring_expenses.html', {
        'recurring_expenses': recurring_expenses
    })

@login_required
def add_recurring_expense(request):
    """View to add a new recurring expense"""
    if request.method == 'POST':
        form = RecurringExpenseForm(request.POST, user=request.user)
        
        if form.is_valid():
            # Get form data
            title = form.cleaned_data['title']
            amount = form.cleaned_data['amount']
            paid_by = form.cleaned_data['paid_by']
            group = form.cleaned_data['group']
            frequency = form.cleaned_data['frequency']
            split_type = form.cleaned_data['split_type']
            next_due_date = form.cleaned_data['next_due_date']
            participants = form.cleaned_data['participants']
            
            # Validate participants
            if not participants:
                messages.error(request, "You must select at least one participant.")
                return render(request, 'expenses/add_recurring_expense.html', {'form': form})
            
            # Ensure payer is in participants
            if paid_by not in participants:
                participants = list(participants)
                participants.append(paid_by)
            
            try:
                with transaction.atomic():
                    # Create the recurring expense
                    recurring_expense = RecurringExpense.objects.create(
                        title=title,
                        amount=amount,
                        paid_by=paid_by,
                        group=group,
                        frequency=frequency,
                        split_type=split_type,
                        next_due_date=next_due_date
                    )
                    
                    # Add participants
                    recurring_expense.participants.set(participants)
                    
                    # Handle different split types for future reference
                    if split_type == 'PERCENTAGE':
                        # Store percentages as metadata
                        percentages = {}
                        for participant in participants:
                            percentage_key = f'percentage_{participant.id}'
                            if percentage_key in request.POST:
                                percentages[str(participant.id)] = request.POST[percentage_key]
                        
                        # Save percentages as JSON in a new field or related model
                        # This is a simplified approach - you might want to create a proper model
                        recurring_expense.split_details = json.dumps(percentages)
                        recurring_expense.save()
                        
                    elif split_type == 'DIRECT':
                        # Store direct amounts as metadata
                        direct_amounts = {}
                        for participant in participants:
                            amount_key = f'amount_{participant.id}'
                            if amount_key in request.POST:
                                direct_amounts[str(participant.id)] = request.POST[amount_key]
                        
                        # Save direct amounts as JSON
                        recurring_expense.split_details = json.dumps(direct_amounts)
                        recurring_expense.save()
                    
                    messages.success(request, f"Recurring expense '{title}' was added successfully!")
                    return redirect('recurring_expenses')
            
            except Exception as e:
                messages.error(request, f"Error creating recurring expense: {str(e)}")
                return render(request, 'expenses/add_recurring_expense.html', {'form': form})
        
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = RecurringExpenseForm(user=request.user)
    
    return render(request, 'expenses/add_recurring_expense.html', {'form': form})

@login_required
def edit_recurring_expense(request, expense_id):
    """View to edit an existing recurring expense"""
    recurring_expense = get_object_or_404(RecurringExpense, id=expense_id)
    
    # Check if user has permission to edit
    if recurring_expense.paid_by != request.user and request.user not in recurring_expense.participants.all():
        messages.error(request, "You don't have permission to edit this recurring expense.")
        return redirect('recurring_expenses')
    
    if request.method == 'POST':
        form = RecurringExpenseForm(request.POST, instance=recurring_expense, user=request.user)
        
        if form.is_valid():
            # Get form data
            participants = form.cleaned_data['participants']
            
            # Validate participants
            if not participants:
                messages.error(request, "You must select at least one participant.")
                return render(request, 'expenses/edit_recurring_expense.html', {'form': form, 'expense': recurring_expense})
            
            # Ensure payer is in participants
            if recurring_expense.paid_by not in participants:
                participants = list(participants)
                participants.append(recurring_expense.paid_by)
            
            try:
                with transaction.atomic():
                    # Update the recurring expense
                    form.save()
                    
                    # Update participants
                    recurring_expense.participants.set(participants)
                    
                    # Handle different split types for future reference
                    split_type = form.cleaned_data['split_type']
                    if split_type == 'PERCENTAGE':
                        # Store percentages as metadata
                        percentages = {}
                        for participant in participants:
                            percentage_key = f'percentage_{participant.id}'
                            if percentage_key in request.POST:
                                percentages[str(participant.id)] = request.POST[percentage_key]
                        
                        # Save percentages as JSON
                        recurring_expense.split_details = json.dumps(percentages)
                        recurring_expense.save()
                        
                    elif split_type == 'DIRECT':
                        # Store direct amounts as metadata
                        direct_amounts = {}
                        for participant in participants:
                            amount_key = f'amount_{participant.id}'
                            if amount_key in request.POST:
                                direct_amounts[str(participant.id)] = request.POST[amount_key]
                        
                        # Save direct amounts as JSON
                        recurring_expense.split_details = json.dumps(direct_amounts)
                        recurring_expense.save()
                    
                    messages.success(request, f"Recurring expense '{recurring_expense.title}' was updated successfully!")
                    return redirect('recurring_expenses')
            
            except Exception as e:
                messages.error(request, f"Error updating recurring expense: {str(e)}")
                return render(request, 'expenses/edit_recurring_expense.html', {'form': form, 'expense': recurring_expense})
        
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = RecurringExpenseForm(instance=recurring_expense, user=request.user)
        
        # Pre-select participants
        form.fields['participants'].initial = recurring_expense.participants.all()
    
    return render(request, 'expenses/edit_recurring_expense.html', {'form': form, 'expense': recurring_expense})

@login_required
def delete_recurring_expense(request, expense_id):
    """View to delete a recurring expense"""
    recurring_expense = get_object_or_404(RecurringExpense, id=expense_id)
    
    # Check if user has permission to delete
    if recurring_expense.paid_by != request.user:
        messages.error(request, "You don't have permission to delete this recurring expense.")
        return redirect('recurring_expenses')
    
    if request.method == 'POST':
        recurring_expense.delete()
        messages.success(request, f"Recurring expense '{recurring_expense.title}' was deleted successfully!")
        return redirect('recurring_expenses')
    
    return render(request, 'expenses/delete_recurring_expense.html', {'expense': recurring_expense})

@login_required
def generate_recurring_expense_now(request, expense_id):
    """View to manually generate a recurring expense"""
    recurring_expense = get_object_or_404(RecurringExpense, id=expense_id)
    
    # Check if user has permission
    if recurring_expense.paid_by != request.user:
        messages.error(request, "You don't have permission to generate this recurring expense.")
        return redirect('recurring_expenses')
    
    try:
        # Generate the expense
        generate_expense_from_recurring(recurring_expense)
        
        # Update next due date
        update_next_due_date(recurring_expense)
        
        messages.success(request, f"Recurring expense '{recurring_expense.title}' was generated successfully!")
    except Exception as e:
        messages.error(request, f"Error generating recurring expense: {str(e)}")
    
    return redirect('recurring_expenses')

def generate_expense_from_recurring(recurring_expense):
    """Generate a new expense from a recurring expense"""
    with transaction.atomic():
        # Create the expense
        expense = Expense.objects.create(
            title=f"{recurring_expense.title} (Recurring: {recurring_expense.get_frequency_display()})",
            amount=recurring_expense.amount,
            paid_by=recurring_expense.paid_by,
            group=recurring_expense.group,
            split_type=recurring_expense.split_type
        )
        
        # Get participants
        participants = recurring_expense.participants.all()
        
        # Handle different split types
        if recurring_expense.split_type == 'EQUAL':
            handle_equal_split(expense, participants)
        elif recurring_expense.split_type == 'PERCENTAGE':
            # Get percentages from stored metadata
            try:
                percentages = json.loads(recurring_expense.split_details)
                percentage_dict = {int(k): Decimal(v) for k, v in percentages.items()}
                handle_percentage_split(expense, participants, percentage_dict)
            except (json.JSONDecodeError, AttributeError):
                # Fallback to equal split if percentages are not available
                handle_equal_split(expense, participants)
        elif recurring_expense.split_type == 'DIRECT':
            # Get direct amounts from stored metadata
            try:
                direct_amounts = json.loads(recurring_expense.split_details)
                amount_dict = {int(k): Decimal(v) for k, v in direct_amounts.items()}
                handle_direct_split(expense, participants, amount_dict)
            except (json.JSONDecodeError, AttributeError):
                # Fallback to equal split if direct amounts are not available
                handle_equal_split(expense, participants)
        
        return expense

def update_next_due_date(recurring_expense):
    """Update the next due date based on frequency"""
    current_date = recurring_expense.next_due_date
    
    if recurring_expense.frequency == 'DAILY':
        next_date = current_date + timezone.timedelta(days=1)
    elif recurring_expense.frequency == 'WEEKLY':
        next_date = current_date + timezone.timedelta(weeks=1)
    elif recurring_expense.frequency == 'MONTHLY':
        # Add one month (handle month boundaries)
        month = current_date.month + 1
        year = current_date.year
        if month > 12:
            month = 1
            year += 1
        
        # Handle different month lengths
        day = min(current_date.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month-1])
        next_date = timezone.datetime(year, month, day).date()
    else:
        # Default to one month if frequency is unknown
        next_date = current_date + timezone.timedelta(days=30)
    
    recurring_expense.next_due_date = next_date
    recurring_expense.save()

@login_required
def settle_up(request):
    user = request.user
    
    # Get all unsettled debts where the user is either debtor or creditor
    debts_as_debtor = Debt.objects.filter(
        debtor=user,
        is_settled=False
    ).select_related('creditor', 'expense')
    
    debts_as_creditor = Debt.objects.filter(
        creditor=user,
        is_settled=False
    ).select_related('debtor', 'expense')
    
    # Group debts by creditor (for debts where user is debtor)
    debts_by_creditor = defaultdict(list)
    for debt in debts_as_debtor:
        debts_by_creditor[debt.creditor].append(debt)
    
    # Calculate total owed to each creditor
    creditor_totals = {}
    for creditor, debts in debts_by_creditor.items():
        creditor_totals[creditor] = sum(debt.amount for debt in debts)
    
    # Group debts by debtor (for debts where user is creditor)
    debts_by_debtor = defaultdict(list)
    for debt in debts_as_creditor:
        debts_by_debtor[debt.debtor].append(debt)
    
    # Calculate total owed by each debtor
    debtor_totals = {}
    for debtor, debts in debts_by_debtor.items():
        debtor_totals[debtor] = sum(debt.amount for debt in debts)
    
    # Handle settlement
    if request.method == 'POST':
        settlement_type = request.POST.get('settlement_type')
        
        if settlement_type == 'pay':
            # User is paying someone else
            creditor_id = request.POST.get('creditor_id')
            amount = Decimal(request.POST.get('amount', 0))
            
            if creditor_id and amount > 0:
                creditor = User.objects.get(pk=creditor_id)
                
                # Get all debts owed to this creditor
                debts = Debt.objects.filter(
                    debtor=user,
                    creditor=creditor,
                    is_settled=False
                ).order_by('created_at')
                
                remaining_amount = amount
                
                # Settle debts one by one until the amount is exhausted
                with transaction.atomic():
                    for debt in debts:
                        if remaining_amount >= debt.amount:
                            # Fully settle this debt
                            debt.is_settled = True
                            debt.settled_at = timezone.now()
                            debt.save()
                            remaining_amount -= debt.amount
                        else:
                            # Partially settle this debt
                            # Create a new debt with the remaining amount
                            new_debt = Debt.objects.create(
                                debtor=user,
                                creditor=creditor,
                                expense=debt.expense,
                                amount=debt.amount - remaining_amount
                            )
                            
                            # Mark the original debt as settled
                            debt.amount = remaining_amount
                            debt.is_settled = True
                            debt.settled_at = timezone.now()
                            debt.save()
                            break
                
                messages.success(request, f"Successfully paid ${amount} to {creditor.username}.")
                return redirect('dashboard')
        
        elif settlement_type == 'receive':
            # User is receiving payment from someone else
            debtor_id = request.POST.get('debtor_id')
            amount = Decimal(request.POST.get('amount', 0))
            
            if debtor_id and amount > 0:
                debtor = User.objects.get(pk=debtor_id)
                
                # Get all debts owed by this debtor
                debts = Debt.objects.filter(
                    debtor=debtor,
                    creditor=user,
                    is_settled=False
                ).order_by('created_at')
                
                remaining_amount = amount
                
                # Settle debts one by one until the amount is exhausted
                with transaction.atomic():
                    for debt in debts:
                        if remaining_amount >= debt.amount:
                            # Fully settle this debt
                            debt.is_settled = True
                            debt.settled_at = timezone.now()
                            debt.save()
                            remaining_amount -= debt.amount
                        else:
                            # Partially settle this debt
                            # Create a new debt with the remaining amount
                            new_debt = Debt.objects.create(
                                debtor=debtor,
                                creditor=user,
                                expense=debt.expense,
                                amount=debt.amount - remaining_amount
                            )
                            
                            # Mark the original debt as settled
                            debt.amount = remaining_amount
                            debt.is_settled = True
                            debt.settled_at = timezone.now()
                            debt.save()
                            break
                
                messages.success(request, f"Successfully recorded ${amount} payment from {debtor.username}.")
                return redirect('dashboard')
    
    context = {
        'debts_by_creditor': dict(debts_by_creditor),
        'creditor_totals': creditor_totals,
        'debts_by_debtor': dict(debts_by_debtor),
        'debtor_totals': debtor_totals,
    }
    
    return render(request, 'expenses/settle_up.html', context)



